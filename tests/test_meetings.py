from datetime import date, timedelta

import pytest

from coffeebot.db.models import Meeting, MeetingStatus, User
from coffeebot.services import meetings as svc

WEEK = date(2026, 6, 8)


@pytest.fixture
def pair(session):
    u1 = User(mm_user_id="mm1", username="u1")
    u2 = User(mm_user_id="mm2", username="u2")
    session.add_all([u1, u2])
    session.commit()
    meeting = Meeting(week_start=WEEK, user1_id=u1.id, user2_id=u2.id)
    session.add(meeting)
    session.commit()
    return meeting, u1, u2


def test_user_slot_and_partner(session, pair):
    meeting, u1, u2 = pair
    assert svc.user_slot(meeting, u1) == 1
    assert svc.user_slot(meeting, u2) == 2
    assert svc.partner_of(meeting, u1).id == u2.id
    stranger = User(mm_user_id="mm3", username="u3")
    session.add(stranger)
    session.commit()
    assert svc.user_slot(meeting, stranger) is None


def test_midweek_status_recorded(session, pair):
    meeting, u1, u2 = pair
    assert svc.set_midweek_status(session, meeting, u1, "agreed")
    assert meeting.midweek_status_u1 == "agreed"
    assert meeting.status == MeetingStatus.SCHEDULED


def test_midweek_cancel_cancels_meeting(session, pair):
    meeting, u1, _ = pair
    svc.set_midweek_status(session, meeting, u1, "cancelled")
    assert meeting.status == MeetingStatus.CANCELLED
    assert meeting.cancelled_by == "user"


def test_midweek_invalid_value_rejected(session, pair):
    meeting, u1, _ = pair
    assert not svc.set_midweek_status(session, meeting, u1, "hacked")


def test_survey_yes_completes(session, pair):
    meeting, u1, _ = pair
    svc.set_survey_answer(session, meeting, u1, happened=True)
    assert meeting.status == MeetingStatus.COMPLETED


def test_survey_no_cancels_but_yes_wins(session, pair):
    meeting, u1, u2 = pair
    svc.set_survey_answer(session, meeting, u1, happened=False)
    assert meeting.status == MeetingStatus.CANCELLED
    # второй подтверждает — доверяем подтверждению
    svc.set_survey_answer(session, meeting, u2, happened=True)
    assert meeting.status == MeetingStatus.COMPLETED


def test_rating_only_for_completed(session, pair):
    meeting, u1, _ = pair
    assert not svc.set_rating(session, meeting, u1, 5)  # ещё scheduled
    svc.set_survey_answer(session, meeting, u1, happened=True)
    assert svc.set_rating(session, meeting, u1, 5)
    assert meeting.rating_u1 == 5
    assert not svc.set_rating(session, meeting, u1, 7)  # вне диапазона


def test_ratings_sum_received(session, pair):
    meeting, u1, u2 = pair
    svc.set_survey_answer(session, meeting, u1, happened=True)
    svc.set_rating(session, meeting, u1, 5)  # u1 поставил → получил u2
    svc.set_rating(session, meeting, u2, 3)  # u2 поставил → получил u1
    r = svc.ratings(session)
    assert r[u1.id] == 3
    assert r[u2.id] == 5


def test_close_stale(session, pair):
    meeting, _, _ = pair
    next_week = WEEK + timedelta(days=7)
    assert svc.close_stale(session, next_week) == 1
    assert meeting.status == MeetingStatus.NO_RESPONSE
    # completed не трогаем
    assert svc.close_stale(session, next_week) == 0
