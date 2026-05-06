#!/usr/bin/env python3
"""
Scrapes upcoming races from runningintheusa.com (New York, NY).
Returns a list of race dicts with keys: date, name, dist, loc, url, source.
"""

import re
from datetime import datetime, date as date_cls

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.runningintheusa.com"
LIST_URLS = [
    BASE_URL + "/classic/list/new%20york-ny/upcoming/run",
    BASE_URL + "/classic/list/bronx-ny/upcoming/run",
    BASE_URL + "/classic/list/brooklyn-ny/upcoming/run",
    BASE_URL + "/classic/list/queens-ny/upcoming/run",
    BASE_URL + "/classic/list/staten%20island-ny/upcoming/run",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

DIST_NORM = {
    "26.2m": "Marathon",
    "13.1m": "HM",
    "10k": "10K",
    "5k": "5K",
    "8k": "8K",
    "15k": "15K",
    "10m": "10M",
    "5m": "5M",
    "4m": "4M",
    "3m": "3M",
    "2m": "2M",
    "1m": "1M",
}

LOC_MAP = {
    "new york": "Manhattan",
    "manhattan": "Manhattan",
    "brooklyn": "Brooklyn",
    "queens": "Queens",
    "bronx": "Bronx",
    "staten island": "Staten Island",
}

SKIP_KEYWORDS = [
    "virtual", "kids", "children", "youth",
    "summer speed", "girls run", "rising nyrr",
]


def norm_loc(raw):
    lower = raw.lower()
    for key, val in LOC_MAP.items():
        if key in lower:
            return val
    return ""


def norm_dist(dist_str):
    tokens = re.findall(r"[\d.]+[KkMm]", dist_str or "")
    seen = set()
    result = []
    for t in tokens:
        val = DIST_NORM.get(t.lower(), t.upper())
        if val not in seen:
            seen.add(val)
            result.append(val)
    return "/".join(result) if result else "Race"


def parse_date(text):
    text = text.strip()
    try:
        return datetime.strptime(text, "%b %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        pass
    # Handle single-digit day without leading zero: "May 9, 2026"
    parts = text.split()
    if len(parts) == 3:
        try:
            day = parts[1].rstrip(",").zfill(2)
            return datetime.strptime(f"{parts[0]} {day} {parts[2]}", "%b %d %Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def should_skip(name, dist_raw):
    # Check name only — dist_raw often contains "kids run" as a sub-event
    # on otherwise adult races, so don't filter on it.
    name_lower = name.lower()
    return any(kw in name_lower for kw in SKIP_KEYWORDS)


def fetch_page(list_url, n):
    url = f"{list_url}/page-{n}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.text


def parse_total(soup):
    pagination = soup.find("ul", class_="pagination")
    if pagination:
        for li in pagination.find_all("li"):
            m = re.search(r"of\s+(\d+)", li.get_text())
            if m:
                return int(m.group(1))
    return None


def parse_page(html):
    soup = BeautifulSoup(html, "html.parser")

    # Pick the main race-listing table (has a "No" row-number column header).
    # Some pages also have a smaller "Featured Listings" table — skip it.
    table = None
    for t in soup.find_all("table"):
        th = t.find("th")
        if th and "No" in th.get_text():
            table = t
            break
    if not table:
        return [], None

    total = parse_total(soup)

    races = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue  # header row or rowspan continuation row

        # td[0] = row number, td[1] = date, td[2] = race, td[3] = location
        date_div = tds[1].find("div", style=lambda s: s and "font-weight:bold" in s)
        if not date_div:
            continue
        date_str = parse_date(date_div.get_text(strip=True))
        if not date_str:
            continue

        name_b = tds[2].find("b")
        if not name_b:
            continue
        name = name_b.get_text(strip=True)

        dist_divs = tds[2].find_all("div", style=lambda s: s and "padding-left" in s)
        dist_raw = dist_divs[0].get_text(strip=True) if dist_divs else ""
        dist = norm_dist(dist_raw)

        detail_a = tds[2].find("a", href=lambda h: h and "/details/" in h)
        url = (BASE_URL + detail_a["href"]) if detail_a else BASE_URL

        loc_b = tds[3].find("b")
        loc = norm_loc(loc_b.get_text(strip=True)) if loc_b else ""

        if should_skip(name, dist_raw):
            print(f"  [RUSA] Skip: {name}", flush=True)
            continue

        races.append({
            "date": date_str,
            "name": name,
            "dist": dist,
            "loc": loc,
            "url": url,
            "source": "",
        })
        print(f"  [RUSA] {date_str} — {name} ({dist})", flush=True)

    return races, total


def scrape_list(list_url):
    all_races = []
    total = None
    page = 1
    per_page = 20

    while True:
        try:
            html = fetch_page(list_url, page)
        except Exception as e:
            print(f"  Warning: page {page} failed: {e}", flush=True)
            break

        races, page_total = parse_page(html)
        if page == 1 and page_total is not None:
            total = page_total

        all_races.extend(races)

        if not races:
            break
        if total is not None and page * per_page >= total:
            break
        page += 1

    return all_races


def scrape():
    seen_urls = set()
    all_races = []

    for list_url in LIST_URLS:
        print(f"\nFetching {list_url} ...", flush=True)
        for race in scrape_list(list_url):
            if race["url"] not in seen_urls:
                seen_urls.add(race["url"])
                all_races.append(race)

    today = date_cls.today().isoformat()
    upcoming = [r for r in all_races if r["date"] >= today]
    print(f"\n  [RUSA] {len(upcoming)} upcoming races total", flush=True)
    return upcoming
