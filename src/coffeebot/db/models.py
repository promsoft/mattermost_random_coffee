"""Модели БД. Схема описана в spec/architecture.md."""

import enum
from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _enum(enum_cls):
    """StrEnum → VARCHAR со значениями (не именами) членов."""
    return SAEnum(enum_cls, values_callable=lambda e: [m.value for m in e], native_enum=False)


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
    state: Mapped[UserState] = mapped_column(_enum(UserState), default=UserState.ACTIVE)
    # Сколько недель подряд участник остался без пары — приоритет при матчинге
    unmatched_streak: Mapped[int] = mapped_column(default=0)
    # Следующее сообщение пользователя сохраняется как профиль
    awaiting_profile: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.state.value})>"


class MeetingStatus(enum.StrEnum):
    SCHEDULED = "scheduled"  # пара собрана, ждём встречи
    DECLINED = "declined"  # участник отказался от этой пары
    POSTPONE_PENDING = "postpone_pending"  # предложен перенос, ждём ответа второго
    POSTPONED = "postponed"  # перенос принят, создана встреча на след. неделю
    CANCELLED = "cancelled"  # отменена (участником / админом / при отказе от переноса)
    COMPLETED = "completed"  # созвон состоялся
    NO_RESPONSE = "no_response"  # неделя кончилась, итог не получен


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Понедельник недели, на которую назначена встреча
    week_start: Mapped[date] = mapped_column(Date, index=True)
    user1_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    user2_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[MeetingStatus] = mapped_column(
        _enum(MeetingStatus), default=MeetingStatus.SCHEDULED
    )
    # Ответы опроса среды: agreed | called | cancelled | no_contact
    midweek_status_u1: Mapped[str | None] = mapped_column(String(32), default=None)
    midweek_status_u2: Mapped[str | None] = mapped_column(String(32), default=None)
    # Оценки 0..5, поставленные соответствующим участником
    rating_u1: Mapped[int | None] = mapped_column(default=None)
    rating_u2: Mapped[int | None] = mapped_column(default=None)
    postponed_from_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id"), default=None)
    # Кто предложил перенос (для postpone_pending): отвечает только второй участник
    postpone_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    cancelled_by: Mapped[str | None] = mapped_column(String(16), default=None)  # user | admin
    # Отметки отправки рассылок (идемпотентность: рестарт не дублирует)
    notified_at: Mapped[datetime | None] = mapped_column(default=None)  # карточка пары
    midweek_sent_at: Mapped[datetime | None] = mapped_column(default=None)  # опрос среды
    survey_sent_at: Mapped[datetime | None] = mapped_column(default=None)  # итоговый опрос
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user1: Mapped[User] = relationship(foreign_keys=[user1_id])
    user2: Mapped[User] = relationship(foreign_keys=[user2_id])

    def __repr__(self) -> str:
        return f"<Meeting {self.week_start} #{self.user1_id}+#{self.user2_id} {self.status}>"


class ComplaintStatus(enum.StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), index=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    accused_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[ComplaintStatus] = mapped_column(
        _enum(ComplaintStatus), default=ComplaintStatus.OPEN
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(default=None)

    reporter: Mapped[User] = relationship(foreign_keys=[reporter_id])
    accused: Mapped[User] = relationship(foreign_keys=[accused_id])

    def __repr__(self) -> str:
        return f"<Complaint #{self.id} on user {self.accused_id} ({self.status})>"
