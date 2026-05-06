#!/usr/bin/env python3
import json
import re
import sys
from datetime import datetime, date

RACES_URL = "https://nycruns.com/races"
HEBCAL_URL = "https://www.hebcal.com/hebcal"

MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}

DATE_RE = re.compile(
    r"((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+\w+\s+\d{1,2},\s+\d{4})"
)


def parse_date(date_str):
    m = re.match(
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
        r"(\w+)\s+(\d{1,2}),\s+(\d{4})",
        date_str.strip()
    )
    if m:
        month = MONTH_MAP.get(m.group(1).lower())
        if month:
            return f"{m.group(3)}-{month}-{m.group(2).zfill(2)}"
    return None


def fetch_hebcal(year):
    import requests
    params = {
        "v": "1", "cfg": "json", "maj": "on", "min": "on", "nx": "off",
        "mf": "off", "ss": "off", "mod": "off", "year": year, "month": "x",
        "c": "off", "geo": "none", "i": "off", "lg": "s",
    }
    try:
        r = requests.get(HEBCAL_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as e:
        print(f"  Warning: Hebcal {year}: {e}", file=sys.stderr)
        return []


def build_holiday_maps(races):
    years = {date.today().year, date.today().year + 1}
    for r in races:
        try:
            years.add(int(r["date"][:4]))
        except Exception:
            pass

    hag_dates = {}
    chol_hamoed_dates = {}
    for year in sorted(years):
        print(f"  Hebcal {year}...")
        for item in fetch_hebcal(year):
            if item.get("category") != "holiday":
                continue
            d = (item.get("date") or "")[:10]
            if not d:
                continue
            title = item.get("title", "")
            if item.get("yomtov"):
                hag_dates[d] = title
            elif item.get("subcat") == "major" and ("Moed" in title or "moed" in title):
                chol_hamoed_dates[d] = title

    print(f"  {len(hag_dates)} Yom Tov, {len(chol_hamoed_dates)} Chol HaMoed")
    return hag_dates, chol_hamoed_dates


def scrape_races():
    print(f"Fetching {RACES_URL} ...", flush=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        print(f"ERROR: playwright import failed: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ))

            print("  Navigating...", flush=True)
            page.goto(RACES_URL, wait_until="networkidle", timeout=30000)
            print("  Page loaded.", flush=True)

            full_text = page.evaluate("() => document.body.innerText")
            print(f"  Page text length: {len(full_text)}", flush=True)
            print("  First 2000 chars:", flush=True)
            print(full_text[:2000], flush=True)

            # Collect race links
            links = page.query_selector_all("a[href*='/race/']")
            url_map = {}
            for link in links:
                href = link.get_attribute("href") or ""
                if not re.search(r"/race/[a-z]", href):
                    continue
                name = (link.inner_text() or "").strip().upper()
                if len(name) < 4:
                    continue
                if href.startswith("/"):
                    href = "https://nycruns.com" + href
                url_map[name] = href
            print(f"  {len(url_map)} race links found", flush=True)

            browser.close()

    except Exception as e:
        print(f"ERROR during browser scrape: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Parse page text
    DIST_RE = re.compile(r"\b(Half Marathon|Marathon|10K|5K|15K|4M)\b")
    LOC_RE  = re.compile(r"([A-Z][^\n]*(?:Park|Island|Center|Garden|Stadium|NY|Brooklyn|Manhattan|Queens|Bronx)[^\n]*)")

    lines = full_text.splitlines()
    current_date_str = None
    current_block = []
    blocks = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = DATE_RE.match(line)
        if m:
            if current_date_str and current_block:
                blocks.append((current_date_str, current_block))
            current_date_str = parse_date(m.group(1))
            current_block = []
        elif current_date_str is not None:
            current_block.append(line)

    if current_date_str and current_block:
        blocks.append((current_date_str, current_block))

    print(f"  {len(blocks)} date blocks found", flush=True)

    races = []
    seen_urls = set()
    for date_str, block_lines in blocks:
        if not date_str:
            continue
        block_text = "\n".join(block_lines)
        dist_matches = list(dict.fromkeys(DIST_RE.findall(block_text)))
        dist_label = "/".join(dist_matches).replace("Half Marathon", "HM") if dist_matches else "Race"
        loc_match = LOC_RE.search(block_text)
        location = re.sub(r"\s*\|\s*", ", ", loc_match.group(1)).strip() if loc_match else "New York, NY"

        for line in block_lines:
            key = line.strip().upper()
            url = url_map.get(key)
            if url and url not in seen_urls:
                seen_urls.add(url)
                races.append({"date": date_str, "name": line.strip(), "dist": dist_label, "loc": location, "url": url})
                print(f"  Found: {date_str} — {line.strip()} ({dist_label})", flush=True)

    today = date.today().isoformat()
    races = sorted([r for r in races if r["date"] >= today], key=lambda r: r["date"])
    print(f"\nTotal upcoming races: {len(races)}", flush=True)
    return races


if __name__ == "__main__":
    races = scrape_races()
    if not races:
        print("ERROR: No races found — aborting.", file=sys.stderr)
        sys.exit(1)

    print("\nFetching Hebcal holiday data...")
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
