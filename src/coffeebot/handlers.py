"""Обработчики: текстовые команды в DM, нажатия кнопок, еженедельный матчинг.

Сценарии описаны в spec/architecture.md (раздел «Интерфейс»).
"""

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from coffeebot import cards, texts
from coffeebot.config import Settings
from coffeebot.db.models import User, UserState
from coffeebot.events import IncomingDM
from coffeebot.mm import MattermostGateway
from coffeebot.services import matching, users

log = logging.getLogger(__name__)

REGISTER_WORDS = {"регистрация", "register", "старт", "start"}
PAUSE_WORDS = {"пауза", "pause", "стоп", "stop"}
RESUME_WORDS = {"возобновить", "resume"}
PROFILE_WORDS = {"профиль", "profile"}
HELP_WORDS = {"помощь", "help", "справка", "меню"}


class BotHandlers:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        gateway: MattermostGateway,
        settings: Settings,
    ):
        self.session_factory = session_factory
        self.gateway = gateway
        self.settings = settings
        self.tz = ZoneInfo(settings.tz)

    # --- личные сообщения -------------------------------------------------

    def on_dm(self, dm: IncomingDM) -> None:
        with self.session_factory() as session:
            user = users.get_by_mm_id(session, dm.user_id)
            word = dm.text.split(maxsplit=1)[0].lower()

            if word in HELP_WORDS:
                self._send_menu(dm.user_id, user, texts.HELP)
            elif word in REGISTER_WORDS:
                self._do_register(session, dm.user_id, dm.username or None)
            elif word in PAUSE_WORDS:
                self._do_pause(session, user, dm.user_id)
            elif word in RESUME_WORDS:
                self._do_resume(session, user, dm.user_id)
            elif word in PROFILE_WORDS:
                self._do_profile(session, user, dm)
            elif user is not None and user.awaiting_profile:
                users.set_profile(session, user, dm.text)
                self.gateway.dm(dm.user_id, texts.PROFILE_SAVED.format(profile=user.profile))
            else:
                self._send_menu(dm.user_id, user, texts.UNKNOWN_COMMAND + "\n\n" + texts.HELP)

    # --- нажатия кнопок ----------------------------------------------------

    def on_action(self, mm_user_id: str, username: str, action: str) -> None:
        with self.session_factory() as session:
            user = users.get_by_mm_id(session, mm_user_id)
            if action == "register":
                self._do_register(session, mm_user_id, username or None)
            elif action == "pause":
                self._do_pause(session, user, mm_user_id)
            elif action == "resume":
                self._do_resume(session, user, mm_user_id)
            elif action == "edit_profile":
                if user is not None:
                    users.start_profile_edit(session, user)
                    self.gateway.dm(mm_user_id, texts.PROFILE_EDIT_PROMPT)
            else:
                log.warning("Неизвестное действие кнопки: %s от %s", action, mm_user_id)

    # --- сценарии ----------------------------------------------------------

    def _send_menu(self, mm_user_id: str, user: User | None, text: str) -> None:
        attachments = cards.menu_attachments(user, self.settings.actions_url)
        self.gateway.dm(mm_user_id, text, attachments)

    def _do_register(self, session: Session, mm_user_id: str, username: str | None) -> None:
        if username is None:
            username = self.gateway.username(mm_user_id)
        user, created = users.register(session, mm_user_id, username)
        if created:
            self.gateway.dm(mm_user_id, texts.REGISTERED_NEW)
        elif user.state == UserState.ACTIVE:
            self.gateway.dm(mm_user_id, texts.REGISTERED_AGAIN)

    def _do_pause(self, session: Session, user: User | None, mm_user_id: str) -> None:
        if user is None:
            self._send_menu(mm_user_id, None, texts.NOT_REGISTERED_HINT)
            return
        if users.pause(session, user):
            self.gateway.dm(mm_user_id, texts.PAUSED)
        else:
            self.gateway.dm(mm_user_id, texts.PAUSED_BY_ADMIN)

    def _do_resume(self, session: Session, user: User | None, mm_user_id: str) -> None:
        if user is None:
            self._send_menu(mm_user_id, None, texts.NOT_REGISTERED_HINT)
            return
        if users.resume(session, user):
            self.gateway.dm(mm_user_id, texts.RESUMED)
        else:
            self.gateway.dm(mm_user_id, texts.PAUSED_BY_ADMIN)

    def _do_profile(self, session: Session, user: User | None, dm: IncomingDM) -> None:
        if user is None:
            self._send_menu(dm.user_id, None, texts.NOT_REGISTERED_HINT)
            return
        parts = dm.text.split(maxsplit=1)
        if len(parts) > 1:  # «профиль <текст>» — сохранить сразу
            users.set_profile(session, user, parts[1])
            self.gateway.dm(dm.user_id, texts.PROFILE_SAVED.format(profile=user.profile))
        elif user.profile:
            attachments = cards.menu_attachments(user, self.settings.actions_url)
            self.gateway.dm(
                dm.user_id, texts.PROFILE_SHOW.format(profile=user.profile), attachments
            )
        else:
            users.start_profile_edit(session, user)
            self.gateway.dm(dm.user_id, texts.PROFILE_EMPTY + " " + texts.PROFILE_EDIT_PROMPT)

    # --- еженедельный матчинг ----------------------------------------------

    def run_matching_job(self) -> None:
        """Понедельничный матчинг + уведомления + анонс. Идемпотентно."""
        today = datetime.now(self.tz).date()
        week_start = matching.current_week_start(today)
        with self.session_factory() as session:
            result = matching.run_weekly_matching(session, week_start)
            self._notify_pairs(session, week_start)
            if result is not None:
                self._announce(result)

    def notify_pending(self) -> None:
        """Дослать уведомления, не отправленные из-за рестарта (без анонса)."""
        today = datetime.now(self.tz).date()
        week_start = matching.current_week_start(today)
        with self.session_factory() as session:
            self._notify_pairs(session, week_start)

    def _notify_pairs(self, session: Session, week_start) -> None:
        for meeting in matching.pending_notifications(session, week_start):
            u1, u2 = meeting.user1, meeting.user2
            try:
                channel_id = self.gateway.group_channel([u1.mm_user_id, u2.mm_user_id])
                self.gateway.post(
                    channel_id,
                    texts.PAIR_CARD.format(
                        mention1=f"@{u1.username}",
                        mention2=f"@{u2.username}",
                        profile1=u1.profile or texts.PROFILE_NOT_FILLED,
                        profile2=u2.profile or texts.PROFILE_NOT_FILLED,
                    ),
                )
            except Exception:
                log.exception("Не удалось уведомить пару %s", meeting)
                continue
            meeting.notified_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()  # фиксируем по одной — рестарт не дублирует рассылку

    def _announce(self, result: matching.MatchResult) -> None:
        if not self.settings.announce_channel_id:
            return
        unmatched_part = (
            texts.ANNOUNCE_UNMATCHED.format(n=len(result.unmatched)) if result.unmatched else ""
        )
        try:
            self.gateway.post(
                self.settings.announce_channel_id,
                texts.ANNOUNCE.format(
                    pairs=len(result.meetings),
                    unmatched_part=unmatched_part,
                    bot_username=self.gateway.bot_username,
                ),
            )
        except Exception:
            log.exception("Не удалось отправить анонс в канал")
