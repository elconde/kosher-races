#!/usr/bin/env python3
"""
Main scraper — orchestrates NYCRUNS and NYRR scrapers, fetches Hebcal
holiday data, and writes races.json.

Requires: playwright, requests
  pip install playwright requests
  playwright install chromium --with-deps
"""

import json
import sys
import traceback
from datetime import datetime, date

import requests

import scrape_nycruns
import scrape_nyrr

HEBCAL_URL = "https://www.hebcal.com/hebcal"


def fetch_hebcal(year):
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
        print(f"  Hebcal {year}...", flush=True)
        for item in fetch_hebcal(year):
            if item.get("category") != "holiday":
                continue
            d = (item.get("date") or "")[:10]
            if not d:
                continue
            title = item.get("title", "")
            if item.get("yomtov"):
                hag_dates[d] = title
            elif not item.get("yomtov") and (
                "CH''M" in item.get("title_orig", "") or title.startswith("Erev")
            ):
                chol_hamoed_dates[d] = title

    print(f"  {len(hag_dates)} Yom Tov, {len(chol_hamoed_dates)} Chol HaMoed", flush=True)
    return hag_dates, chol_hamoed_dates


def main():
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

            nycruns_races = scrape_nycruns.scrape(page)
            nyrr_races    = scrape_nyrr.scrape(page)

            browser.close()
    except Exception as e:
        print(f"ERROR during scrape: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    today = date.today().isoformat()
    all_races = sorted(
        [r for r in nycruns_races + nyrr_races if r["date"] >= today],
        key=lambda r: (r["date"], r["source"])
    )
    print(f"\nTotal: {len(all_races)} races ({len(nycruns_races)} NYCRUNS, {len(nyrr_races)} NYRR)", flush=True)

    if not all_races:
        print("ERROR: No races found — aborting.", file=sys.stderr)
        sys.exit(1)

    print("\nFetching Hebcal holiday data...", flush=True)
    hag_dates, chol_hamoed_dates = build_holiday_maps(all_races)

    output = {
        "generated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "races": all_races,
        "hag_dates": hag_dates,
        "chol_hamoed_dates": chol_hamoed_dates,
    }

    with open("races.json", "w") as f:
        json.dump(output, f, indent=2)
    print("Written to races.json", flush=True)


if __name__ == "__main__":
    main()
