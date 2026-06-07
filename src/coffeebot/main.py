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


def matching_overdue(settings: Settings, now: datetime) -> bool:
    """Прошло ли на этой неделе время матчинга (для догона после простоя)."""
    monday = (now - timedelta(days=now.weekday())).date()
    fire_at = datetime(
        monday.year, monday.month, monday.day, settings.match_hour, settings.match_minute,
        tzinfo=now.tzinfo,
    ) + timedelta(days=settings.match_weekday)
    return now >= fire_at


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

    # Планировщик: понедельничный матчинг
    tz = ZoneInfo(settings.tz)
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        handlers.run_matching_job,
        CronTrigger(
            day_of_week=settings.match_weekday,
            hour=settings.match_hour,
            minute=settings.match_minute,
            timezone=tz,
        ),
        id="weekly_matching",
    )
    scheduler.start()

    # Догон после простоя: если время матчинга этой недели прошло — выполняем
    # (идемпотентно), затем досылаем неотправленные уведомления пар
    if matching_overdue(settings, datetime.now(tz)):
        handlers.run_matching_job()
    handlers.notify_pending()

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
