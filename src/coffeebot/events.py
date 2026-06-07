"""Разбор событий WebSocket Mattermost.

Чистые функции без сетевых вызовов — для тестируемости.
"""

import json
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class Reply:
    channel_id: str
    message: str


def handle_event(raw: str, bot_user_id: str) -> Reply | None:
    """Обработать сырое событие WebSocket; вернуть ответ или None.

    Этап 0: эхо-бот — отвечаем на любое личное сообщение.
    """
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Не удалось разобрать событие: %.200s", raw)
        return None

    if event.get("event") != "posted":
        return None
    data = event.get("data", {})
    # 'D' = direct message; групповые и публичные каналы игнорируем
    if data.get("channel_type") != "D":
        return None

    try:
        post = json.loads(data["post"])
    except (KeyError, json.JSONDecodeError):
        log.warning("Событие 'posted' без корректного post: %.200s", raw)
        return None

    if post.get("user_id") == bot_user_id:
        return None  # собственные сообщения бота

    message = (post.get("message") or "").strip()
    if not message:
        return None

    return Reply(
        channel_id=post["channel_id"],
        message=f"Эхо: {message}\n\n_Бот в разработке — скоро здесь будет random coffee._",
    )
