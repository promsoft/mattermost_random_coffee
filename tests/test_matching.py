import random
from datetime import date, timedelta

from coffeebot.db.models import Meeting, User, UserState
from coffeebot.services import matching

WEEK = date(2026, 6, 8)  # понедельник


def add_users(session, n, state=UserState.ACTIVE, streak=0):
    users = [
        User(mm_user_id=f"mm{i}", username=f"u{i}", state=state, unmatched_streak=streak)
        for i in range(n)
    ]
    session.add_all(users)
    session.commit()
    return users


def test_current_week_start():
    assert matching.current_week_start(date(2026, 6, 8)) == date(2026, 6, 8)  # пн
    assert matching.current_week_start(date(2026, 6, 11)) == date(2026, 6, 8)  # чт
    assert matching.current_week_start(date(2026, 6, 14)) == date(2026, 6, 8)  # вс


def test_even_number_all_paired(session):
    add_users(session, 6)
    result = matching.run_weekly_matching(session, WEEK, random.Random(1))
    assert len(result.meetings) == 3
    assert result.unmatched == []


def test_odd_number_one_unmatched_with_streak(session):
    users = add_users(session, 5)
    result = matching.run_weekly_matching(session, WEEK, random.Random(1))
    assert len(result.meetings) == 2
    assert len(result.unmatched) == 1
    session.expire_all()
    streaks = sorted(u.unmatched_streak for u in users)
    assert streaks == [0, 0, 0, 0, 1]


def test_unmatched_user_has_priority_next_week(session):
    users = add_users(session, 3)
    users[2].unmatched_streak = 5  # давно без пары — должен получить пару первым
    session.commit()
    result = matching.run_weekly_matching(session, WEEK, random.Random(1))
    paired_ids = {u.id for m in result.meetings for u in (m.user1, m.user2)}
    assert users[2].id in paired_ids


def test_paused_users_not_matched(session):
    add_users(session, 2, state=UserState.PAUSED)
    result = matching.run_weekly_matching(session, WEEK, random.Random(1))
    assert result.meetings == []


def test_cooldown_excludes_recent_pair(session):
    u1, u2, u3 = add_users(session, 3)
    # u1+u2 встречались месяц назад → их нельзя парить, кто-то остаётся без пары
    session.add(
        Meeting(week_start=WEEK - timedelta(days=30), user1_id=u1.id, user2_id=u2.id)
    )
    session.commit()
    result = matching.run_weekly_matching(session, WEEK, random.Random(1))
    assert len(result.meetings) == 1
    pair = {result.meetings[0].user1_id, result.meetings[0].user2_id}
    assert pair != {u1.id, u2.id}
    assert u3.id in pair


def test_cooldown_expired_allows_pair(session):
    u1, u2 = add_users(session, 2)
    session.add(
        Meeting(week_start=WEEK - timedelta(days=400), user1_id=u1.id, user2_id=u2.id)
    )
    session.commit()
    result = matching.run_weekly_matching(session, WEEK, random.Random(1))
    assert len(result.meetings) == 1


def test_idempotent_per_week(session):
    add_users(session, 4)
    first = matching.run_weekly_matching(session, WEEK, random.Random(1))
    assert first is not None
    second = matching.run_weekly_matching(session, WEEK, random.Random(1))
    assert second is None  # повторный запуск той же недели — ничего не делает


def test_pending_notifications_flow(session):
    add_users(session, 4)
    result = matching.run_weekly_matching(session, WEEK, random.Random(1))
    pending = matching.pending_notifications(session, WEEK)
    assert {m.id for m in pending} == {m.id for m in result.meetings}
