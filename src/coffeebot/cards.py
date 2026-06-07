"""Построение сообщений с интерактивными кнопками (message attachments).

Кнопка шлёт POST на actions_url с context.action — см. http_app.py.
"""

from coffeebot import texts
from coffeebot.db.models import User, UserState


def _button(label: str, action: str, actions_url: str) -> dict:
    return {
        "id": action,
        "name": label,
        "integration": {"url": actions_url, "context": {"action": action}},
    }


def menu_attachments(user: User | None, actions_url: str) -> list[dict]:
    """Кнопки меню в зависимости от состояния участника."""
    if user is None or user.state == UserState.PAUSED:
        buttons = (
            [_button(texts.BTN_REGISTER, "register", actions_url)]
            if user is None
            else [_button(texts.BTN_RESUME, "resume", actions_url)]
        )
    elif user.state == UserState.ACTIVE:
        buttons = [
            _button(texts.BTN_PAUSE, "pause", actions_url),
            _button(texts.BTN_EDIT_PROFILE, "edit_profile", actions_url),
        ]
    else:  # paused_by_admin / paused_by_complaint — действий нет
        buttons = []
    if buttons:
        return [{"actions": buttons}]
    return []
