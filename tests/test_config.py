import re

import pytest

import config

FLAGS = re.IGNORECASE


def matches(name: str, text: str) -> bool:
    return re.search(config.TECHNOLOGIES[name], text, FLAGS) is not None


def test_numeric_settings_are_sane():
    assert isinstance(config.CONCURRENCY, int) and config.CONCURRENCY >= 1
    assert config.DELAY_SECONDS >= 0
    assert isinstance(config.MAX_LOAD_MORE, int) and config.MAX_LOAD_MORE >= 0


def test_urls_are_https_and_share_base():
    for name in ("BASE_URL", "RSS_URL", "LIST_URL", "LOAD_URL"):
        value = getattr(config, name)
        assert value.startswith("https://"), name
    for name in ("RSS_URL", "LIST_URL", "LOAD_URL"):
        assert getattr(config, name).startswith(config.BASE_URL), name


def test_experience_levels():
    assert config.EXPERIENCE_LEVELS
    values = list(config.EXPERIENCE_LEVELS.values())
    assert all(isinstance(v, str) and v for v in values)
    assert len(values) == len(set(values)), "duplicate exp values"


def test_all_patterns_compile():
    assert config.TECHNOLOGIES
    for name, pattern in config.TECHNOLOGIES.items():
        re.compile(pattern, FLAGS)  # кине re.error, якщо патерн зламаний


POSITIVE = [
    ("Django", "Experience with Django and DRF"),
    ("Flask", "Flask or FastAPI"),
    ("FastAPI", "We use FastAPI"),
    ("PostgreSQL", "PostgreSQL"),
    ("PostgreSQL", "Postgres"),
    ("MySQL", "MySQL 8"),
    ("Redis", "Redis, Celery"),
    ("Docker", "Docker-compose"),
    ("Kubernetes", "Kubernetes"),
    ("Kubernetes", "k8s"),
    ("AWS", "AWS (S3, EC2)"),
    ("AWS", "Amazon Web Services"),
    ("Celery", "Celery tasks"),
    ("REST", "REST API"),
    ("REST", "REST APIs"),
    ("REST", "REST-API"),
    ("REST", "RESTful services"),
    ("REST", "REST, GraphQL"),
    ("Git", "Git, Docker"),
    ("Pandas", "pandas"),
    ("SQLAlchemy", "SQLAlchemy"),
    ("pytest", "unit tests with pytest"),
    ("RabbitMQ", "RabbitMQ"),
    ("Kafka", "Kafka streams"),
    ("asyncio", "asyncio"),
]

NEGATIVE = [
    ("AWS", "new laws and regulations"),
    ("Redis", "redistribute the load"),
    ("REST", "the rest of the team"),
    ("REST", "take a rest"),
    ("Git", "digital transformation"),
]


@pytest.mark.parametrize("name, text", POSITIVE)
def test_pattern_matches(name, text):
    assert matches(name, text), f"{name!r} should match {text!r}"


@pytest.mark.parametrize("name, text", NEGATIVE)
def test_pattern_does_not_match(name, text):
    assert not matches(name, text), f"{name!r} should not match {text!r}"


def test_every_technology_has_a_positive_example():
    covered = {name for name, _ in POSITIVE}
    assert (
        set(config.TECHNOLOGIES) <= covered
    ), f"no positive example for: {set(config.TECHNOLOGIES) - covered}"
