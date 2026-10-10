BASE_URL = "https://jobs.dou.ua"
RSS_URL = f"{BASE_URL}/vacancies/feeds/"
LIST_URL = f"{BASE_URL}/vacancies/"
LOAD_URL = f"{BASE_URL}/vacancies/xhr-load/"

CATEGORY = "Python"

EXPERIENCE_LEVELS = {
    "0_1y": "0-1",
    "1_3y": "1-3",
    "3_5y": "3-5",
    "5y_plus": "5plus",
}

MAX_LOAD_MORE = 15
CONCURRENCY = 3
DELAY_SECONDS = 1.5

USER_AGENT = (
    "Mozilla/5.0 (compatible; PythonTechStats/1.0; "
    "contact: sardor.tozhiev1994@gmail.com)"
)

RAW_DIR = "data/raw"
CHARTS_DIR = "charts"
HISTORY_FILE = "data/history.csv"

TECHNOLOGIES = {
    "Django": r"\bdjango\b",
    "Flask": r"\bflask\b",
    "FastAPI": r"\bfastapi\b",
    "PostgreSQL": r"\bpostgres(?:ql)?\b",
    "MySQL": r"\bmysql\b",
    "Redis": r"\bredis\b",
    "Docker": r"\bdocker\b",
    "Kubernetes": r"\b(?:kubernetes|k8s)\b",
    "AWS": r"\baws\b|\bamazon\s+web\s+services\b",
    "Celery": r"\bcelery\b",
    "REST": r"\brestful\b|\brest[\s-]*apis?\b|(?-i:\bREST\b)",
    "Git": r"\bgit\b",
    "Pandas": r"\bpandas\b",
    "SQLAlchemy": r"\bsqlalchemy\b",
    "pytest": r"\bpytest\b",
    "RabbitMQ": r"\brabbitmq\b",
    "Kafka": r"\bkafka\b",
    "asyncio": r"\basyncio\b",
}
