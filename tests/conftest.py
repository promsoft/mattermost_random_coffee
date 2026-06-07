import pytest

from coffeebot.db.models import Base
from coffeebot.db.session import make_engine, make_session_factory


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


@pytest.fixture
def session(session_factory):
    with session_factory() as s:
        yield s


class FakeGateway:
    """Шлюз-заглушка: копит отправленные сообщения вместо сетевых вызовов."""

    bot_user_id = "bot-id"
    bot_username = "random_coffee"

    def __init__(self):
        self.dms: list[tuple[str, str, list | None]] = []  # (mm_user_id, message, attachments)
        self.posts: list[tuple[str, str]] = []  # (channel_id, message)
        self.group_channels: list[list[str]] = []

    def dm(self, mm_user_id, message, attachments=None):
        self.dms.append((mm_user_id, message, attachments))

    def post(self, channel_id, message, attachments=None):
        self.posts.append((channel_id, message))

    def group_channel(self, mm_user_ids):
        self.group_channels.append(mm_user_ids)
        return f"group-{'-'.join(sorted(mm_user_ids))}"

    def username(self, mm_user_id):
        return f"user_{mm_user_id}"


@pytest.fixture
def gateway():
    return FakeGateway()
