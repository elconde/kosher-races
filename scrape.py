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
from datetime import datetime, date, timedelta
import requests
from playwright.sync_api import sync_playwright

RACES_URL = "https://nycruns.com/races"
HEBCAL_URL = "https://www.hebcal.com/hebcal"

MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}

# Hebcal holiday title substrings that are full Yom Tov (no running)
HAG_KEYWORDS = [
    'Rosh Hashana', 'Yom Kippur',
    'Sukkot I', 'Sukkot II',
    'Shemini Atzeret', 'Shmini Atzeret', 'Simchat Torah',
    'Pesach I', 'Pesach II', 'Pesach VII', 'Pesach VIII',
    'Shavuot I', 'Shavuot II',
]

# Hebcal holiday title substrings that are Chol HaMoed (clear to run, but note it)
CHOL_HAMOED_KEYWORDS = [
    'Chol ha-Moed', 'Chol HaMoed',
]


def parse_date(date_str):
    """Convert 'Saturday, July 25, 2026' -> '2026-07-25'"""
    date_str = date_str.strip()
    if "," in date_str:
        parts = date_str.split(",")
        if len(parts) == 3:
            month_day = parts[1].strip().split()
            year = parts[2].strip()
            month = MONTH_MAP.get(month_day[0].lower(), "00")
            day = month_day[1].zfill(2)
            return f"{year}-{month}-{day}"
        elif len(parts) == 2:
            tokens = parts[0].strip().split() + [parts[1].strip()]
            month = MONTH_MAP.get(tokens[0].lower(), "00")
            day = tokens[1].zfill(2)
            year = tokens[2]
            return f"{year}-{month}-{day}"
    return None


def fetch_hebcal(year):
    """Fetch major holidays from Hebcal for a given Gregorian year."""
    params = {
        "v": "1", "cfg": "json",
        "maj": "on", "min": "off", "nx": "off",
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
    """
    Fetch Hebcal data for years covered by the race list and return
    (hag_dates, chol_hamoed_dates) dicts mapping date strings -> holiday name.
    """
    # Determine which years we need
    years = set()
    today = date.today()
    for r in races:
        try:
            y = int(r["date"][:4])
            years.add(y)
        except Exception:
            pass
    # Also include next year in case races extend that far
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
            if any(kw in title for kw in HAG_KEYWORDS):
                hag_dates[d] = title
            elif any(kw in title for kw in CHOL_HAMOED_KEYWORDS):
                chol_hamoed_dates[d] = title

    print(f"  Found {len(hag_dates)} Yom Tov days, {len(chol_hamoed_dates)} Chol HaMoed days")
    return hag_dates, chol_hamoed_dates


def scrape_races():
    """Use a headless browser to scrape upcoming races from nycruns.com."""
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

        race_links = page.query_selector_all("a[href*='/race/']")
        seen_urls = set()

        for link in race_links:
            href = link.get_attribute("href") or ""
            if not re.search(r"/race/[a-z]", href):
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)

            name = (link.inner_text() or "").strip()
            if not name or len(name) < 4:
                continue

            block = link
            date_str = None
            location = ""
            distances = []

            for _ in range(8):
                block = page.evaluate("el => el.parentElement", block)
                if not block:
                    break
                text = (page.evaluate("el => el.innerText", block) or "").strip()

                date_match = re.search(
                    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
                    r"(\w+ \d{1,2},\s+\d{4})",
                    text
                )
                if date_match:
                    date_str = parse_date(date_match.group(0))

                loc_match = re.search(
                    r"([A-Z][^\n|]+\|[^\n]+|[A-Z][^\n]+(Park|Island|Center|Garden|Stadium)[^\n]*)",
                    text
                )
                if loc_match and not location:
                    location = loc_match.group(0).strip()

                dist_matches = re.findall(r"\b(Half Marathon|HM|Marathon|10K|5K|15K|4M)\b", text)
                if dist_matches and not distances:
                    distances = list(dict.fromkeys(dist_matches))

                if date_str:
                    break

            if not date_str:
                print(f"  Skipping (no date found): {name[:60]}")
                continue

            dist_label = "/".join(distances) if distances else "Race"
            dist_label = dist_label.replace("Half Marathon", "HM")

            if href.startswith("/"):
                href = "https://nycruns.com" + href

            races.append({
                "date": date_str,
                "name": name,
                "dist": dist_label,
                "loc": location or "New York, NY",
                "url": href,
            })
            print(f"  Found: {date_str} — {name} ({dist_label})")

        browser.close()

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
