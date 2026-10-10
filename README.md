# Python Technologies Statistics

A vacancy scraper for [jobs.dou.ua](https://jobs.dou.ua/) (Python category) and an analysis of which technologies are most frequently mentioned in descriptions, broken down by experience level.

## Project Structure

- `config.py` — general constants, parameters, and a dictionary of technologies with regular expressions.
- `scraper/scrape.py` — an asynchronous vacancy collector (via RSS or `xhr-load`).
- `analysis/analyze.py` — analysis of collected data, chart generation, and history tracking.
- `requirements.txt` — list of dependencies (`httpx`, `beautifulsoup4`, `lxml`, `pandas`, `matplotlib`).
- `.gitignore` — ignores local data and cache (`data/raw/*.jsonl`, `data/history.csv`, `__pycache__/`, `.venv/`).

## How It Works

1. `scraper/scrape.py` collects vacancy links for each experience level (`0-1`, `1-3`, `3-5`, `5plus`). It first tries RSS, and if empty, falls back to `xhr-load` ("Load more"). Then, it downloads the vacancy pages and saves them to `data/raw/vacancies_YYYY-MM-DD.jsonl`.
2. `analysis/analyze.py` searches for technologies using regular expressions from `config.py`, generates charts in `charts/`, and maintains `data/history.csv` for tracking trends.

A vacancy can belong to multiple experience levels simultaneously (e.g., Junior/Middle): in the experience-specific charts, it is counted in each category; in the overall chart, it is counted once.

## Running

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scraper.scrape
python -m analysis.analyze

## Results

- `charts/overall_<date>.png` — top technologies overview
- `charts/by_experience_<date>.png` — technologies by experience level
- `charts/trends.png` — trends over time (appears after 2+ runs on different dates)

## Limitations

- Keyword-based counting: a match in the text does not necessarily mean it is a mandatory requirement.
- The list of technologies and regular expressions can be edited in `config.py`.
- The scraper operates without authentication, with delays between requests. Please respect the website's rules.