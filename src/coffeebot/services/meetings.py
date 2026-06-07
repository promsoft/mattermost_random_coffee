"""Жизненный цикл встречи: статусы среды, итоги недели, оценки, рейтинг.

State machine описана в spec/architecture.md.
"""

import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coffeebot.db.models import Meeting, MeetingStatus, User

log = logging.getLogger(__name__)

MIDWEEK_STATUSES = {"agreed", "called", "cancelled", "no_contact"}


def get(session: Session, meeting_id: int) -> Meeting | None:
    return session.get(Meeting, meeting_id)


def user_slot(meeting: Meeting, user: User) -> int | None:
    """1 или 2 — какой «стороной» встречи является участник, None — не его встреча."""
    if meeting.user1_id == user.id:
        return 1
    if meeting.user2_id == user.id:
        return 2
    return None


def partner_of(meeting: Meeting, user: User) -> User:
    return meeting.user2 if meeting.user1_id == user.id else meeting.user1


def for_midweek_poll(session: Session, week_start: date) -> list[Meeting]:
    """Встречи недели, по которым пора рассылать опрос среды."""
    return list(
        session.scalars(
            select(Meeting).where(
                Meeting.week_start == week_start,
                Meeting.status == MeetingStatus.SCHEDULED,
                Meeting.midweek_sent_at.is_(None),
            )
        )
    )


def for_survey(session: Session, week_start: date) -> list[Meeting]:
    """Встречи недели, по которым пора рассылать итоговый опрос."""
    return list(
        session.scalars(
            select(Meeting).where(
                Meeting.week_start == week_start,
                Meeting.status == MeetingStatus.SCHEDULED,
                Meeting.survey_sent_at.is_(None),
            )
        )
    )


def set_midweek_status(session: Session, meeting: Meeting, user: User, value: str) -> bool:
    """Записать ответ опроса среды. «Отменили» отменяет встречу. False — не участник."""
    slot = user_slot(meeting, user)
    if slot is None or value not in MIDWEEK_STATUSES:
        return False
    if slot == 1:
        meeting.midweek_status_u1 = value
    else:
        meeting.midweek_status_u2 = value
    if value == "cancelled" and meeting.status == MeetingStatus.SCHEDULED:
        meeting.status = MeetingStatus.CANCELLED
        meeting.cancelled_by = "user"
    session.commit()
    return True


def set_survey_answer(session: Session, meeting: Meeting, user: User, happened: bool) -> bool:
    """Итог недели: состоялась/нет. «Да» приоритетнее «нет» (доверяем подтверждению)."""
    if user_slot(meeting, user) is None:
        return False
    if happened:
        meeting.status = MeetingStatus.COMPLETED
    elif meeting.status == MeetingStatus.SCHEDULED:
        meeting.status = MeetingStatus.CANCELLED
        meeting.cancelled_by = "user"
    session.commit()
    return True


def set_rating(session: Session, meeting: Meeting, user: User, value: int) -> bool:
    """Оценка 0–5 состоявшейся встречи; полученные оценки идут в рейтинг партнёра."""
    slot = user_slot(meeting, user)
    if slot is None or not 0 <= value <= 5 or meeting.status != MeetingStatus.COMPLETED:
        return False
    if slot == 1:
        meeting.rating_u1 = value
    else:
        meeting.rating_u2 = value
    session.commit()
    return True


def close_stale(session: Session, before_week: date) -> int:
    """Встречи прошлых недель без итога → no_response. Возвращает число закрытых."""
    stale = list(
        session.scalars(
            select(Meeting).where(
                Meeting.week_start < before_week,
                Meeting.status == MeetingStatus.SCHEDULED,
            )
        )
    )
    for meeting in stale:
        meeting.status = MeetingStatus.NO_RESPONSE
    if stale:
        session.commit()
        log.info("Закрыто без итога (no_response): %d встреч", len(stale))
    return len(stale)


def ratings(session: Session) -> dict[int, int]:
    """user_id → рейтинг (сумма оценок, полученных от партнёров, по completed)."""
    result: dict[int, int] = {}
    # Оценка, поставленная u1 (rating_u1), получена пользователем u2 — и наоборот
    received_by_u2 = (
        select(Meeting.user2_id.label("uid"), func.sum(Meeting.rating_u1).label("total"))
        .where(Meeting.status == MeetingStatus.COMPLETED, Meeting.rating_u1.is_not(None))
        .group_by(Meeting.user2_id)
    )
    received_by_u1 = (
        select(Meeting.user1_id.label("uid"), func.sum(Meeting.rating_u2).label("total"))
        .where(Meeting.status == MeetingStatus.COMPLETED, Meeting.rating_u2.is_not(None))
        .group_by(Meeting.user1_id)
    )
    for query in (received_by_u2, received_by_u1):
        for uid, total in session.execute(query):
            result[uid] = result.get(uid, 0) + int(total)
    return result
