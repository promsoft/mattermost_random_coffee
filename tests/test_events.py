import json

from coffeebot.events import handle_event

BOT_ID = "bot-user-id"


def posted_event(message="привет", user_id="someone", channel_type="D", channel_id="chan1"):
    return json.dumps(
        {
            "event": "posted",
            "data": {
                "channel_type": channel_type,
                "post": json.dumps(
                    {"user_id": user_id, "channel_id": channel_id, "message": message}
                ),
            },
        }
    )


def test_echo_on_direct_message():
    reply = handle_event(posted_event("привет"), BOT_ID)
    assert reply is not None
    assert reply.channel_id == "chan1"
    assert "привет" in reply.message


def test_ignores_own_posts():
    assert handle_event(posted_event(user_id=BOT_ID), BOT_ID) is None


def test_ignores_public_channels():
    assert handle_event(posted_event(channel_type="O"), BOT_ID) is None


def test_ignores_non_posted_events():
    assert handle_event(json.dumps({"event": "typing", "data": {}}), BOT_ID) is None


def test_ignores_empty_message():
    assert handle_event(posted_event("   "), BOT_ID) is None


def test_survives_garbage():
    assert handle_event("not a json {", BOT_ID) is None
    no_post = json.dumps({"event": "posted", "data": {"channel_type": "D"}})
    assert handle_event(no_post, BOT_ID) is None
