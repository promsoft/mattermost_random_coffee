"""Админ-команды и жалобы (этап 4)."""

import pytest
from sqlalchemy import select

from coffeebot.config import Settings
from coffeebot.db.models import Complaint, ComplaintStatus, Meeting, MeetingStatus, User, UserState
from coffeebot.events import IncomingDM
from coffeebot.handlers import BotHandlers


@pytest.fixture
def handlers(session_factory, gateway):
    settings = Settings(
        _env_file=None, actions_secret="s3cret", admin_usernames="boss, second_admin"
    )
    return BotHandlers(session_factory, gateway, settings)


@pytest.fixture
def pair(session_factory, handlers):
    with session_factory() as s:
        s.add_all(
            User(mm_user_id=f"mm{i}", username=f"u{i}", state=UserState.ACTIVE)
            for i in (1, 2)
        )
        s.commit()
    handlers.run_matching_job()
    with session_factory() as s:
        return s.scalar(select(Meeting))


def dm(text, user_id="mm-boss", username="boss"):
    return IncomingDM(user_id=user_id, username=username, channel_id="ch", text=text)


def last_dm_to(gateway, user_id):
    return [m for u, m, _ in gateway.dms if u == user_id][-1]


# --- доступ ---


def test_non_admin_rejected(handlers, gateway):
    handlers.on_dm(dm("админ участники", user_id="mm1", username="u1"))
    assert "только администраторам" in last_dm_to(gateway, "mm1")


def test_admin_help(handlers, gateway):
    handlers.on_dm(dm("админ"))
    assert "Админ-команды" in last_dm_to(gateway, "mm-boss")


# --- отчёты ---


def test_users_report(handlers, gateway, pair):
    handlers.on_dm(dm("админ участники"))
    report = last_dm_to(gateway, "mm-boss")
    assert "@u1" in report and "@u2" in report
    assert "рейтинг 0" in report


def test_meetings_report(handlers, gateway, pair):
    handlers.on_dm(dm("админ встречи"))
    report = last_dm_to(gateway, "mm-boss")
    assert f"#{pair.id}" in report
    assert "scheduled" in report


def test_meetings_report_empty(handlers, gateway):
    handlers.on_dm(dm("админ встречи"))
    assert "встреч нет" in last_dm_to(gateway, "mm-boss")


# --- отмена встречи ---


def test_admin_cancel(handlers, gateway, session_factory, pair):
    handlers.on_dm(dm(f"админ отменить {pair.id}"))
    with session_factory() as s:
        meeting = s.get(Meeting, pair.id)
        assert meeting.status == MeetingStatus.CANCELLED
        assert meeting.cancelled_by == "admin"
    # уведомлены оба участника и админ
    assert "отменена администратором" in last_dm_to(gateway, "mm1")
    assert "отменена администратором" in last_dm_to(gateway, "mm2")
    assert "отменена" in last_dm_to(gateway, "mm-boss")


def test_admin_cancel_not_found(handlers, gateway):
    handlers.on_dm(dm("админ отменить 999"))
    assert "не найдена" in last_dm_to(gateway, "mm-boss")


# --- пауза/снятие ---


def test_admin_pause_unpause(handlers, gateway, session_factory, pair):
    handlers.on_dm(dm("админ пауза u1"))
    with session_factory() as s:
        user = s.scalar(select(User).where(User.username == "u1"))
        assert user.state == UserState.PAUSED_BY_ADMIN
    assert "приостановлено администратором" in last_dm_to(gateway, "mm1")

    # участник не может снять админскую паузу сам
    handlers.on_dm(dm("возобновить", user_id="mm1", username="u1"))
    with session_factory() as s:
        user = s.scalar(select(User).where(User.username == "u1"))
        assert user.state == UserState.PAUSED_BY_ADMIN

    handlers.on_dm(dm("админ снять-паузу u1"))
    with session_factory() as s:
        user = s.scalar(select(User).where(User.username == "u1"))
        assert user.state == UserState.ACTIVE
    assert "возобновлено" in last_dm_to(gateway, "mm1")


def test_admin_pause_unknown_user(handlers, gateway):
    handlers.on_dm(dm("админ пауза nobody"))
    assert "не найден" in last_dm_to(gateway, "mm-boss")


# --- жалобы ---


def complain_flow(handlers, gateway, session_factory, pair):
    handlers.on_dm(dm("пожаловаться", user_id="mm1", username="u1"))
    confirm = last_dm_to(gateway, "mm1")
    assert "пожаловаться на @u2" in confirm
    handlers.on_action("mm1", "u1", {"action": "complain", "meeting_id": pair.id})


def test_complaint_pauses_accused_and_alerts_admins(
    handlers, gateway, session_factory, pair
):
    complain_flow(handlers, gateway, session_factory, pair)
    with session_factory() as s:
        accused = s.scalar(select(User).where(User.username == "u2"))
        assert accused.state == UserState.PAUSED_BY_COMPLAINT
        complaint = s.scalar(select(Complaint))
        assert complaint.status == ComplaintStatus.OPEN
    # оба админа уведомлены
    assert "Жалоба" in last_dm_to(gateway, "id-boss")
    assert "Жалоба" in last_dm_to(gateway, "id-second_admin")
    assert "принята" in last_dm_to(gateway, "mm1")


def test_repeat_complaint_not_duplicated(handlers, gateway, session_factory, pair):
    complain_flow(handlers, gateway, session_factory, pair)
    handlers.on_action("mm1", "u1", {"action": "complain", "meeting_id": pair.id})
    with session_factory() as s:
        assert len(list(s.scalars(select(Complaint)))) == 1
    assert "уже подана" in last_dm_to(gateway, "mm1")


def test_unpause_resolves_complaints(handlers, gateway, session_factory, pair):
    complain_flow(handlers, gateway, session_factory, pair)
    handlers.on_dm(dm("админ снять-паузу u2"))
    with session_factory() as s:
        complaint = s.scalar(select(Complaint))
        assert complaint.status == ComplaintStatus.RESOLVED
        accused = s.scalar(select(User).where(User.username == "u2"))
        assert accused.state == UserState.ACTIVE
    assert "Закрыто жалоб: 1" in last_dm_to(gateway, "mm-boss")


def test_complaint_without_meeting(handlers, gateway, session_factory):
    with session_factory() as s:
        s.add(User(mm_user_id="mm5", username="u5", state=UserState.ACTIVE))
        s.commit()
    handlers.on_dm(dm("пожаловаться", user_id="mm5", username="u5"))
    assert "нет встречи" in last_dm_to(gateway, "mm5")


def test_complaints_report(handlers, gateway, session_factory, pair):
    handlers.on_dm(dm("админ жалобы"))
    assert "жалоб нет" in last_dm_to(gateway, "mm-boss")
    complain_flow(handlers, gateway, session_factory, pair)
    handlers.on_dm(dm("админ жалобы"))
    report = last_dm_to(gateway, "mm-boss")
    assert "@u1" in report and "@u2" in report
