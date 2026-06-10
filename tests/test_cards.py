"""id кнопок: маршрут Mattermost /actions/{action_id:[A-Za-z0-9]+} требует
строго алфавитно-цифровые id — иначе клик даёт 404 ещё в роутере."""

import re

from coffeebot import cards
from coffeebot.db.models import User, UserState

URL = "http://x/actions/s"


def all_buttons() -> list[dict]:
    user = User(id=1, mm_user_id="m1", username="u1", state=UserState.ACTIVE)
    paused = User(id=2, mm_user_id="m2", username="u2", state=UserState.PAUSED)
    attachment_lists = [
        cards.menu_attachments(None, URL),
        cards.menu_attachments(user, URL),
        cards.menu_attachments(paused, URL),
        cards.pair_card_attachments(7, URL),
        cards.postpone_confirm_attachments(7, URL),
        cards.midweek_attachments(7, URL),
        cards.survey_attachments(7, URL),
        cards.rating_attachments(7, URL),
        cards.complain_confirm_attachments(7, URL),
    ]
    return [b for atts in attachment_lists for a in atts for b in a["actions"]]


def test_button_ids_are_alphanumeric():
    buttons = all_buttons()
    assert buttons
    for b in buttons:
        assert re.fullmatch(r"[A-Za-z0-9]+", b["id"]), b["id"]


def test_button_ids_unique_within_each_card():
    user = User(id=1, mm_user_id="m1", username="u1", state=UserState.ACTIVE)
    for atts in [
        cards.menu_attachments(user, URL),
        cards.pair_card_attachments(7, URL),
        cards.postpone_confirm_attachments(7, URL),
        cards.midweek_attachments(7, URL),
        cards.survey_attachments(7, URL),
        cards.rating_attachments(7, URL),
    ]:
        ids = [b["id"] for a in atts for b in a["actions"]]
        assert len(ids) == len(set(ids)), ids
