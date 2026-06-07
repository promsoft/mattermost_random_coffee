from datetime import datetime
from zoneinfo import ZoneInfo

from coffeebot.config import Settings
from coffeebot.main import matching_overdue

MSK = ZoneInfo("Europe/Moscow")


def settings():
    return Settings(_env_file=None, match_weekday=0, match_hour=7, match_minute=0)


def test_overdue_after_monday_morning():
    # четверг 12:00 — матчинг понедельника прошёл
    assert matching_overdue(settings(), datetime(2026, 6, 11, 12, 0, tzinfo=MSK))


def test_not_overdue_monday_early():
    # понедельник 06:30 — ещё рано
    assert not matching_overdue(settings(), datetime(2026, 6, 8, 6, 30, tzinfo=MSK))


def test_overdue_exactly_at_fire_time():
    assert matching_overdue(settings(), datetime(2026, 6, 8, 7, 0, tzinfo=MSK))
