"""Еженедельный матчинг пар. Алгоритм описан в spec/architecture.md."""

import logging
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coffeebot.db.models import Meeting, MeetingStatus, User, UserState

log = logging.getLogger(__name__)

# Пара не может повториться в течение года (спека п. 9)
PAIR_COOLDOWN_DAYS = 365


@dataclass
class MatchResult:
    week_start: date
    meetings: list[Meeting] = field(default_factory=list)
    unmatched: list[User] = field(default_factory=list)


def current_week_start(today: date) -> date:
    """Понедельник недели, в которую попадает указанная дата."""
    return today - timedelta(days=today.weekday())


def recent_pairs(session: Session, since: date) -> set[frozenset[int]]:
    """Пары, у которых была встреча начиная с `since` (любой статус — спека п. 9)."""
    rows = session.execute(
        select(Meeting.user1_id, Meeting.user2_id).where(Meeting.week_start >= since)
    ).all()
    return {frozenset((u1, u2)) for u1, u2 in rows}


def build_pairs(
    users: list[User],
    blocked: set[frozenset[int]],
    rng: random.Random,
) -> tuple[list[tuple[User, User]], list[User]]:
    """Жадный подбор пар.

    Порядок кандидатов: случайный, затем стабильная сортировка по
    unmatched_streak (убыв.) — кто дольше без пары, тот выбирает первым.
    На этапе 2 сюда добавится сортировка по рейтингу (спека п. 8).
    """
    queue = users[:]
    rng.shuffle(queue)
    queue.sort(key=lambda u: u.unmatched_streak, reverse=True)

    pairs: list[tuple[User, User]] = []
    unmatched: list[User] = []
    while queue:
        candidate = queue.pop(0)
        partner = next(
            (u for u in queue if frozenset((candidate.id, u.id)) not in blocked),
            None,
        )
        if partner is None:
            unmatched.append(candidate)
        else:
            queue.remove(partner)
            pairs.append((candidate, partner))
    return pairs, unmatched


def run_weekly_matching(
    session: Session,
    week_start: date,
    rng: random.Random | None = None,
) -> MatchResult | None:
    """Собрать пары на неделю. Идемпотентно: если встречи недели уже есть — None.

    Коммитит транзакцию. Уведомления отправляются отдельно (см. notified_at).
    """
    already = session.scalar(
        select(func.count()).select_from(Meeting).where(Meeting.week_start == week_start)
    )
    if already:
        log.info("Матчинг на %s уже выполнен (%d встреч), пропускаем", week_start, already)
        return None

    users = list(
        session.scalars(select(User).where(User.state == UserState.ACTIVE)).all()
    )
    blocked = recent_pairs(session, week_start - timedelta(days=PAIR_COOLDOWN_DAYS))
    pairs, unmatched = build_pairs(users, blocked, rng or random.Random())

    result = MatchResult(week_start=week_start, unmatched=unmatched)
    for u1, u2 in pairs:
        meeting = Meeting(week_start=week_start, user1_id=u1.id, user2_id=u2.id)
        session.add(meeting)
        result.meetings.append(meeting)
        u1.unmatched_streak = 0
        u2.unmatched_streak = 0
    for user in unmatched:
        user.unmatched_streak += 1

    session.commit()
    log.info(
        "Матчинг на %s: %d пар, %d без пары", week_start, len(pairs), len(unmatched)
    )
    return result


def pending_notifications(session: Session, week_start: date) -> list[Meeting]:
    """Встречи текущей недели, паре которых ещё не отправлено уведомление."""
    return list(
        session.scalars(
            select(Meeting).where(
                Meeting.week_start == week_start,
                Meeting.status == MeetingStatus.SCHEDULED,
                Meeting.notified_at.is_(None),
            )
        ).all()
    )
