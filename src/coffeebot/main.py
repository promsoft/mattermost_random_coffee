"""Точка входа: подключение к Mattermost и обработка событий."""

import logging

from mattermostdriver import Driver

from coffeebot.config import Settings
from coffeebot.events import handle_event

log = logging.getLogger(__name__)


def main() -> None:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    driver = Driver(settings.driver_options)
    driver.login()
    bot_user_id = driver.client.userid
    me = driver.users.get_user("me")
    log.info("Вошли как @%s (%s) на %s", me["username"], bot_user_id, settings.mm_url)

    async def on_event(raw: str) -> None:
        try:
            reply = handle_event(raw, bot_user_id)
        except Exception:
            log.exception("Ошибка обработки события")
            return
        if reply is not None:
            driver.posts.create_post({"channel_id": reply.channel_id, "message": reply.message})

    # Блокирующий вызов: слушаем WebSocket, при обрыве соединения драйвер переподключается
    driver.init_websocket(on_event)


if __name__ == "__main__":
    main()
