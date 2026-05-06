#!/usr/bin/env python3
"""
Scrapes upcoming races from nycruns.com and Jewish holiday data from Hebcal,
then writes races.json with the combined data.

Requires: playwright, requests
  pip install playwright requests
  playwright install chromium --with-deps
"""

import json
import re
import sys
from datetime import datetime, date
import requests
from playwright.sync_api import sync_playwright

RACES_URL = "https://nycruns.com/races"
HEBCAL_URL = "https://www.hebcal.com/hebcal"

MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def parse_date(date_str):
    """Convert 'Saturday, July 25, 2026' -> '2026-07-25'"""
    date_str = date_str.strip()
    m = re.match(
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
        r"(\w+)\s+(\d{1,2}),\s+(\d{4})",
        date_str
    )
    if m:
        month = MONTH_MAP.get(m.group(1).lower())
        if month:
            return f"{m.group(3)}-{month}-{m.group(2).zfill(2)}"
    return None


def fetch_hebcal(year):
    params = {
        "v": "1", "cfg": "json",
        "maj": "on", "min": "on", "nx": "off",
        "mf": "off", "ss": "off", "mod": "off",
        "year": year, "month": "x",
        "c": "off", "geo": "none", "i": "off", "lg": "s",
    }
    try:
        r = requests.get(HEBCAL_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as e:
        print(f"  Warning: could not fetch Hebcal data for {year}: {e}", file=sys.stderr)
        return []


def build_holiday_maps(races):
    years = set()
    today = date.today()
    for r in races:
        try:
            years.add(int(r["date"][:4]))
        except Exception:
            pass
    years.add(today.year)
    years.add(today.year + 1)

    hag_dates = {}
    chol_hamoed_dates = {}

    for year in sorted(years):
        print(f"  Fetching Hebcal holidays for {year}...")
        items = fetch_hebcal(year)
        for item in items:
            if item.get("category") != "holiday":
                continue
            raw_date = item.get("date", "")
            d = raw_date[:10] if raw_date else None
            if not d:
                continue
            title = item.get("title", "")
            if item.get("yomtov"):
                hag_dates[d] = title
            elif item.get("subcat") == "major" and ("Moed" in title or "moed" in title):
                chol_hamoed_dates[d] = title

    print(f"  Found {len(hag_dates)} Yom Tov days, {len(chol_hamoed_dates)} Chol HaMoed days")
    return hag_dates, chol_hamoed_dates


def scrape_races():
    """
    Scrape nycruns.com by extracting the full page text and parsing it
    as a sequence of date-headed race blocks.
    """
    races = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        )
        print(f"Fetching {RACES_URL} ...")
        page.goto(RACES_URL, wait_until="networkidle", timeout=30000)

        # Grab all race entry containers. Each race on nycruns has a link to /race/slug
        # and lives alongside a visible date. We collect per-race data via JS evaluation
        # of the DOM, walking up to find the nearest ancestor that contains a date string.

        # Strategy: get the full innerText of the page, then parse it as structured text.
        # The rendered page text looks like:
        #   "Tuesday, June 16, 2026\nTue, June 16, 2026\n5K\nNYCRUNS Lousy T-Shirt Race...\nProspect Park..."
        # We also collect hrefs separately to match names to URLs.

        full_text = page.evaluate("() => document.body.innerText")

        # Collect all race URLs keyed by the slug portion of the name
        links = page.query_selector_all("a[href*='/race/']")
        url_map = {}  # normalised name -> full url
        for link in links:
            href = link.get_attribute("href") or ""
            if not re.search(r"/race/[a-z]", href):
                continue
            name = (link.inner_text() or "").strip().upper()
            if not name or len(name) < 4:
                continue
            if href.startswith("/"):
                href = "https://nycruns.com" + href
            url_map[name] = href

        browser.close()

    # Parse the full page text into race blocks.
    # Split on lines that look like a full date heading: "Tuesday, June 16, 2026"
    DATE_LINE = re.compile(
        r"^((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+\w+ \d{1,2},\s+\d{4})$"
    )
    DIST_RE = re.compile(r"\b(Half Marathon|Marathon|10K|5K|15K|4M)\b")
    LOC_RE  = re.compile(r"([A-Z][^\n]*(?:Park|Island|Center|Garden|Stadium|NY|Brooklyn|Manhattan|Queens|Bronx)[^\n]*)")

    lines = full_text.splitlines()
    current_date = None
    current_block = []
    blocks = []  # list of (date_str, lines)

    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = DATE_LINE.match(line)
        if m:
            if current_date and current_block:
                blocks.append((current_date, current_block))
            current_date = parse_date(m.group(1))
            current_block = []
        else:
            if current_date:
                current_block.append(line)

    if current_date and current_block:
        blocks.append((current_date, current_block))

    seen_urls = set()
    for date_str, block_lines in blocks:
        if not date_str:
            continue

        block_text = "\n".join(block_lines)

        # Find distance badges
        dist_matches = list(dict.fromkeys(DIST_RE.findall(block_text)))
        dist_label = "/".join(dist_matches).replace("Half Marathon", "HM") if dist_matches else "Race"

        # Find location
        loc_match = LOC_RE.search(block_text)
        location = loc_match.group(1).strip() if loc_match else "New York, NY"
        # Clean up location — remove pipe separators common in nycruns formatting
        location = re.sub(r"\s*\|\s*", ", ", location).strip()

        # Find race name(s) — lines that match a URL key
        for line in block_lines:
            key = line.strip().upper()
            url = url_map.get(key)
            if url and url not in seen_urls:
                seen_urls.add(url)
                races.append({
                    "date": date_str,
                    "name": line.strip(),
                    "dist": dist_label,
                    "loc": location,
                    "url": url,
                })
                print(f"  Found: {date_str} — {line.strip()} ({dist_label})")

    # Sort and drop past races
    races.sort(key=lambda r: r["date"])
    today = date.today().isoformat()
    races = [r for r in races if r["date"] >= today]
    print(f"\nTotal upcoming races found: {len(races)}")
    return races


if __name__ == "__main__":
    races = scrape_races()
    if not races:
        print("ERROR: No races found — aborting to avoid overwriting good data.", file=sys.stderr)
        sys.exit(1)

    print("\nFetching Jewish holiday data from Hebcal...")
    hag_dates, chol_hamoed_dates = build_holiday_maps(races)

    output = {
        "generated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "races": races,
        "hag_dates": hag_dates,
        "chol_hamoed_dates": chol_hamoed_dates,
    }

    with open("races.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Written to races.json")
