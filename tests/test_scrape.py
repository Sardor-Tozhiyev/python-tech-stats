import asyncio

import httpx
import pytest

import config
from scraper import scrape

# ---------- fixtures ----------


@pytest.fixture(autouse=True)
def fast_config(monkeypatch):
    """Фіксовані налаштування і без реальних пауз."""
    monkeypatch.setattr(config, "BASE_URL", "https://jobs.dou.ua")
    monkeypatch.setattr(
        config, "RSS_URL", "https://jobs.dou.ua/vacancies/feeds/"
    )
    monkeypatch.setattr(config, "LIST_URL", "https://jobs.dou.ua/vacancies/")
    monkeypatch.setattr(
        config, "LOAD_URL", "https://jobs.dou.ua/vacancies/xhr-load/"
    )
    monkeypatch.setattr(config, "CATEGORY", "Python")
    monkeypatch.setattr(config, "MAX_LOAD_MORE", 3)
    monkeypatch.setattr(config, "DELAY_SECONDS", 0)

    async def no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(scrape.asyncio, "sleep", no_sleep)


def run(handler, fn):
    """Запускає async-функцію з клієнтом, що відповідає через handler."""

    async def inner():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await fn(client)

    return asyncio.run(inner())


def vacancy_item(n: int) -> str:
    return (
        f'<li class="l-vacancy"><div class="title">'
        f'<a class="vt" href="/companies/c/vacancies/{n}/">Job {n}</a>'
        f"</div></li>"
    )


LISTING_HTML = """
<ul>
  <li class="l-vacancy"><div class="title">
    <a class="vt"
     href="/companies/a/vacancies/1/?utm=x#top">Python Dev</a></div></li>
  <li class="l-vacancy"><div class="title">
    <a class="vt"
     href="https://jobs.dou.ua/companies/b/vacancies/2">Senior</a></div></li>
  <li class="l-vacancy"><div class="title">
    <a class="vt" href="/companies/a/vacancies/1/">Duplicate</a></div></li>
  <li class="l-vacancy"><div class="title"><a class="vt">No href</a></div></li>
  <li><a class="vt" href="/other/">Not a vacancy</a></li>
</ul>
"""

VACANCY_HTML = """
<html><body>
  <h1 class="g-h2">  Python   Developer </h1>
  <div class="date">10 жовтня 2026</div>
  <span class="place">Київ, remote</span>
  <div class="b-typo vacancy-section">
    <p>We use  Django</p>
    <p>and Docker.</p>
  </div>
</body></html>
"""

RSS_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
  <item><title>A</title><link>https://jobs.dou.ua/companies/r/vacancies/99/?x=1</link></item>
  <item><title>No link</title></item>
</channel></rss>
"""


# ---------- clean_url ----------


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "/companies/a/vacancies/1/?utm=x#top",
            "https://jobs.dou.ua/companies/a/vacancies/1/",
        ),
        (
            "https://jobs.dou.ua/companies/a/vacancies/1",
            "https://jobs.dou.ua/companies/a/vacancies/1/",
        ),
        (
            "  /companies/a/vacancies/1///  ",
            "https://jobs.dou.ua/companies/a/vacancies/1/",
        ),
    ],
)
def test_clean_url(raw, expected):
    assert scrape.clean_url(raw) == expected


def test_clean_url_is_idempotent():
    once = scrape.clean_url("/companies/a/vacancies/1/?q=1")
    assert scrape.clean_url(once) == once


# ---------- extract_links ----------


def test_extract_links_normalizes_and_dedupes():
    assert scrape.extract_links(LISTING_HTML) == {
        "https://jobs.dou.ua/companies/a/vacancies/1/",
        "https://jobs.dou.ua/companies/b/vacancies/2/",
    }


@pytest.mark.parametrize(
    "html", ["", "<html></html>", "<ul><li>nothing</li></ul>"]
)
def test_extract_links_empty(html):
    assert scrape.extract_links(html) == set()


# ---------- squash / ok ----------


def test_squash():
    from bs4 import BeautifulSoup

    el = BeautifulSoup("<p>a   b\n c</p>", "lxml").p
    assert scrape.squash(el) == "a b c"
    assert scrape.squash(None) == ""


def test_ok_filters_exceptions_and_none():
    results = [1, None, ValueError("boom"), 2]
    assert scrape.ok(results, "test") == [1, 2]


# ---------- get(): retries ----------


def test_get_retries_on_503_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        status = 503 if len(calls) < 3 else 200
        return httpx.Response(status, text="ok")

    r = run(handler, lambda c: scrape.get(c, "GET", "https://jobs.dou.ua/x/"))
    assert r is not None and r.status_code == 200
    assert len(calls) == 3


def test_get_gives_up_after_four_attempts():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    r = run(handler, lambda c: scrape.get(c, "GET", "https://jobs.dou.ua/x/"))
    assert r is None
    assert len(calls) == 4


def test_get_does_not_retry_404():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404)

    r = run(handler, lambda c: scrape.get(c, "GET", "https://jobs.dou.ua/x/"))
    assert r is None
    assert len(calls) == 1


def test_get_retries_on_timeout():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 2:
            raise httpx.ConnectTimeout("slow")
        return httpx.Response(200, text="ok")

    r = run(handler, lambda c: scrape.get(c, "GET", "https://jobs.dou.ua/x/"))
    assert r is not None
    assert len(calls) == 2


# ---------- parse_vacancy ----------


def test_parse_vacancy_extracts_fields():
    def handler(request):
        return httpx.Response(200, text=VACANCY_HTML)

    url = "https://jobs.dou.ua/companies/a/vacancies/1/"
    result = run(
        handler,
        lambda c: scrape.parse_vacancy(
            c, url, {"3_5y", "1_3y"}, "2026-10-10T12:00:00+00:00"
        ),
    )

    assert result == {
        "url": url,
        "title": "Python Developer",
        "published": "10 жовтня 2026",
        "place": "Київ, remote",
        "experience": ["1_3y", "3_5y"],
        "description": "We use Django and Docker.",
        "scraped_at": "2026-10-10T12:00:00+00:00",
    }


def test_parse_vacancy_without_description_returns_none():
    def handler(request):
        return httpx.Response(200, text="<html><h1 class='g-h2'>T</h1></html>")

    result = run(
        handler,
        lambda c: scrape.parse_vacancy(
            c, "https://jobs.dou.ua/v/1/", {"1_3y"}, "ts"
        ),
    )
    assert result is None


def test_parse_vacancy_http_error_returns_none():
    def handler(request):
        return httpx.Response(404)

    result = run(
        handler,
        lambda c: scrape.parse_vacancy(
            c, "https://jobs.dou.ua/v/1/", {"1_3y"}, "ts"
        ),
    )
    assert result is None


# ---------- collect_links ----------


def test_collect_links_merges_rss_and_listing():
    def handler(request):
        path = request.url.path
        if path.endswith("/feeds/"):
            return httpx.Response(200, text=RSS_XML)
        if path == "/vacancies/":
            return httpx.Response(200, text=LISTING_HTML)
        return httpx.Response(404)

    name, links = run(
        handler, lambda c: scrape.collect_links(c, "1_3y", "1-3")
    )

    assert name == "1_3y"
    assert links == {
        "https://jobs.dou.ua/companies/r/vacancies/99/",
        "https://jobs.dou.ua/companies/a/vacancies/1/",
        "https://jobs.dou.ua/companies/b/vacancies/2/",
    }


def test_collect_links_loads_more_via_xhr():
    first_page = (
        'window.CSRF_TOKEN = "abc123";'
        + "<ul>"
        + "".join(vacancy_item(n) for n in range(20))
        + "</ul>"
    )
    posts = []

    def handler(request):
        path = request.url.path
        if path.endswith("/feeds/"):
            return httpx.Response(200, text="<rss><channel></channel></rss>")
        if path.endswith("/xhr-load/"):
            posts.append(request.content.decode())
            html = "<ul>" + vacancy_item(100) + vacancy_item(101) + "</ul>"
            return httpx.Response(200, json={"html": html, "last": True})
        if path == "/vacancies/":
            return httpx.Response(200, text=first_page)
        return httpx.Response(404)

    _, links = run(
        handler, lambda c: scrape.collect_links(c, "5y_plus", "5plus")
    )

    assert len(links) == 22
    assert "https://jobs.dou.ua/companies/c/vacancies/101/" in links
    assert len(posts) == 1  # "last": True зупиняє цикл
    assert "csrfmiddlewaretoken=abc123" in posts[0]
    assert "count=20" in posts[0]


def test_collect_links_survives_invalid_xhr_json():
    first_page = (
        'window.CSRF_TOKEN = "t";'
        + "<ul>"
        + "".join(vacancy_item(n) for n in range(20))
        + "</ul>"
    )

    def handler(request):
        path = request.url.path
        if path.endswith("/feeds/"):
            return httpx.Response(200, text="<rss><channel></channel></rss>")
        if path.endswith("/xhr-load/"):
            return httpx.Response(200, text="not json")
        return httpx.Response(200, text=first_page)

    _, links = run(
        handler, lambda c: scrape.collect_links(c, "5y_plus", "5plus")
    )
    assert len(links) == 20
