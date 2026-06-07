"""Разбор событий WebSocket Mattermost.

Чистые функции без сетевых вызовов — для тестируемости.
"""

import json
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class IncomingDM:
    """Личное сообщение боту."""

    user_id: str  # mm_user_id отправителя
    username: str  # без @; может быть пустым, тогда добирается через API
    channel_id: str
    text: str


def parse_dm(raw: str, bot_user_id: str) -> IncomingDM | None:
    """Достать из сырого события WebSocket личное сообщение боту (или None)."""
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Не удалось разобрать событие: %.200s", raw)
        return None

    if event.get("event") != "posted":
        return None
    data = event.get("data", {})
    # 'D' = direct message; групповые ('G') и публичные каналы игнорируем
    if data.get("channel_type") != "D":
        return None

    try:
        post = json.loads(data["post"])
    except (KeyError, json.JSONDecodeError):
        log.warning("Событие 'posted' без корректного post: %.200s", raw)
        return None

    if post.get("user_id") == bot_user_id:
        return None  # собственные сообщения бота

    text = (post.get("message") or "").strip()
    if not text:
        return None

    return IncomingDM(
        user_id=post["user_id"],
        username=(data.get("sender_name") or "").lstrip("@"),
        channel_id=post["channel_id"],
        text=text,
    )
