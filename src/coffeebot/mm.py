"""Шлюз к Mattermost: вся сетевая отправка сообщений в одном месте."""

import logging

from mattermostdriver import Driver

log = logging.getLogger(__name__)


class MattermostGateway:
    def __init__(self, driver: Driver):
        self.driver = driver
        self.bot_user_id: str = driver.client.userid
        me = driver.users.get_user("me")
        self.bot_username: str = me["username"]
        self._dm_channels: dict[str, str] = {}  # mm_user_id -> channel_id

    def post(self, channel_id: str, message: str, attachments: list[dict] | None = None) -> None:
        post: dict = {"channel_id": channel_id, "message": message}
        if attachments:
            post["props"] = {"attachments": attachments}
        self.driver.posts.create_post(post)

    def dm_channel(self, mm_user_id: str) -> str:
        """ID личного канала бот↔пользователь (с кэшем)."""
        channel_id = self._dm_channels.get(mm_user_id)
        if channel_id is None:
            channel = self.driver.channels.create_direct_message_channel(
                [self.bot_user_id, mm_user_id]
            )
            channel_id = channel["id"]
            self._dm_channels[mm_user_id] = channel_id
        return channel_id

    def dm(self, mm_user_id: str, message: str, attachments: list[dict] | None = None) -> None:
        self.post(self.dm_channel(mm_user_id), message, attachments)

    def group_channel(self, mm_user_ids: list[str]) -> str:
        """Групповой канал бота с несколькими пользователями (для знакомства пары)."""
        channel = self.driver.channels.create_group_message_channel(
            [self.bot_user_id, *mm_user_ids]
        )
        return channel["id"]

    def username(self, mm_user_id: str) -> str:
        return self.driver.users.get_user(mm_user_id)["username"]
