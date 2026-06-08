"""Этап 3: отказ от пары с домэтчем из пула и перенос встречи."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from coffeebot import cards
from coffeebot.config import Settings
from coffeebot.db.models import Meeting, MeetingStatus, User, UserState
from coffeebot.events import IncomingDM
from coffeebot.handlers import BotHandlers
from coffeebot.services import matching
from coffeebot.services import meetings as meetings_svc


@pytest.fixture
def handlers(session_factory, gateway):
    settings = Settings(_env_file=None, actions_secret="s3cret")
    return BotHandlers(session_factory, gateway, settings)


def make_users(session_factory, n):
    with session_factory() as s:
        users = [
            User(mm_user_id=f"mm{i}", username=f"u{i}", state=UserState.ACTIVE)
            for i in range(1, n + 1)
        ]
        s.add_all(users)
        s.commit()
        return {u.username: u.id for u in users}


def all_meetings(session_factory):
    with session_factory() as s:
        meetings = list(s.scalars(select(Meeting)))
        for m in meetings:  # подгрузить связи, пока сессия открыта
            _ = m.user1, m.user2
        return meetings


def get_meeting(session_factory, meeting_id):
    with session_factory() as s:
        return s.get(Meeting, meeting_id)


# --- отказ от пары -------------------------------------------------------


def test_decline_two_users_both_return_to_pool(handlers, gateway, session_factory):
    make_users(session_factory, 2)
    handlers.run_matching_job()
    meetings = all_meetings(session_factory)
    assert len(meetings) == 1
    m = meetings[0]
    decliner = m.user1  # любой из двоих
    partner = m.user2

    handlers.on_action(
        decliner.mm_user_id,
        decliner.username,
        {"action": "decline", "meeting_id": m.id},
    )

    m = get_meeting(session_factory, m.id)
    assert m.status == MeetingStatus.DECLINED
    # пары больше нет (повторно эти двое в течение года не сойдутся)
    scheduled = [x for x in all_meetings(session_factory) if x.status == MeetingStatus.SCHEDULED]
    assert scheduled == []
    # обоим сообщили, что они в пуле
    dms = {uid: msg for uid, msg, _ in gateway.dms}
    assert "свободных" in dms[decliner.mm_user_id]
    assert "свободных" in dms[partner.mm_user_id]


def test_decline_rematches_from_pool(handlers, gateway, session_factory):
    ids = make_users(session_factory, 3)
    handlers.run_matching_job()
    scheduled = [m for m in all_meetings(session_factory) if m.status == MeetingStatus.SCHEDULED]
    assert len(scheduled) == 1  # 1 пара + 1 свободный
    m = scheduled[0]
    pair_ids = {m.user1_id, m.user2_id}
    leftover_id = (set(ids.values()) - pair_ids).pop()
    decliner = m.user1

    gateway.group_channels.clear()
    handlers.on_action(
        decliner.mm_user_id, decliner.username, {"action": "decline", "meeting_id": m.id}
    )

    assert get_meeting(session_factory, m.id).status == MeetingStatus.DECLINED
    new = [
        x
        for x in all_meetings(session_factory)
        if x.status == MeetingStatus.SCHEDULED and x.id != m.id
    ]
    assert len(new) == 1  # из пула собралась новая пара
    assert leftover_id in {new[0].user1_id, new[0].user2_id}  # свободный получил пару
    assert len(gateway.group_channels) == 1  # карточка новой пары отправлена

    rematched = {new[0].user1_id, new[0].user2_id}
    decliner_msg = [msg for uid, msg, _ in gateway.dms if uid == decliner.mm_user_id][-1]
    if decliner.id in rematched:
        assert "новую" in decliner_msg
    else:
        assert "пул свободных" in decliner_msg


def test_decline_rejected_when_not_scheduled(handlers, gateway, session_factory):
    make_users(session_factory, 2)
    handlers.run_matching_job()
    m = all_meetings(session_factory)[0]
    # отменяем встречу, затем пробуем отказаться
    handlers.on_action(
        m.user1.mm_user_id,
        m.user1.username,
        {"action": "midweek", "meeting_id": m.id, "value": "cancelled"},
    )
    handlers.on_action(
        m.user1.mm_user_id, m.user1.username, {"action": "decline", "meeting_id": m.id}
    )
    assert get_meeting(session_factory, m.id).status == MeetingStatus.CANCELLED
    assert "нельзя выполнить" in gateway.dms[-1][1]


def test_decline_limited_to_one_per_week(handlers, gateway, session_factory):
    """Один отказ в неделю: вторая попытка отклоняется, встреча остаётся."""
    week = date(2026, 6, 8)  # понедельник
    with session_factory() as s:
        a = User(mm_user_id="mmA", username="a", state=UserState.ACTIVE)
        b = User(mm_user_id="mmB", username="b", state=UserState.ACTIVE)
        c = User(mm_user_id="mmC", username="c", state=UserState.ACTIVE)
        s.add_all([a, b, c])
        s.commit()
        m1 = Meeting(week_start=week, user1_id=a.id, user2_id=b.id)
        m2 = Meeting(week_start=week, user1_id=a.id, user2_id=c.id)
        s.add_all([m1, m2])
        s.commit()
        a_mm, a_un, b_id = a.mm_user_id, a.username, b.id
        m1_id, m2_id = m1.id, m2.id

    # 1-й отказ — успешен
    handlers.on_action(a_mm, a_un, {"action": "decline", "meeting_id": m1_id})
    assert get_meeting(session_factory, m1_id).status == MeetingStatus.DECLINED

    # тот, на кого отказались (b), лимит не тратит
    with session_factory() as s:
        b_user = s.get(User, b_id)
        assert meetings_svc.user_declined_this_week(s, b_user, week) is False

    # 2-й отказ той же недели — отклонён, встреча остаётся scheduled
    handlers.on_action(a_mm, a_un, {"action": "decline", "meeting_id": m2_id})
    assert get_meeting(session_factory, m2_id).status == MeetingStatus.SCHEDULED
    assert "раз в неделю" in gateway.dms[-1][1]


# --- домэтч при регистрации среди недели ---------------------------------


def test_registration_midweek_gets_matched_from_pool(handlers, gateway, session_factory):
    make_users(session_factory, 3)  # 1 пара + 1 свободный
    handlers.run_matching_job()
    before = [m for m in all_meetings(session_factory) if m.status == MeetingStatus.SCHEDULED]
    assert len(before) == 1

    gateway.group_channels.clear()
    handlers.on_dm(IncomingDM(user_id="mm4", username="u4", channel_id="d", text="регистрация"))

    scheduled = [m for m in all_meetings(session_factory) if m.status == MeetingStatus.SCHEDULED]
    assert len(scheduled) == 2  # новичок спарился со свободным
    with session_factory() as s:
        new_user = s.scalar(select(User).where(User.mm_user_id == "mm4"))
        assert new_user is not None
        in_pair = any(new_user.id in {m.user1_id, m.user2_id} for m in scheduled)
    assert in_pair
    assert len(gateway.group_channels) == 1  # карточка отправлена


def test_registration_before_matching_does_not_pair(handlers, gateway, session_factory):
    # На неделе матчинга ещё не было — регистрация не должна собирать пары
    handlers.on_dm(IncomingDM(user_id="mm1", username="u1", channel_id="d", text="регистрация"))
    handlers.on_dm(IncomingDM(user_id="mm2", username="u2", channel_id="d", text="регистрация"))
    assert all_meetings(session_factory) == []


# --- перенос -------------------------------------------------------------


def test_postpone_accept_creates_next_week_meeting(handlers, gateway, session_factory):
    make_users(session_factory, 2)
    handlers.run_matching_job()
    m = all_meetings(session_factory)[0]
    proposer, partner = m.user1, m.user2

    handlers.on_action(
        proposer.mm_user_id, proposer.username, {"action": "postpone", "meeting_id": m.id}
    )
    m = get_meeting(session_factory, m.id)
    assert m.status == MeetingStatus.POSTPONE_PENDING
    assert m.postpone_by_id == proposer.id
    # партнёру пришёл запрос с кнопками согласия/отказа
    req = [d for d in gateway.dms if d[0] == partner.mm_user_id and d[2]][-1]
    actions = [a["integration"]["context"]["action"] for a in req[2][0]["actions"]]
    assert actions == ["postpone_accept", "postpone_decline"]

    handlers.on_action(
        partner.mm_user_id,
        partner.username,
        {"action": "postpone_accept", "meeting_id": m.id},
    )
    m = get_meeting(session_factory, m.id)
    assert m.status == MeetingStatus.POSTPONED
    with session_factory() as s:
        fwd = s.scalar(select(Meeting).where(Meeting.postponed_from_id == m.id))
    assert fwd is not None
    assert fwd.week_start == m.week_start + timedelta(days=7)
    assert fwd.status == MeetingStatus.SCHEDULED
    assert {fwd.user1_id, fwd.user2_id} == {proposer.id, partner.id}


def test_postpone_proposer_cannot_self_accept(handlers, gateway, session_factory):
    make_users(session_factory, 2)
    handlers.run_matching_job()
    m = all_meetings(session_factory)[0]
    proposer = m.user1
    handlers.on_action(
        proposer.mm_user_id, proposer.username, {"action": "postpone", "meeting_id": m.id}
    )
    handlers.on_action(
        proposer.mm_user_id,
        proposer.username,
        {"action": "postpone_accept", "meeting_id": m.id},
    )
    assert get_meeting(session_factory, m.id).status == MeetingStatus.POSTPONE_PENDING
    assert "нельзя выполнить" in gateway.dms[-1][1]


def test_postpone_decline_cancels_meeting(handlers, gateway, session_factory):
    make_users(session_factory, 2)
    handlers.run_matching_job()
    m = all_meetings(session_factory)[0]
    proposer, partner = m.user1, m.user2
    handlers.on_action(
        proposer.mm_user_id, proposer.username, {"action": "postpone", "meeting_id": m.id}
    )
    handlers.on_action(
        partner.mm_user_id,
        partner.username,
        {"action": "postpone_decline", "meeting_id": m.id},
    )
    m = get_meeting(session_factory, m.id)
    assert m.status == MeetingStatus.CANCELLED
    assert m.cancelled_by == "user"
    # новой встречи на следующей неделе не появилось
    with session_factory() as s:
        assert s.scalar(select(Meeting).where(Meeting.postponed_from_id.is_not(None))) is None


def test_postponed_meeting_does_not_break_next_week_matching(handlers, session_factory):
    """След. понедельник: матчинг не дублирует уже перенесённую пару и не падает."""
    make_users(session_factory, 2)
    handlers.run_matching_job()
    m = all_meetings(session_factory)[0]
    proposer, partner = m.user1, m.user2
    handlers.on_action(
        proposer.mm_user_id, proposer.username, {"action": "postpone", "meeting_id": m.id}
    )
    handlers.on_action(
        partner.mm_user_id, partner.username, {"action": "postpone_accept", "meeting_id": m.id}
    )
    with session_factory() as s:
        fwd = s.scalar(select(Meeting).where(Meeting.postponed_from_id.is_not(None)))
        next_week = fwd.week_start

    # регулярный матчинг ещё не выполнялся для след. недели (только перенос)
    with session_factory() as s:
        assert matching.matching_done(s, next_week) is False
        result = matching.run_weekly_matching(s, next_week)
    assert result is not None
    assert result.meetings == []  # оба заняты переносом, новых пар нет
    # повторно — уже идемпотентно
    with session_factory() as s:
        assert matching.matching_done(s, next_week) is False  # перенос не считается матчингом
        scheduled = list(
            s.scalars(
                select(Meeting).where(
                    Meeting.week_start == next_week,
                    Meeting.status == MeetingStatus.SCHEDULED,
                )
            )
        )
    assert len(scheduled) == 1  # только перенесённая встреча


# --- карточки -------------------------------------------------------------


def test_pair_card_has_decline_and_postpone_buttons():
    [block] = cards.pair_card_attachments(7, "http://x/actions/s")
    actions = [a["integration"]["context"]["action"] for a in block["actions"]]
    assert actions == ["decline", "postpone"]
    assert all(a["integration"]["context"]["meeting_id"] == 7 for a in block["actions"])
