#!/usr/bin/env python3
"""
Scrapes upcoming races from runningintheusa.com (New York, NY).
Returns a list of race dicts with keys: date, name, dist, loc, url, source.
"""

import os
import re
import subprocess
from datetime import datetime, date as date_cls

from bs4 import BeautifulSoup

BASE_URL = "https://www.runningintheusa.com"
LIST_URLS = [
    (BASE_URL + "/classic/list/new%20york-ny/upcoming/run", "Manhattan"),
    (BASE_URL + "/classic/list/new%20york-county-ny/upcoming/run", "Manhattan"),
    (BASE_URL + "/classic/list/bronx-ny/upcoming/run", "Bronx"),
    (BASE_URL + "/classic/list/bronx-county-ny/upcoming/run", "Bronx"),
    (BASE_URL + "/classic/list/brooklyn-ny/upcoming/run", "Brooklyn"),
    (BASE_URL + "/classic/list/kings-county-ny/upcoming/run", "Brooklyn"),
    (BASE_URL + "/classic/list/queens-ny/upcoming/run", "Queens"),
    (BASE_URL + "/classic/list/queens-county-ny/upcoming/run", "Queens"),
    (BASE_URL + "/classic/list/corona-ny/upcoming/run", "Queens"),
    (BASE_URL + "/classic/list/rockaway%20beach-ny/upcoming/run", "Queens"),
    (BASE_URL + "/classic/list/staten%20island-ny/upcoming/run", "Staten Island"),
    (BASE_URL + "/classic/list/richmond-county-ny/upcoming/run", "Staten Island"),
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

# Patterns stripped before matching race names against nyrr.txt entries.
# The site drops sponsor names; nyrr.txt keeps them.
_STRIP_PREFIX = re.compile(
    r'^\s*(virtual|rising nyrr at the|rising nyrr|nyrr|tcs|new balance|'
    r'mastercard|rbc|citizens|united airlines|maybelline)\s+',
    re.IGNORECASE,
)
_STRIP_SUFFIX = re.compile(
    r'(\s+presented by\s+.*'
    r'|\s*[–\-]\s+women\'?s\s+race'
    r'|\s*\+\s+[\d.]+\s+mile\s+.*'
    r'|\s*&\s+drhazel.*'
    r'|\s*&\s+\d+.*mile.*walk.*)$',
    re.IGNORECASE,
)


def _clean(name):
    n = _STRIP_PREFIX.sub('', name)
    n = _STRIP_SUFFIX.sub('', n)
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', n.lower())).strip()


def _load_nyrr():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nyrr.txt')
    try:
        with open(path, encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []


_NYRR_CLEANED = [_clean(n) for n in _load_nyrr()]


def is_nyrr(race_name):
    r = _clean(race_name)
    for e in _NYRR_CLEANED:
        if r == e:
            return True
        # Only use substring match when the needle is long enough to be distinctive
        if len(r) >= 10 and r in e:
            return True
        if len(e) >= 10 and e in r:
            return True
    return False


SKIP_KEYWORDS = [
    "virtual", "youth", "summer speed", "girls run", "rising nyrr", "gaza",
]


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
    # Cloudflare fingerprints requests' TLS/HTTP2 handshake and blocks it as a
    # bot even from an allowlisted IP with a browser User-Agent; curl passes.
    url = f"{list_url}/page-{n}"
    result = subprocess.run(
        ["curl", "-4", "-s", "--fail", "--max-time", "15",
         "-A", HEADERS["User-Agent"], url],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"curl failed for {url}: exit {result.returncode}: "
            f"{result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout.decode("utf-8", errors="replace")


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

        if should_skip(name, dist_raw):
            print(f"  [RUSA] Skip: {name}", flush=True)
            continue

        races.append({
            "date": date_str,
            "name": name,
            "dist": dist,
            "loc": "",
            "url": url,
            "source": "NYCRUNS" if "NYCRUNS" in name else ("QDR" if name.startswith("QDR") else ("NYRR" if is_nyrr(name) else "")),
        })
        print(f"  [RUSA] {date_str} — {name} ({dist})", flush=True)

    return races, total


def scrape_list(list_url, default_loc):
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

        for race in races:
            race["loc"] = default_loc

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

    for list_url, default_loc in LIST_URLS:
        print(f"\nFetching {list_url} ...", flush=True)
        for race in scrape_list(list_url, default_loc):
            if race["url"] not in seen_urls:
                seen_urls.add(race["url"])
                all_races.append(race)

    today = date_cls.today().isoformat()
    upcoming = [r for r in all_races if r["date"] >= today]
    print(f"\n  [RUSA] {len(upcoming)} upcoming races total", flush=True)
    return upcoming
