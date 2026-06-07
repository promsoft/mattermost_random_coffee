"""Операции с участниками: регистрация, пауза, профиль."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from coffeebot.db.models import User, UserState


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


def set_profile(session: Session, user: User, text: str) -> None:
    user.profile = text.strip()
    user.awaiting_profile = False
    session.commit()


def start_profile_edit(session: Session, user: User) -> None:
    user.awaiting_profile = True
    session.commit()
