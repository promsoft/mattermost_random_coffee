"""Построение сообщений с интерактивными кнопками (message attachments).

Кнопка шлёт POST на actions_url с context.action — см. http_app.py.
"""

from coffeebot import texts
from coffeebot.db.models import User, UserState


def _button(label: str, action: str, actions_url: str, **context) -> dict:
    return {
        "id": f"{action}_{context['value']}" if "value" in context else action,
        "name": label,
        "integration": {"url": actions_url, "context": {"action": action, **context}},
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


def midweek_attachments(meeting_id: int, actions_url: str) -> list[dict]:
    """Опрос среды: договорились / созвонились / отменили / не связывались."""
    return [
        {
            "actions": [
                _button(label, "midweek", actions_url, meeting_id=meeting_id, value=value)
                for value, label in texts.BTN_MIDWEEK.items()
            ]
        }
    ]


def survey_attachments(meeting_id: int, actions_url: str) -> list[dict]:
    """Итог недели: состоялась / не состоялась."""
    return [
        {
            "actions": [
                _button(
                    texts.BTN_SURVEY_YES, "survey", actions_url,
                    meeting_id=meeting_id, value="yes",
                ),
                _button(
                    texts.BTN_SURVEY_NO, "survey", actions_url,
                    meeting_id=meeting_id, value="no",
                ),
            ]
        }
    ]


def rating_attachments(meeting_id: int, actions_url: str) -> list[dict]:
    """Оценка встречи 0–5."""
    return [
        {
            "actions": [
                _button(str(i), "rate", actions_url, meeting_id=meeting_id, value=i)
                for i in range(6)
            ]
        }
    ]


def complain_confirm_attachments(meeting_id: int, actions_url: str) -> list[dict]:
    """Подтверждение жалобы (обвиняемый определяется на сервере как партнёр)."""
    return [
        {
            "actions": [
                _button(
                    texts.BTN_COMPLAIN_YES, "complain", actions_url, meeting_id=meeting_id
                )
            ]
        }
    ]
