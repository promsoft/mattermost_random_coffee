"""Еженедельный матчинг пар. Алгоритм описан в spec/architecture.md."""

import logging
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coffeebot.db.models import Meeting, MeetingStatus, User, UserState
from coffeebot.services import meetings as meetings_svc

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
    ratings: dict[int, int] | None = None,
) -> tuple[list[tuple[User, User]], list[User]]:
    """Жадный подбор пар.

    Порядок кандидатов: случайный, затем стабильная сортировка по
    (unmatched_streak, рейтинг) убыв. — кто дольше без пары, тот выбирает
    первым; при равенстве высокорейтинговые встают рядом и попадают
    в пары друг с другом (спека п. 8).
    """
    ratings = ratings or {}
    queue = users[:]
    rng.shuffle(queue)
    queue.sort(key=lambda u: (u.unmatched_streak, ratings.get(u.id, 0)), reverse=True)

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


def matching_done(session: Session, week_start: date) -> bool:
    """Был ли уже регулярный матчинг на неделю (встречи, не созданные переносом)."""
    return bool(
        session.scalar(
            select(func.count())
            .select_from(Meeting)
            .where(
                Meeting.week_start == week_start,
                Meeting.postponed_from_id.is_(None),
            )
        )
    )


def committed_user_ids(session: Session, week_start: date) -> set[int]:
    """ID участников, у которых уже есть живая встреча на эту неделю.

    Это в т.ч. встречи, перенесённые с прошлой недели (postponed_from_id задан):
    таких в новый матчинг не берём.
    """
    rows = session.execute(
        select(Meeting.user1_id, Meeting.user2_id).where(
            Meeting.week_start == week_start,
            Meeting.status.in_(
                (MeetingStatus.SCHEDULED, MeetingStatus.POSTPONE_PENDING)
            ),
        )
    ).all()
    return {uid for pair in rows for uid in pair}


def pool_users(session: Session, week_start: date) -> list[User]:
    """Свободные на этой неделе активные участники (этап 3: домэтч).

    Занятыми считаем тех, у кого есть встреча со статусом scheduled/postpone_pending
    на эту или будущую неделю (перенос вперёд), либо состоявшаяся на этой неделе.
    """
    busy: set[int] = set()
    rows = session.execute(
        select(
            Meeting.user1_id, Meeting.user2_id, Meeting.week_start, Meeting.status
        ).where(Meeting.week_start >= week_start)
    ).all()
    for u1, u2, ws, status in rows:
        if status in (MeetingStatus.SCHEDULED, MeetingStatus.POSTPONE_PENDING) or (
            ws == week_start and status == MeetingStatus.COMPLETED
        ):
            busy.add(u1)
            busy.add(u2)
    active = session.scalars(select(User).where(User.state == UserState.ACTIVE)).all()
    return [u for u in active if u.id not in busy]


def domatch(
    session: Session, week_start: date, rng: random.Random | None = None
) -> list[Meeting]:
    """Подобрать пары из пула свободных среди недели (отказ от пары / новый участник).

    Создаёт scheduled-встречи, сбрасывает streak у получивших пару, коммитит.
    Возвращает новые встречи (рассылку карточек делает вызывающий по notified_at).
    """
    pool = pool_users(session, week_start)
    if len(pool) < 2:
        return []
    blocked = recent_pairs(session, week_start - timedelta(days=PAIR_COOLDOWN_DAYS))
    user_ratings = meetings_svc.ratings(session)
    pairs, _ = build_pairs(pool, blocked, rng or random.Random(), user_ratings)
    new_meetings: list[Meeting] = []
    for u1, u2 in pairs:
        meeting = Meeting(week_start=week_start, user1_id=u1.id, user2_id=u2.id)
        session.add(meeting)
        new_meetings.append(meeting)
        u1.unmatched_streak = 0
        u2.unmatched_streak = 0
    if new_meetings:
        session.commit()
        log.info("Домэтч на %s: %d новых пар", week_start, len(new_meetings))
    return new_meetings


def run_weekly_matching(
    session: Session,
    week_start: date,
    rng: random.Random | None = None,
) -> MatchResult | None:
    """Собрать пары на неделю. Идемпотентно: если матчинг недели уже был — None.

    Коммитит транзакцию. Уведомления отправляются отдельно (см. notified_at).
    """
    if matching_done(session, week_start):
        log.info("Матчинг на %s уже выполнен, пропускаем", week_start)
        return None

    committed = committed_user_ids(session, week_start)  # перенос с прошлой недели
    users = [
        u
        for u in session.scalars(select(User).where(User.state == UserState.ACTIVE)).all()
        if u.id not in committed
    ]
    blocked = recent_pairs(session, week_start - timedelta(days=PAIR_COOLDOWN_DAYS))
    user_ratings = meetings_svc.ratings(session)
    pairs, unmatched = build_pairs(users, blocked, rng or random.Random(), user_ratings)

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
