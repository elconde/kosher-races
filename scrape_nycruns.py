#!/usr/bin/env python3
"""
Scrapes upcoming races from NYCRUNS.
Returns a list of race dicts with keys: date, name, dist, loc, url, source.
"""

import re
from datetime import date

NYCRUNS_URL = "https://nycruns.com/races"

MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}

DATE_RE = re.compile(
    r"((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+\w+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE
)

NON_RACE_SLUGS = {"paid-membership", "membership"}

DIST_RE = re.compile(r"\b(Half Marathon|Marathon|HM|10K|5K|15K|4M)\b", re.IGNORECASE)
LOC_RE  = re.compile(r"([^\n]+\|[^\n]+)")
NORM    = {"HALF MARATHON": "HM", "MARATHON": "Marathon"}


def parse_date(date_str):
    m = re.match(
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
        r"(\w+)\s+(\d{1,2}),\s+(\d{4})",
        date_str.strip(), re.IGNORECASE
    )
    if m:
        month = MONTH_MAP.get(m.group(1).lower())
        if month:
            return f"{m.group(3)}-{month}-{m.group(2).zfill(2)}"
    return None


def parse_page(full_text, url_map):
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

    print(f"  [NYCRUNS] {len(blocks)} date blocks found", flush=True)

    races = []
    seen_urls = set()
    for date_str, block_lines in blocks:
        if not date_str:
            continue
        block_text = "\n".join(block_lines)

        dist_matches = DIST_RE.findall(block_text)
        dist_matches = list(dict.fromkeys(NORM.get(d.upper(), d.upper()) for d in dist_matches))
        dist_label = "/".join(dist_matches) if dist_matches else "Race"

        loc_match = LOC_RE.search(block_text)
        location = re.sub(r"\s*\|\s*", ", ", loc_match.group(1)).strip() if loc_match else "New York, NY"
        loc_clean = re.sub(r',\s*Ny\b', '', location.title()).strip().rstrip(',').strip()

        for line in block_lines:
            key = re.sub(r'\s+', ' ', line).strip().upper()
            url = url_map.get(key)
            if url and url not in seen_urls:
                seen_urls.add(url)
                race_name = re.sub(r'^Nycruns\s+', '', line.strip().title())
                races.append({
                    "date": date_str,
                    "name": race_name,
                    "dist": dist_label,
                    "loc": loc_clean,
                    "url": url,
                    "source": "NYCRUNS",
                })
                print(f"  [NYCRUNS] {date_str} — {race_name} ({dist_label})", flush=True)

    return races


def scrape(page):
    print(f"\nFetching {NYCRUNS_URL} ...", flush=True)
    page.goto(NYCRUNS_URL, wait_until="networkidle", timeout=30000)
    print("  Page loaded.", flush=True)

    full_text = page.evaluate("() => document.body.innerText")
    print(f"  Page text length: {len(full_text)}", flush=True)

    links = page.query_selector_all("a[href*='/race/']")
    url_map = {}
    for link in links:
        href = link.get_attribute("href") or ""
        if not re.search(r"/race/[a-z]", href):
            continue
        slug = href.rstrip("/").split("/")[-1]
        if slug in NON_RACE_SLUGS:
            continue
        name = re.sub(r'\s+', ' ', (link.inner_text() or "")).strip().upper()
        if len(name) < 4:
            continue
        if href.startswith("/"):
            href = "https://nycruns.com" + href
        url_map[name] = href
    print(f"  [NYCRUNS] {len(url_map)} race links found", flush=True)

    today = date.today().isoformat()
    races = [r for r in parse_page(full_text, url_map) if r["date"] >= today]
    print(f"  [NYCRUNS] {len(races)} upcoming races", flush=True)
    return races
