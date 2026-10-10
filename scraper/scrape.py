import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

import config

log = logging.getLogger("scraper")
sem = asyncio.Semaphore(config.CONCURRENCY)
RETRY_STATUSES = {429, 500, 502, 503, 504}


def squash(el):
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""


def clean_url(url):
    parts = urlsplit(urljoin(config.BASE_URL, url.strip()))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path.rstrip("/") + "/", "", "")
    )


def extract_links(html):
    soup = BeautifulSoup(html, "lxml")
    return {
        clean_url(a["href"])
        for a in soup.select("li.l-vacancy div.title a.vt[href]")
    }


async def get(client, method, url, **kwargs):
    """Запит з 4 спробами та експоненційною паузою (пауза поза семафором)."""
    for attempt in range(4):
        async with sem:
            await asyncio.sleep(config.DELAY_SECONDS)
            try:
                r = await client.request(method, url, timeout=20, **kwargs)
                if r.status_code not in RETRY_STATUSES:
                    r.raise_for_status()
                    return r
                log.warning(
                    "HTTP %s %s (attempt %d)", r.status_code, url, attempt + 1
                )
            except httpx.HTTPStatusError as e:
                log.warning("HTTP %s %s", e.response.status_code, url)
                return None
            except httpx.TransportError as e:
                log.warning("%s: %r (attempt %d)", url, e, attempt + 1)
        await asyncio.sleep(2**attempt)
    log.error("Giving up: %s", url)
    return None


async def collect_links(client, name, exp):
    params = {"category": config.CATEGORY, "exp": exp}
    found = set()

    r = await get(client, "GET", config.RSS_URL, params=params)
    if r:
        items = BeautifulSoup(r.text, "xml").find_all("item")
        found |= {
            clean_url(i.link.get_text(strip=True))
            for i in items
            if i.link and i.link.get_text(strip=True)
        }

    r = await get(client, "GET", config.LIST_URL, params=params)
    if not r:
        return name, found

    listed = extract_links(r.text)
    found |= listed
    if not listed:
        log.error("%s: no vacancies in listing, markup may have changed", name)

    m = re.search(r'window\.CSRF_TOKEN\s*=\s*"([^"]+)"', r.text)
    token = m.group(1) if m else client.cookies.get("csrftoken")
    if len(listed) < 20 or not token:
        return name, found

    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Origin": config.BASE_URL,
        "Referer": str(r.url),
        "X-Requested-With": "XMLHttpRequest",
    }
    for _ in range(config.MAX_LOAD_MORE):
        r = await get(
            client,
            "POST",
            config.LOAD_URL,
            params=params,
            headers=headers,
            data={"csrfmiddlewaretoken": token, "count": len(listed)},
        )
        if not r:
            break
        try:
            data = r.json()
            new = extract_links(data["html"]) - listed
        except (ValueError, KeyError, TypeError):
            log.warning("%s: unexpected XHR response", name)
            break
        if not new:
            break
        listed |= new
        found |= new
        if data.get("last"):
            break

    return name, found


async def parse_vacancy(client, url, levels, scraped_at):
    r = await get(client, "GET", url)
    if not r:
        return None

    soup = BeautifulSoup(r.text, "lxml")
    desc = soup.select_one("div.b-typo.vacancy-section")
    if desc is None:
        log.warning("No vacancy description: %s", url)
        return None

    title = squash(soup.select_one("h1.g-h2"))
    if not title:
        log.warning("No vacancy title: %s", url)

    return {
        "url": url,
        "title": title,
        "published": squash(soup.select_one("div.date")),
        "place": squash(soup.select_one("span.place")),
        "experience": sorted(levels),
        "description": squash(desc),
        "scraped_at": scraped_at,
    }


def ok(results, what):
    """Відкидає винятки та None, логуючи винятки."""
    good = []
    for r in results:
        if isinstance(r, Exception):
            log.error("%s failed: %r", what, r)
        elif r is not None:
            good.append(r)
    return good


async def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if config.CONCURRENCY < 1 or config.DELAY_SECONDS < 0:
        raise ValueError("CONCURRENCY must be >= 1 and DELAY_SECONDS >= 0")

    now = datetime.now(timezone.utc)
    scraped_at = now.isoformat(timespec="seconds")

    async with httpx.AsyncClient(
        headers={"User-Agent": config.USER_AGENT}, follow_redirects=True
    ) as client:
        link_results = await asyncio.gather(
            *[
                collect_links(client, n, e)
                for n, e in config.EXPERIENCE_LEVELS.items()
            ],
            return_exceptions=True,
        )

        levels_by_url: dict[str, set[str]] = {}
        for name, links in ok(link_results, "Link collection"):
            log.info("%s: %d links", name, len(links))
            for url in links:
                levels_by_url.setdefault(url, set()).add(name)
        log.info("Unique vacancies: %d", len(levels_by_url))

        vacancy_results = await asyncio.gather(
            *[
                parse_vacancy(client, u, lv, scraped_at)
                for u, lv in levels_by_url.items()
            ],
            return_exceptions=True,
        )
        vacancies = ok(vacancy_results, "Vacancy parsing")

    if levels_by_url and len(vacancies) < len(levels_by_url) / 2:
        log.error(
            "Only %d of %d parsed: markup changed or requests blocked?",
            len(vacancies),
            len(levels_by_url),
        )

    out_dir = Path(config.RAW_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"vacancies_{now:%Y-%m-%d}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for v in vacancies:
            f.write(json.dumps(v, ensure_ascii=False) + "\n")

    log.info("Saved %d vacancies to %s", len(vacancies), path)


if __name__ == "__main__":
    asyncio.run(main())
