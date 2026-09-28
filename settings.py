"""Crawler settings and the URL extension blacklist."""

import csv
from dataclasses import dataclass
from pathlib import Path


def _load_banned_extensions() -> frozenset[str]:
    path = Path(__file__).with_name("banned_extensions.csv")
    if not path.exists():
        path = Path(__file__).parent / "app" / "banned_extensions.csv"
    with path.open(encoding="utf-8", newline="") as source:
        return frozenset(
            f".{extension.strip().lower().lstrip('.')}"
            for row in csv.reader(source)
            for extension in row
            if extension.strip()
        )


@dataclass(frozen=True)
class Settings:
    BANNED_EXTENSIONS: frozenset[str] = _load_banned_extensions()
    BANNED_DOMAINS: frozenset[str] = frozenset(
        {"wikipedia.org", "web.archive.org", "archive.org", "webcitation.org"}
    )
    MAX_URL_LENGTH: int = 2048

    MAX_WORKERS: int = 32
    MAX_PENDING_URLS: int = 50_000
    DOMAIN_DELAY: float = 1.0
    BASE_BACKOFF: float = 2.0
    MAX_BACKOFF: float = 60.0
    REQUEST_TIMEOUT: float = 5.0
    MAX_CONTENT_LENGTH: int = 10_000_000
    LOG_FILE: str = "crawler.log"
    LOG_LEVEL: str = "INFO"
    LOG_MAX_BYTES: int = 5_000_000
    LOG_BACKUPS: int = 3


settings = Settings()
