"""Версия бота: Dockerfile записывает UTC-время сборки в файл build_time."""

from datetime import UTC, datetime
from pathlib import Path

_BUILD_TIME_FILE = Path(__file__).with_name("build_time")


def build_time() -> datetime | None:
    """Время сборки Docker-образа (UTC); None — запуск не из Docker-сборки."""
    try:
        raw = _BUILD_TIME_FILE.read_text().strip()
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (OSError, ValueError):
        return None
