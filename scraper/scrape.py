
import asyncio
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

import config


sem = asyncio.Semaphore(config.CONCURRENCY)


async def request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response | None:
    async with sem:
        await asyncio.sleep(config.DELAY_SECONDS)

        try:
            response = await client.request(
                method,
                url,
                timeout=20,
                **kwargs,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            print(f"[WARN] {method} {url}: {exc}")
            return None


def clean_url(url: str) -> str:
    """Remove query parameters and fragments from a vacancy URL."""
    absolute_url = urljoin(config.BASE_URL, url.strip())
    parts = urlsplit(absolute_url)

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path.rstrip("/") + "/",
            "",
            "",
        )
    )


async def links_from_rss(
    client: httpx.AsyncClient,
    exp: str,
) -> set[str]:
    response = await request(
        client,
        "GET",
        config.RSS_URL,
        params={
            "category": config.CATEGORY,
            "exp": exp,
        },
    )

    if response is None:
        return set()

    try:
        soup = BeautifulSoup(response.text, "xml")
    except Exception as exc:
        print(f"[WARN] Cannot parse RSS for {exp}: {exc}")
        return set()

    links = set()

    for item in soup.find_all("item"):
        link = item.find("link")

        if link and link.get_text(strip=True):
            links.add(clean_url(link.get_text(strip=True)))

    return links


def extract_links(html: str) -> set[str]:
    soup = BeautifulSoup(html, "lxml")

    return {
        clean_url(anchor["href"])
        for anchor in soup.select("li.l-vacancy div.title a.vt[href]")
    }


async def links_from_xhr(
    client: httpx.AsyncClient,
    exp: str,
) -> set[str]:
    """Collect additional vacancy links using the DOU XHR endpoint."""
    params = {
        "category": config.CATEGORY,
        "exp": exp,
    }

    first_response = await request(
        client,
        "GET",
        config.LIST_URL,
        params=params,
    )

    if first_response is None:
        return set()

    links = extract_links(first_response.text)

    token_match = re.search(
        r'window\.CSRF_TOKEN\s*=\s*"([^"]+)"',
        first_response.text,
    )
    token = (
        token_match.group(1)
        if token_match
        else client.cookies.get("csrftoken")
    )

    if not token:
        return links

    count = len(links)

    for _ in range(config.MAX_LOAD_MORE):
        response = await request(
            client,
            "POST",
            config.LOAD_URL,
            params=params,
            data={
                "csrfmiddlewaretoken": token,
                "count": count,
            },
            headers={
                "Referer": str(first_response.url),
                "X-Requested-With": "XMLHttpRequest",
            },
        )

        if response is None:
            break

        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            print(
                f"[WARN] XHR returned invalid JSON for experience {exp}"
            )
            break

        if not isinstance(data, dict):
            print(
                f"[WARN] Unexpected XHR response for experience {exp}"
            )
            break

        html = data.get("html", "")

        if not isinstance(html, str):
            print(
                f"[WARN] XHR HTML field is invalid for experience {exp}"
            )
            break

        new_links = extract_links(html) - links

        if not new_links:
            break

        links.update(new_links)
        count += len(new_links)

        if data.get("last"):
            break

    return links


async def collect_links(
    client: httpx.AsyncClient,
    level: str,
    exp: str,
) -> tuple[str, set[str]]:
    rss_links = await links_from_rss(client, exp)
    xhr_links = await links_from_xhr(client, exp)

    links = rss_links | xhr_links

    print(
        f"{level}: RSS={len(rss_links)}, "
        f"XHR={len(xhr_links)}, unique={len(links)}"
    )

    return level, links


async def parse_vacancy(
    client: httpx.AsyncClient,
    url: str,
    levels: list[str],
) -> dict | None:
    response = await request(client, "GET", url)

    if response is None:
        return None

    soup = BeautifulSoup(response.text, "lxml")
    description = soup.select_one("div.b-typo.vacancy-section")

    if description is None:
        print(f"[WARN] No vacancy description: {url}")
        return None

    def text(selector: str) -> str:
        element = soup.select_one(selector)

        if element is None:
            return ""

        return re.sub(
            r"\s+",
            " ",
            element.get_text(" ", strip=True),
        )

    title = text("h1.g-h2")

    if not title:
        print(f"[WARN] No vacancy title: {url}")

    return {
        "url": clean_url(url),
        "title": title,
        "published": text("div.date"),
        "place": text("span.place"),
        "experience": sorted(set(levels)),
        "description": re.sub(
            r"\s+",
            " ",
            description.get_text(" ", strip=True),
        ),
        "scraped_at": date.today().isoformat(),
    }


async def main() -> None:
    headers = {"User-Agent": config.USER_AGENT}

    async with httpx.AsyncClient(
        headers=headers,
        follow_redirects=True,
    ) as client:
        results = await asyncio.gather(
            *[
                collect_links(client, name, exp)
                for name, exp in config.EXPERIENCE_LEVELS.items()
            ]
        )

        url_levels: dict[str, list[str]] = defaultdict(list)

        for level, links in results:
            for url in links:
                if level not in url_levels[url]:
                    url_levels[url].append(level)

        print(f"Unique vacancies: {len(url_levels)}")

        vacancies = await asyncio.gather(
            *[
                parse_vacancy(client, url, levels)
                for url, levels in url_levels.items()
            ]
        )

    Path(config.RAW_DIR).mkdir(parents=True, exist_ok=True)

    output_path = (
        Path(config.RAW_DIR)
        / f"vacancies_{date.today().isoformat()}.jsonl"
    )

    saved_count = 0

    with output_path.open("w", encoding="utf-8") as file:
        for vacancy in vacancies:
            if vacancy is None:
                continue

            file.write(
                json.dumps(vacancy, ensure_ascii=False) + "\n"
            )
            saved_count += 1

    print(f"Saved {saved_count} vacancies to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
