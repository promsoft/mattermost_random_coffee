from datetime import datetime
from zoneinfo import ZoneInfo

from coffeebot.config import Settings
from coffeebot.main import job_overdue, matching_overdue

MSK = ZoneInfo("Europe/Moscow")


def settings():
    return Settings(_env_file=None, match_weekday=0, match_hour=7, match_minute=0)


def test_matching_overdue_within_grace():
    # вторник 12:00 — матчинг понедельника догоняем (внутри 72ч)
    assert matching_overdue(settings(), datetime(2026, 6, 9, 12, 0, tzinfo=MSK))


def test_matching_not_overdue_monday_early():
    assert not matching_overdue(settings(), datetime(2026, 6, 8, 6, 30, tzinfo=MSK))


def test_matching_overdue_exactly_at_fire_time():
    assert matching_overdue(settings(), datetime(2026, 6, 8, 7, 0, tzinfo=MSK))


def test_matching_catchup_expires_after_grace():
    # воскресенье — поздно пары собирать, ждём следующего понедельника
    assert not matching_overdue(settings(), datetime(2026, 6, 14, 12, 0, tzinfo=MSK))


def test_job_overdue_without_grace_lasts_all_week():
    # опрос среды (ср 14:00) догоняем даже в субботу
    assert job_overdue(datetime(2026, 6, 13, 9, 0, tzinfo=MSK), 2, 14, 0)
    # но не раньше времени
    assert not job_overdue(datetime(2026, 6, 10, 13, 59, tzinfo=MSK), 2, 14, 0)
