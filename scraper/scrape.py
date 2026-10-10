import asyncio
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

import config

sem = asyncio.Semaphore(config.CONCURRENCY)


async def request(client, method, url, **kwargs):
    async with sem:
        await asyncio.sleep(config.DELAY_SECONDS)
        try:
            r = await client.request(method, url, timeout=20, **kwargs)
            r.raise_for_status()
            return r
        except httpx.HTTPError as e:
            print(f"[WARN] {method} {url}: {e}")
            return None


def clean_url(url: str) -> str:
    return url.split("?")[0]


async def links_from_rss(client, exp: str) -> set[str]:
    r = await request(client, "GET", config.RSS_URL,
                      params={"category": config.CATEGORY, "exp": exp})
    if not r:
        return set()
    soup = BeautifulSoup(r.text, "xml")
    return {clean_url(i.link.get_text(strip=True))
            for i in soup.find_all("item") if i.link}


def extract_links(html: str) -> set[str]:
    soup = BeautifulSoup(html, "lxml")
    return {clean_url(a["href"])
            for a in soup.select("li.l-vacancy div.title a.vt[href]")}


async def links_from_xhr(client, exp: str) -> set[str]:
    """Запасний шлях. Формат POST (csrfmiddlewaretoken + count) не підтверджено."""
    params = {"category": config.CATEGORY, "exp": exp}
    first = await request(client, "GET", config.LIST_URL, params=params)
    if not first:
        return set()
    links = extract_links(first.text)
    m = re.search(r'window\.CSRF_TOKEN\s*=\s*"([^"]+)"', first.text)
    token = m.group(1) if m else client.cookies.get("csrftoken")
    if not token:
        return links
    count = len(links)
    for _ in range(config.MAX_LOAD_MORE):
        r = await request(
            client, "POST", config.LOAD_URL, params=params,
            data={"csrfmiddlewaretoken": token, "count": count},
            headers={"Referer": str(first.url),
                     "X-Requested-With": "XMLHttpRequest"},
        )
        if not r:
            break
        data = r.json()
        new = extract_links(data.get("html", ""))
        if not new - links:
            break
        links |= new
        count += len(new)
        if data.get("last"):
            break
    return links


async def collect_links(client, level: str, exp: str):
    links = await links_from_rss(client, exp)
    if not links:
        print(f"{level}: RSS empty, trying xhr-load")
        links = await links_from_xhr(client, exp)
    print(f"{level}: {len(links)} links")
    return level, links


async def parse_vacancy(client, url: str, levels: list[str]):
    r = await request(client, "GET", url)
    if not r:
        return None
    soup = BeautifulSoup(r.text, "lxml")
    desc = soup.select_one("div.b-typo.vacancy-section")
    if not desc:
        print(f"[WARN] no description: {url}")
        return None

    def text(sel):
        el = soup.select_one(sel)
        return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""

    return {
        "url": url,
        "title": text("h1.g-h2"),
        "published": text("div.date"),
        "place": text("span.place"),
        "experience": levels,
        "description": re.sub(r"\s+", " ", desc.get_text(" ", strip=True)),
        "scraped_at": date.today().isoformat(),
    }


async def main():
    headers = {"User-Agent": config.USER_AGENT}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        results = await asyncio.gather(*[
            collect_links(client, name, exp)
            for name, exp in config.EXPERIENCE_LEVELS.items()
        ])
        url_levels = defaultdict(list)
        for level, links in results:
            for u in links:
                url_levels[u].append(level)
        print(f"Unique vacancies: {len(url_levels)}")

        vacancies = await asyncio.gather(*[
            parse_vacancy(client, u, lv) for u, lv in url_levels.items()
        ])

    Path(config.RAW_DIR).mkdir(parents=True, exist_ok=True)
    out = Path(config.RAW_DIR) / f"vacancies_{date.today().isoformat()}.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for v in filter(None, vacancies):
            f.write(json.dumps(v, ensure_ascii=False) + "\n")
    print(f"Saved: {out}")


if __name__ == "__main__":
    asyncio.run(main())
