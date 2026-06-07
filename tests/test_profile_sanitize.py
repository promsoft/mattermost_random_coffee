"""Санитизация пользовательского контента в профилях (spec/security.md)."""

import pytest

from coffeebot.config import Settings
from coffeebot.db.models import User, UserState
from coffeebot.events import IncomingDM
from coffeebot.handlers import BotHandlers
from coffeebot.services.users import PROFILE_MAX_LEN, sanitize_profile

# --- чистая функция ---


def test_mass_mentions_neutralized():
    assert sanitize_profile("привет @all и @channel и @here") == (
        "привет `@all` и `@channel` и `@here`"
    )
    assert sanitize_profile("@ALL") == "`@ALL`"


def test_personal_mentions_kept():
    # @username — легитимная часть контактов
    assert sanitize_profile("мой ник @ivan_petrov") == "мой ник @ivan_petrov"
    # @allium — не масс-пинг (граница слова)
    assert sanitize_profile("люблю @allium") == "люблю @allium"


def test_image_embed_becomes_link():
    assert sanitize_profile("![аватар](https://evil.example/track.png)") == (
        "[аватар](https://evil.example/track.png)"
    )


def test_plain_links_and_code_untouched():
    text = "tg: https://t.me/ivan, `print('hi')`"
    assert sanitize_profile(text) == text


# --- через обработчики ---


@pytest.fixture
def handlers(session_factory, gateway):
    settings = Settings(_env_file=None, actions_secret="s3cret")
    return BotHandlers(session_factory, gateway, settings)


def dm(text, user_id="mm1"):
    return IncomingDM(user_id=user_id, username="ivan", channel_id="ch", text=text)


def test_profile_too_long_rejected(handlers, gateway, session_factory):
    handlers.on_dm(dm("регистрация"))
    handlers.on_dm(dm("x" * (PROFILE_MAX_LEN + 1)))
    assert "слишком длинный" in gateway.dms[-1][1]
    # профиль не сохранился, бот всё ещё ждёт его
    handlers.on_dm(dm("нормальный профиль"))
    assert "сохранён" in gateway.dms[-1][1].lower()


def test_pair_card_sanitizes_old_profiles(handlers, gateway, session_factory):
    """Профили, записанные в БД до санитизации, чистятся при отправке карточки."""
    with session_factory() as s:
        s.add_all(
            [
                User(
                    mm_user_id="mm1",
                    username="u1",
                    state=UserState.ACTIVE,
                    profile="пингую @all ![x](https://evil.example/a.png)",
                ),
                User(mm_user_id="mm2", username="u2", state=UserState.ACTIVE),
            ]
        )
        s.commit()
    handlers.run_matching_job()
    card = [m for c, m in gateway.posts if c.startswith("group-")][0]
    assert "`@all`" in card and "![x]" not in card
