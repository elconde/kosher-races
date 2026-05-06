#!/usr/bin/env python3
"""
Scrapes upcoming races from NYRR.
Returns a list of race dicts with keys: date, name, dist, loc, url, source.
"""

import re
from datetime import date as date_cls

NYRR_URL = "https://www.nyrr.org/run/race-calendar"

MONTHS = {'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'}
MONTH_TO_NUM = {
    'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04', 'MAY': '05', 'JUN': '06',
    'JUL': '07', 'AUG': '08', 'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12',
}
DAYS_ABBR = {'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'}
TIME_RE = re.compile(r'^\d{1,2}:\d{2}\s+[AP]M$')
DAY_NUM_RE = re.compile(r'^(\d{1,2})$')

DIST_NORM = {
    'half marathon': 'HM',
    'marathon': 'Marathon',
    '10k': '10K',
    '5k': '5K',
    '15k': '15K',
    '8k': '8K',
    '4 miles': '4M',
    '5 miles': '5M',
    '4m': '4M',
    '5m': '5M',
    'hm': 'HM',
}


def norm_dist(dist_line):
    dl = dist_line.strip().lower()
    for key, val in DIST_NORM.items():
        if key == dl or key in dl:
            return val
    return dist_line.strip() or 'Race'


def is_day_num(s):
    m = DAY_NUM_RE.match(s.strip())
    return m is not None and 1 <= int(m.group(1)) <= 31


def event_year(month_num, day_num):
    today = date_cls.today()
    try:
        candidate = date_cls(today.year, month_num, day_num)
        return today.year if candidate >= today else today.year + 1
    except ValueError:
        return today.year


def parse_page(full_text):
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]

    events = []
    seen_names = set()
    i = 0

    while i < len(lines):
        # Date block starts with a bare day number followed by a month abbreviation
        if (is_day_num(lines[i])
                and i + 1 < len(lines)
                and lines[i + 1].upper() in MONTHS):

            day = lines[i].zfill(2)
            month = MONTH_TO_NUM[lines[i + 1].upper()]
            i += 2

            if i < len(lines) and lines[i].upper() in DAYS_ABBR:
                i += 1
            if i < len(lines) and TIME_RE.match(lines[i]):
                i += 1

            # Range event: "-" followed by end-date block; use end date so the
            # event stays visible until it closes.
            if i < len(lines) and lines[i] == '-':
                i += 1
                if (i < len(lines) and is_day_num(lines[i])
                        and i + 1 < len(lines) and lines[i + 1].upper() in MONTHS):
                    day = lines[i].zfill(2)
                    month = MONTH_TO_NUM[lines[i + 1].upper()]
                    i += 2
                    if i < len(lines) and lines[i].upper() in DAYS_ABBR:
                        i += 1
                    if i < len(lines) and TIME_RE.match(lines[i]):
                        i += 1

            yr = event_year(int(month), int(day))
            date_str = f"{yr}-{month}-{day}"

            if i >= len(lines):
                continue
            name = lines[i]
            i += 1

            if not name or len(name) < 3:
                continue

            # Location: short line, not a price, not a month name
            loc = "New York, NY"
            if i < len(lines):
                raw = lines[i]
                if raw and len(raw) < 50 and not raw.startswith('$') and raw.upper() not in MONTHS:
                    loc = raw if 'New York' in raw else raw + ', NY'
                    i += 1

            dist = 'Race'
            if i < len(lines):
                dist = norm_dist(lines[i])
                i += 1

            if (name in seen_names or 'Rising NYRR' in name or 'Virtual' in name
                    or 'Summer Speed Series' in name or 'Kids' in name
                    or 'Girls Run' in name or 'Kids' in dist):
                continue
            seen_names.add(name)

            events.append({
                "date": date_str,
                "name": name,
                "dist": dist,
                "loc": loc,
                "url": NYRR_URL,
                "source": "NYRR",
            })
            print(f"  [NYRR] {date_str} — {name} ({dist})", flush=True)
        else:
            i += 1

    print(f"  [NYRR] {len(events)} events parsed", flush=True)
    return events


def scrape(page):
    print(f"\nFetching {NYRR_URL} ...", flush=True)
    try:
        page.goto(NYRR_URL, wait_until="commit", timeout=30000)
        # SPA: networkidle never fires; a banner "Learn more here." matches
        # generic text selectors before race cards render, so use a fixed wait.
        page.wait_for_timeout(10000)
        print("  Page loaded.", flush=True)
    except Exception as e:
        print(f"  Warning: NYRR page load issue: {e}", flush=True)
        return []

    full_text = page.evaluate("() => document.body.innerText")
    print(f"  Page text length: {len(full_text)}", flush=True)

    today = date_cls.today().isoformat()
    races = [r for r in parse_page(full_text) if r["date"] >= today]
    print(f"  [NYRR] {len(races)} upcoming races", flush=True)
    return races
