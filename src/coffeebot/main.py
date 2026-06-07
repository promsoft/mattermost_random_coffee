"""Точка входа: WebSocket + HTTP-эндпоинт кнопок + планировщик в одном asyncio-loop."""

import asyncio
import logging
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from mattermostdriver import Driver

from coffeebot.config import Settings
from coffeebot.db.session import make_engine, make_session_factory
from coffeebot.events import parse_dm
from coffeebot.handlers import BotHandlers
from coffeebot.http_app import create_app
from coffeebot.mm import MattermostGateway
from coffeebot.mm_websocket import ClientTLSWebsocket

log = logging.getLogger(__name__)


def job_overdue(
    now: datetime, weekday: int, hour: int, minute: int, grace_hours: int | None = None
) -> bool:
    """Прошло ли на этой неделе время задачи (для догона после простоя).

    grace_hours ограничивает окно догона: матчить пары в конце недели хуже,
    чем пропустить неделю (опрос-опоздание, наоборот, безвредно).
    """
    monday = (now - timedelta(days=now.weekday())).date()
    fire_at = datetime(
        monday.year, monday.month, monday.day, hour, minute, tzinfo=now.tzinfo
    ) + timedelta(days=weekday)
    if now < fire_at:
        return False
    return grace_hours is None or now < fire_at + timedelta(hours=grace_hours)


MATCH_CATCHUP_GRACE_HOURS = 72  # пн 07:00 + 72ч = до чт утра; позже ждём след. недели


def matching_overdue(settings: Settings, now: datetime) -> bool:
    return job_overdue(
        now,
        settings.match_weekday,
        settings.match_hour,
        settings.match_minute,
        MATCH_CATCHUP_GRACE_HOURS,
    )


async def run() -> None:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not settings.actions_secret:
        log.error(
            "ACTIONS_SECRET не задан — кнопки без аутентификации запрещены. Сгенерируйте: "
            'python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
        sys.exit(1)

    driver = Driver(settings.driver_options)
    driver.login()
    gateway = MattermostGateway(driver)
    log.info("Вошли как @%s (%s) на %s", gateway.bot_username, gateway.bot_user_id, settings.mm_url)

    engine = make_engine(settings.db_url)
    session_factory = make_session_factory(engine)
    handlers = BotHandlers(session_factory, gateway, settings)

    # Планировщик: пн — матчинг, ср — опрос статуса, вс — итоги и оценка
    tz = ZoneInfo(settings.tz)
    scheduler = AsyncIOScheduler(timezone=tz)
    jobs = [
        ("weekly_matching", handlers.run_matching_job, settings.match_weekday,
         settings.match_hour, settings.match_minute, MATCH_CATCHUP_GRACE_HOURS),
        ("midweek_poll", handlers.run_midweek_job, settings.midweek_weekday,
         settings.midweek_hour, settings.midweek_minute, None),
        ("weekly_survey", handlers.run_survey_job, settings.survey_weekday,
         settings.survey_hour, settings.survey_minute, None),
    ]
    for job_id, func, weekday, hour, minute, _grace in jobs:
        scheduler.add_job(
            func,
            CronTrigger(day_of_week=weekday, hour=hour, minute=minute, timezone=tz),
            id=job_id,
        )
    scheduler.start()

    # Догон после простоя: каждая задача идемпотентна (week_start / *_sent_at),
    # поэтому просто выполняем все, чьё время на этой неделе уже прошло
    now = datetime.now(tz)
    for _job_id, func, weekday, hour, minute, grace in jobs:
        if job_overdue(now, weekday, hour, minute, grace):
            func()
    handlers.notify_pending()  # дослать карточки пар, не ушедшие из-за рестарта

    # HTTP-эндпоинт кнопок
    app = create_app(handlers, settings.actions_secret)
    server = uvicorn.Server(
        uvicorn.Config(app, host=settings.http_host, port=settings.http_port, log_level="warning")
    )

    # WebSocket: входящие личные сообщения
    async def on_event(raw: str) -> None:
        try:
            dm = parse_dm(raw, gateway.bot_user_id)
            if dm is not None:
                handlers.on_dm(dm)
        except Exception:
            log.exception("Ошибка обработки события")

    websocket = ClientTLSWebsocket(driver.options, driver.client.token)
    log.info("Слушаем WebSocket и HTTP %s:%d", settings.http_host, settings.http_port)
    await asyncio.gather(websocket.connect(on_event), server.serve())


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
