import json

from coffeebot.events import parse_dm

BOT_ID = "bot-user-id"


def posted_event(message="привет", user_id="someone", channel_type="D", channel_id="chan1"):
    return json.dumps(
        {
            "event": "posted",
            "data": {
                "channel_type": channel_type,
                "sender_name": "@ivan",
                "post": json.dumps(
                    {"user_id": user_id, "channel_id": channel_id, "message": message}
                ),
            },
        }
    )


def test_parses_direct_message():
    dm = parse_dm(posted_event("привет"), BOT_ID)
    assert dm is not None
    assert dm.user_id == "someone"
    assert dm.username == "ivan"
    assert dm.channel_id == "chan1"
    assert dm.text == "привет"


def test_ignores_own_posts():
    assert parse_dm(posted_event(user_id=BOT_ID), BOT_ID) is None


def test_ignores_public_and_group_channels():
    assert parse_dm(posted_event(channel_type="O"), BOT_ID) is None
    assert parse_dm(posted_event(channel_type="G"), BOT_ID) is None


def test_ignores_non_posted_events():
    assert parse_dm(json.dumps({"event": "typing", "data": {}}), BOT_ID) is None


def test_ignores_empty_message():
    assert parse_dm(posted_event("   "), BOT_ID) is None


def test_survives_garbage():
    assert parse_dm("not a json {", BOT_ID) is None
    no_post = json.dumps({"event": "posted", "data": {"channel_type": "D"}})
    assert parse_dm(no_post, BOT_ID) is None
