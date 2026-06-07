"""Операции с участниками: регистрация, пауза, профиль."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from coffeebot.db.models import User, UserState

# Профиль — свободный текст, который бот пересылает партнёру и в групповой
# канал пары, поэтому нейтрализуем то, что Mattermost интерпретирует
# (см. spec/security.md, «Пользовательский контент»)
PROFILE_MAX_LEN = 500
_MASS_MENTION_RE = re.compile(r"@(all|channel|here)\b", re.IGNORECASE)
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def sanitize_profile(text: str) -> str:
    """Нейтрализовать markdown-инъекции: масс-пинги и автоподгрузку картинок."""
    text = text.strip()
    text = _MASS_MENTION_RE.sub(r"`@\1`", text)  # @all → `@all` (не пингует)
    text = _IMAGE_RE.sub(r"[\1](\2)", text)  # ![x](url) → [x](url) (без embed/утечки IP)
    return text


def get_by_mm_id(session: Session, mm_user_id: str) -> User | None:
    return session.scalar(select(User).where(User.mm_user_id == mm_user_id))


def register(session: Session, mm_user_id: str, username: str) -> tuple[User, bool]:
    """Зарегистрировать (или возобновить) участника. Возвращает (user, created)."""
    user = get_by_mm_id(session, mm_user_id)
    if user is None:
        user = User(mm_user_id=mm_user_id, username=username, awaiting_profile=True)
        session.add(user)
        session.commit()
        return user, True
    user.username = username  # username мог поменяться
    user.state = UserState.ACTIVE
    session.commit()
    return user, False


def pause(session: Session, user: User) -> bool:
    """Поставить на паузу. False — если пауза административная (снять может админ)."""
    if user.state in (UserState.PAUSED_BY_ADMIN, UserState.PAUSED_BY_COMPLAINT):
        return False
    user.state = UserState.PAUSED
    session.commit()
    return True


def resume(session: Session, user: User) -> bool:
    """Возобновить участие. False — если пауза административная."""
    if user.state in (UserState.PAUSED_BY_ADMIN, UserState.PAUSED_BY_COMPLAINT):
        return False
    user.state = UserState.ACTIVE
    session.commit()
    return True


def get_by_username(session: Session, username: str) -> User | None:
    return session.scalar(select(User).where(User.username == username.lstrip("@")))


def admin_pause(session: Session, user: User) -> None:
    user.state = UserState.PAUSED_BY_ADMIN
    session.commit()


def admin_unpause(session: Session, user: User) -> None:
    """Снять любую паузу (в т.ч. по жалобе)."""
    user.state = UserState.ACTIVE
    session.commit()


def all_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.username)))


def set_profile(session: Session, user: User, text: str) -> bool:
    """Сохранить профиль (с санитизацией). False — слишком длинный."""
    text = sanitize_profile(text)
    if len(text) > PROFILE_MAX_LEN:
        return False
    user.profile = text
    user.awaiting_profile = False
    session.commit()
    return True


def start_profile_edit(session: Session, user: User) -> None:
    user.awaiting_profile = True
    session.commit()
