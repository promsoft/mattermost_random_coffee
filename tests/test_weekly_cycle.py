"""Интеграционный тест цикла недели через обработчики (с FakeGateway)."""

import pytest

from coffeebot.config import Settings
from coffeebot.db.models import MeetingStatus, User, UserState
from coffeebot.handlers import BotHandlers
from coffeebot.services import matching


@pytest.fixture
def handlers(session_factory, gateway):
    settings = Settings(_env_file=None, actions_secret="s3cret")
    return BotHandlers(session_factory, gateway, settings)


@pytest.fixture
def two_users(session_factory):
    with session_factory() as s:
        users = [
            User(mm_user_id=f"mm{i}", username=f"u{i}", state=UserState.ACTIVE)
            for i in (1, 2)
        ]
        s.add_all(users)
        s.commit()
    return users


def meeting_of_week(session_factory):
    with session_factory() as s:
        from sqlalchemy import select

        from coffeebot.db.models import Meeting

        return s.scalar(select(Meeting))


def test_full_week_cycle(handlers, gateway, session_factory, two_users):
    # Понедельник: матчинг
    handlers.run_matching_job()
    meeting = meeting_of_week(session_factory)
    assert meeting is not None and meeting.status == MeetingStatus.SCHEDULED

    # Среда: опрос статуса обоим
    handlers.run_midweek_job()
    midweek_dms = [d for d in gateway.dms if "Как дела" in d[1]]
    assert len(midweek_dms) == 2
    assert midweek_dms[0][2][0]["actions"][0]["integration"]["context"]["meeting_id"] == meeting.id
    # повторный запуск — без дублей
    handlers.run_midweek_job()
    assert len([d for d in gateway.dms if "Как дела" in d[1]]) == 2

    # Участник отвечает «договорились» (слот u1/u2 зависит от перемешивания)
    handlers.on_action(
        "mm1", "u1", {"action": "midweek", "meeting_id": meeting.id, "value": "agreed"}
    )
    meeting = meeting_of_week(session_factory)
    assert "agreed" in (meeting.midweek_status_u1, meeting.midweek_status_u2)

    # Воскресенье: итоговый опрос обоим, тоже идемпотентно
    handlers.run_survey_job()
    handlers.run_survey_job()
    survey_dms = [d for d in gateway.dms if "состоялась" in d[1]]
    assert len(survey_dms) == 2

    # «Да» → статус completed и кнопки оценки
    handlers.on_action("mm1", "u1", {"action": "survey", "meeting_id": meeting.id, "value": "yes"})
    meeting = meeting_of_week(session_factory)
    assert meeting.status == MeetingStatus.COMPLETED
    rating_dm = gateway.dms[-1]
    assert len(rating_dm[2][0]["actions"]) == 6  # кнопки 0–5

    # Оценка 4 от mm1 → рейтинг получает партнёр
    handlers.on_action("mm1", "u1", {"action": "rate", "meeting_id": meeting.id, "value": 4})
    meeting = meeting_of_week(session_factory)
    assert 4 in (meeting.rating_u1, meeting.rating_u2)
    assert "Спасибо за оценку" in gateway.dms[-1][1]


def test_cancelled_meeting_not_surveyed(handlers, gateway, session_factory, two_users):
    handlers.run_matching_job()
    meeting = meeting_of_week(session_factory)
    handlers.on_action(
        "mm2", "u2", {"action": "midweek", "meeting_id": meeting.id, "value": "cancelled"}
    )
    meeting = meeting_of_week(session_factory)
    assert meeting.status == MeetingStatus.CANCELLED
    handlers.run_survey_job()
    assert [d for d in gateway.dms if "состоялась" in d[1]] == []


def test_foreign_user_cannot_answer(handlers, gateway, session_factory, two_users):
    handlers.run_matching_job()
    meeting = meeting_of_week(session_factory)
    with session_factory() as s:
        s.add(User(mm_user_id="mm9", username="intruder", state=UserState.ACTIVE))
        s.commit()
    handlers.on_action("mm9", "intruder", {"action": "rate", "meeting_id": meeting.id, "value": 0})
    meeting = meeting_of_week(session_factory)
    assert meeting.rating_u1 is None and meeting.rating_u2 is None
    assert "не к вашей встрече" in gateway.dms[-1][1]


def test_rating_affects_next_matching(handlers, gateway, session_factory):
    """Высокорейтинговые попадают в пары друг к другу (спека п. 8)."""
    import random

    from coffeebot.services import meetings as svc

    with session_factory() as s:
        users = [
            User(mm_user_id=f"mm{i}", username=f"u{i}", state=UserState.ACTIVE)
            for i in range(4)
        ]
        s.add_all(users)
        s.commit()
        ids = [u.id for u in users]
        ratings = {ids[0]: 10, ids[1]: 8, ids[2]: 2, ids[3]: 0}
        pairs, unmatched = matching.build_pairs(users, set(), random.Random(7), ratings)
        assert unmatched == []
        pair_sets = [{a.id, b.id} for a, b in pairs]
        assert {ids[0], ids[1]} in pair_sets  # топ-двое вместе
        assert {ids[2], ids[3]} in pair_sets
        assert svc.ratings(s) == {}  # реальных оценок ещё нет
