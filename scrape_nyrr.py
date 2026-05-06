#!/usr/bin/env python3
"""
Scrapes upcoming races from NYRR.
Returns a list of race dicts with keys: date, name, dist, loc, url, source.
"""

import re
from datetime import date

NYRR_URL = "https://www.nyrr.org/run/race-calendar"

MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}

DATE_RE = re.compile(
    r"((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+\w+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE
)

DIST_RE = re.compile(r"\b(Half Marathon|Marathon|HM|10K|5K|15K|4M|5M|8K)\b", re.IGNORECASE)
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


def parse_page(full_text):
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

    print(f"  [NYRR] {len(blocks)} date blocks found", flush=True)

    races = []
    seen = set()
    for date_str, block_lines in blocks:
        if not date_str:
            continue
        block_text = "\n".join(block_lines)

        dist_matches = DIST_RE.findall(block_text)
        dist_matches = list(dict.fromkeys(NORM.get(d.upper(), d.upper()) for d in dist_matches))
        dist_label = "/".join(dist_matches) if dist_matches else "Race"

        # First substantive non-distance line is the race name,
        # second is the location.
        name = None
        loc = "New York, NY"
        for line in block_lines:
            if DIST_RE.fullmatch(line.strip()):
                continue
            if len(line.strip()) < 4:
                continue
            if name is None:
                name = line.strip()
            else:
                loc = line.strip()
                break

        if not name or name in seen:
            continue
        seen.add(name)

        races.append({
            "date": date_str,
            "name": name,
            "dist": dist_label,
            "loc": loc,
            "url": NYRR_URL,
            "source": "NYRR",
        })
        print(f"  [NYRR] {date_str} — {name} ({dist_label})", flush=True)

    return races


def scrape(page):
    print(f"\nFetching {NYRR_URL} ...", flush=True)
    try:
        page.goto(NYRR_URL, wait_until="networkidle", timeout=30000)
        print("  Page loaded.", flush=True)
    except Exception as e:
        print(f"  Warning: NYRR page load failed: {e}", flush=True)
        return []

    full_text = page.evaluate("() => document.body.innerText")
    print(f"  Page text length: {len(full_text)}", flush=True)
    print("  First 2000 chars:", flush=True)
    print(full_text[:2000], flush=True)

    today = date.today().isoformat()
    races = [r for r in parse_page(full_text) if r["date"] >= today]
    print(f"  [NYRR] {len(races)} upcoming races", flush=True)
    return races
