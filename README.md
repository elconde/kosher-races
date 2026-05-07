# Kosher NYC Races

A web app that lists upcoming NYC races and flags which ones fall on Shabbat or Jewish holidays, so observant runners can plan accordingly.

**Live site:** https://elconde.github.io/kosher-races/

## What it does

- Scrapes upcoming races from [RunningInTheUSA](https://www.runningintheusa.com/) across all five NYC boroughs
- Fetches Jewish holiday data from [Hebcal](https://www.hebcal.com/)
- Classifies each race as Shabbat, Hag (Yom Tov), or Kosher (clear to run)
- Flags Chol HaMoed and Erev holidays in the Holiday column (clear to run but noted)
- Filters by status (Kosher / Shabbat / Hag), organization (NYRR / NYCRUNS), and distance

## Project structure

| File | Purpose |
|------|---------|
| `index.html` | Single-page frontend — loads `races.json` and renders the table |
| `scrape.py` | Main scraper — orchestrates borough scrapers, fetches Hebcal data, writes `races.json` |
| `scrape_runningintheusa.py` | Scrapes runningintheusa.com across all five NYC borough pages |
| `races.json` | Generated data file consumed by the frontend |
| `nyrr.txt` | Reference list of NYRR race names used to tag races in the Org column |
| `.github/workflows/scrape.yml` | GitHub Actions workflow — runs the scraper nightly and commits `races.json` |

## Running the scraper locally

```bash
pip install requests beautifulsoup4
python scrape.py
```

This writes a fresh `races.json`. Open `index.html` in a browser to view the result (you may need a local HTTP server due to the `fetch()` call — e.g. `python -m http.server`).

## How races are classified

| Status | Meaning |
|--------|---------|
| **Kosher** | Clear to run — not Shabbat or Yom Tov |
| **Shabbat** | Falls on Saturday |
| **Hag** | Falls on a Torah-mandated Yom Tov (Diaspora observance) |
| **Shabbat + Hag** | Both |

Chol HaMoed (intermediate days of Pesach/Sukkot) and Erev holidays are classified as Kosher but noted in the Holiday column.

## Adding NYRR races

The `nyrr.txt` file controls which races are tagged as NYRR in the Org column. Add one race name per line. The scraper normalizes sponsor prefixes (TCS, New Balance, Mastercard, etc.) before matching, so both `"NYRR Bronx 10 Mile"` (site name) and `"New Balance Bronx 10 Mile"` (NYRR.org name) match.

## Data sources

- Race listings: [RunningInTheUSA.com](https://www.runningintheusa.com/)
- Holiday data: [Hebcal.com](https://www.hebcal.com/)
