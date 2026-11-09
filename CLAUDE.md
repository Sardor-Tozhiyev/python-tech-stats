# CLAUDE.md

- Run from the project root via `python -m` (`python -m scraper.scrape`, `python -m analysis.analyze`, `python -m pytest`), because the `import config` lines depend on it.
- CI runs only `black --check .` and `flake8 .`, not pytest. Run the tests yourself. Locally, flake8 needs `--exclude .venv`.
- Never hit the real DOU in tests or "just to check". Network tests go through `httpx.MockTransport` + the `run()` helper and the autouse `fast_config` fixture in `tests/test_scrape.py`.
- All HTTP goes through `scrape.get()`, which handles the semaphore, delay and retries. On failure it returns `None` instead of raising.
- A single vacancy can belong to several experience levels. Overall counts are by unique URL, and per-level counts are percentages within each level. Don't mix the two, or vacancies get double-counted.
- `TECHNOLOGIES` regexes are applied with `case=False`. For a case-sensitive part, use `(?-i:...)` (see `REST`).
- DOU's CSS selectors in `scrape.py` are fragile. If parsing drops sharply, check them first.
- `data/` is gitignored, while `charts/*.png` is committed and linked from the README. When you regenerate charts for a new date, update the links.
- The email in `USER_AGENT` is there on purpose (polite scraping).
