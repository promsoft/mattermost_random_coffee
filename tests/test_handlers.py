import pytest

from coffeebot.config import Settings
from coffeebot.db.models import User, UserState
from coffeebot.events import IncomingDM
from coffeebot.handlers import BotHandlers
from coffeebot.services import users as users_svc


@pytest.fixture
def handlers(session_factory, gateway):
    settings = Settings(
        _env_file=None,
        actions_secret="s3cret",
        announce_channel_id="announce-chan",
    )
    return BotHandlers(session_factory, gateway, settings)


def dm(text, user_id="mm1", username="ivan"):
    return IncomingDM(user_id=user_id, username=username, channel_id="dm-chan", text=text)


def get_user(session_factory, mm_user_id="mm1"):
    with session_factory() as s:
        return users_svc.get_by_mm_id(s, mm_user_id)


def test_help_unregistered_shows_register_button(handlers, gateway):
    handlers.on_dm(dm("помощь"))
    [(uid, message, attachments)] = gateway.dms
    assert uid == "mm1"
    assert "Random Coffee" in message
    actions = attachments[0]["actions"]
    assert [a["integration"]["context"]["action"] for a in actions] == ["register"]
    assert "s3cret" in actions[0]["integration"]["url"]


def test_register_flow(handlers, gateway, session_factory):
    handlers.on_dm(dm("регистрация"))
    user = get_user(session_factory)
    assert user is not None
    assert user.state == UserState.ACTIVE
    assert user.awaiting_profile  # ждём профиль
    assert "профиль" in gateway.dms[-1][1].lower()

    handlers.on_dm(dm("telegram: @ivan, люблю кофе"))
    user = get_user(session_factory)
    assert user.profile == "telegram: @ivan, люблю кофе"
    assert not user.awaiting_profile
    assert "сохранён" in gateway.dms[-1][1].lower()


def test_pause_and_resume(handlers, gateway, session_factory):
    handlers.on_dm(dm("регистрация"))
    handlers.on_dm(dm("пауза"))
    assert get_user(session_factory).state == UserState.PAUSED
    handlers.on_dm(dm("возобновить"))
    assert get_user(session_factory).state == UserState.ACTIVE


def test_admin_pause_cannot_be_lifted_by_user(handlers, gateway, session_factory):
    handlers.on_dm(dm("регистрация"))
    with session_factory() as s:
        user = users_svc.get_by_mm_id(s, "mm1")
        user.state = UserState.PAUSED_BY_COMPLAINT
        s.commit()
    handlers.on_dm(dm("возобновить"))
    assert get_user(session_factory).state == UserState.PAUSED_BY_COMPLAINT
    assert "администратор" in gateway.dms[-1][1].lower()


def test_registration_does_not_lift_admin_or_complaint_pause(handlers, gateway, session_factory):
    """Обход блокировки: пауза по жалобе/админом не снимается командой `регистрация`."""
    handlers.on_dm(dm("регистрация"))
    for paused in (UserState.PAUSED_BY_COMPLAINT, UserState.PAUSED_BY_ADMIN):
        with session_factory() as s:
            user = users_svc.get_by_mm_id(s, "mm1")
            user.state = paused
            s.commit()
        handlers.on_dm(dm("регистрация"))
        assert get_user(session_factory).state == paused  # остался на паузе
        assert "администратор" in gateway.dms[-1][1].lower()


def test_profile_inline_set(handlers, gateway, session_factory):
    handlers.on_dm(dm("регистрация"))
    handlers.on_dm(dm("профиль tg: @ivan"))
    assert get_user(session_factory).profile == "tg: @ivan"


def test_button_actions(handlers, gateway, session_factory):
    handlers.on_action("mm1", "ivan", {"action": "register"})
    assert get_user(session_factory).state == UserState.ACTIVE
    handlers.on_action("mm1", "ivan", {"action": "pause"})
    assert get_user(session_factory).state == UserState.PAUSED
    handlers.on_action("mm1", "ivan", {"action": "resume"})
    assert get_user(session_factory).state == UserState.ACTIVE


def test_unknown_message_shows_help(handlers, gateway):
    handlers.on_dm(dm("что ты умеешь?"))
    assert "Не понял" in gateway.dms[-1][1]


def test_matching_job_notifies_pairs_and_announces(handlers, gateway, session_factory):
    with session_factory() as s:
        s.add_all(
            User(mm_user_id=f"mm{i}", username=f"u{i}", state=UserState.ACTIVE)
            for i in range(4)
        )
        s.commit()

    handlers.run_matching_job()

    # две пары — два групповых канала с карточками
    assert len(gateway.group_channels) == 2
    pair_posts = [m for c, m in gateway.posts if c.startswith("group-")]
    assert all("вы — пара" in m for m in pair_posts)
    # анонс в канал
    announce = [m for c, m in gateway.posts if c == "announce-chan"]
    assert len(announce) == 1
    assert "Собрано пар: **2**" in announce[0]

    # повторный запуск недели: ни новых пар, ни повторных рассылок
    gateway.posts.clear()
    gateway.group_channels.clear()
    handlers.run_matching_job()
    assert gateway.posts == []
    assert gateway.group_channels == []


def test_version_dev_without_build_file(handlers, gateway):
    handlers.on_dm(dm("версия"))
    [(uid, message, _)] = gateway.dms
    assert uid == "mm1"
    assert "локальный запуск" in message


def test_version_shows_build_time_in_bot_tz(handlers, gateway, tmp_path, monkeypatch):
    from coffeebot import version

    f = tmp_path / "build_time"
    f.write_text("2026-06-10T09:23:00Z\n")
    monkeypatch.setattr(version, "_BUILD_TIME_FILE", f)
    handlers.on_dm(dm("version"))
    [(_, message, _)] = gateway.dms
    assert message == "сборка 2026-06-10 12:23"  # 09:23 UTC = 12:23 МСК
