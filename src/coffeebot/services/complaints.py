"""Жалобы: пауза обвиняемого до разблокировки админом (спека п. 12)."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from coffeebot.db.models import Complaint, ComplaintStatus, Meeting, User, UserState

log = logging.getLogger(__name__)


def create(session: Session, meeting: Meeting, reporter: User, accused: User) -> Complaint:
    """Создать жалобу и поставить обвиняемого на паузу."""
    complaint = Complaint(meeting_id=meeting.id, reporter_id=reporter.id, accused_id=accused.id)
    session.add(complaint)
    accused.state = UserState.PAUSED_BY_COMPLAINT
    session.commit()
    log.info("Жалоба #%d: %s → %s", complaint.id, reporter.username, accused.username)
    return complaint


def open_list(session: Session) -> list[Complaint]:
    return list(
        session.scalars(
            select(Complaint).where(Complaint.status == ComplaintStatus.OPEN)
        )
    )


def resolve_for(session: Session, accused: User) -> int:
    """Закрыть открытые жалобы на участника (при разблокировке админом)."""
    complaints = list(
        session.scalars(
            select(Complaint).where(
                Complaint.accused_id == accused.id,
                Complaint.status == ComplaintStatus.OPEN,
            )
        )
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    for complaint in complaints:
        complaint.status = ComplaintStatus.RESOLVED
        complaint.resolved_at = now
    session.commit()
    return len(complaints)
