"""Модели БД. Схема описана в spec/architecture.md."""

import enum
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserState(enum.StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    PAUSED_BY_ADMIN = "paused_by_admin"
    PAUSED_BY_COMPLAINT = "paused_by_complaint"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    mm_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(255))
    # Свободный текст: контакты (telegram, whatsapp, ...) и пара слов о себе
    profile: Mapped[str | None] = mapped_column(Text, default=None)
    state: Mapped[UserState] = mapped_column(
        SAEnum(UserState, values_callable=lambda e: [m.value for m in e], native_enum=False),
        default=UserState.ACTIVE,
    )
    # Сколько недель подряд участник остался без пары — приоритет при матчинге
    unmatched_streak: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.state.value})>"
