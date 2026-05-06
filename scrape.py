#!/usr/bin/env python3
"""
Scrapes upcoming races from nycruns.com and writes races.json.
Requires: playwright (pip install playwright && playwright install chromium)
"""

import json
import re
import sys
from datetime import datetime
from playwright.sync_api import sync_playwright

RACES_URL = "https://nycruns.com/races"

MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}

def parse_date(date_str):
    """Convert 'Saturday, July 25, 2026' -> '2026-07-25'"""
    date_str = date_str.strip()
    # Remove day-of-week prefix if present
    if "," in date_str:
        parts = date_str.split(",")
        if len(parts) == 3:
            # "Saturday, July 25, 2026"
            month_day = parts[1].strip().split()
            year = parts[2].strip()
            month = MONTH_MAP.get(month_day[0].lower(), "00")
            day = month_day[1].zfill(2)
            return f"{year}-{month}-{day}"
        elif len(parts) == 2:
            # "July 25, 2026"
            month_day_year = parts[0].strip().split() + [parts[1].strip()]
            month = MONTH_MAP.get(month_day_year[0].lower(), "00")
            day = month_day_year[1].zfill(2)
            year = month_day_year[2]
            return f"{year}-{month}-{day}"
    return None

def scrape():
    races = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        print(f"Fetching {RACES_URL} ...")
        page.goto(RACES_URL, wait_until="networkidle", timeout=30000)

        # Each race is in a section with a date heading followed by race details.
        # Look for the race calendar entries. The page uses repeated blocks:
        # <div> with date, then race name/link, distance badges, location, time.
        # We'll extract via text content of known selectors.

        # Get all race card elements — try common selectors
        # nycruns uses a table-like layout; grab rows by looking for links to /race/
        race_links = page.query_selector_all("a[href*='/race/']")

        seen_urls = set()
        for link in race_links:
            href = link.get_attribute("href") or ""
            # Skip nav/footer links that aren't race pages
            if not re.search(r"/race/[a-z]", href):
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)

            name = (link.inner_text() or "").strip()
            if not name or len(name) < 4:
                continue

            # Walk up to find the containing block that has date + location info
            block = link
            date_str = None
            location = ""
            distances = []

            for _ in range(8):
                block = page.evaluate("el => el.parentElement", block)
                if not block:
                    break
                text = (page.evaluate("el => el.innerText", block) or "").strip()

                # Look for a date pattern like "Saturday, July 25, 2026"
                date_match = re.search(
                    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
                    r"(\w+ \d{1,2},\s+\d{4})",
                    text
                )
                if date_match:
                    date_str = parse_date(date_match.group(0))

                # Look for location (contains | or "Park" or "Island" etc.)
                loc_match = re.search(r"([A-Z][^\n|]+\|[^\n]+|[A-Z][^\n]+(Park|Island|Center|Garden|Stadium)[^\n]*)", text)
                if loc_match and not location:
                    location = loc_match.group(0).strip()

                # Look for distance badges: HM, 5K, 10K, Marathon
                dist_matches = re.findall(r"\b(Half Marathon|HM|Marathon|10K|5K|15K|4M)\b", text)
                if dist_matches and not distances:
                    distances = list(dict.fromkeys(dist_matches))  # dedupe, preserve order

                if date_str:
                    break

            if not date_str:
                print(f"  Skipping (no date found): {name[:60]}")
                continue

            # Normalise distance label
            dist_label = "/".join(distances) if distances else "Race"
            dist_label = dist_label.replace("Half Marathon", "HM")

            # Make URL absolute
            if href.startswith("/"):
                href = "https://nycruns.com" + href

            race = {
                "date": date_str,
                "name": name,
                "dist": dist_label,
                "loc": location or "New York, NY",
                "url": href,
            }
            races.append(race)
            print(f"  Found: {date_str} — {name} ({dist_label})")

        browser.close()

    # Sort by date
    races.sort(key=lambda r: r["date"])

    # Remove any that are in the past
    today = datetime.today().strftime("%Y-%m-%d")
    races = [r for r in races if r["date"] >= today]

    print(f"\nTotal upcoming races found: {len(races)}")
    return races

if __name__ == "__main__":
    races = scrape()
    if not races:
        print("ERROR: No races found — aborting to avoid overwriting good data.", file=sys.stderr)
        sys.exit(1)

    with open("races.json", "w") as f:
        json.dump(races, f, indent=2)
    print("Written to races.json")
