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
from coffeebot.services import complaints as complaints_svc
from coffeebot.services import matching, users
from coffeebot.services import meetings as meetings_svc

log = logging.getLogger(__name__)

REGISTER_WORDS = {"регистрация", "register", "старт", "start"}
PAUSE_WORDS = {"пауза", "pause", "стоп", "stop"}
RESUME_WORDS = {"возобновить", "resume"}
PROFILE_WORDS = {"профиль", "profile"}
HELP_WORDS = {"помощь", "help", "справка", "меню"}
COMPLAIN_WORDS = {"пожаловаться", "жалоба", "complain"}
ADMIN_WORDS = {"админ", "admin"}


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

            if word in ADMIN_WORDS:
                self._on_admin(session, dm)
            elif word in HELP_WORDS:
                self._send_menu(dm.user_id, user, texts.HELP)
            elif word in COMPLAIN_WORDS:
                self._do_complain(session, user, dm)
            elif word in REGISTER_WORDS:
                self._do_register(session, dm.user_id, dm.username or None)
            elif word in PAUSE_WORDS:
                self._do_pause(session, user, dm.user_id)
            elif word in RESUME_WORDS:
                self._do_resume(session, user, dm.user_id)
            elif word in PROFILE_WORDS:
                self._do_profile(session, user, dm)
            elif user is not None and user.awaiting_profile:
                if users.set_profile(session, user, dm.text):
                    self.gateway.dm(
                        dm.user_id, texts.PROFILE_SAVED.format(profile=user.profile)
                    )
                else:
                    self.gateway.dm(
                        dm.user_id,
                        texts.PROFILE_TOO_LONG.format(max_len=users.PROFILE_MAX_LEN),
                    )
            else:
                self._send_menu(dm.user_id, user, texts.UNKNOWN_COMMAND + "\n\n" + texts.HELP)

    # --- нажатия кнопок ----------------------------------------------------

    def on_action(self, mm_user_id: str, username: str, context: dict) -> None:
        action = context.get("action")
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
            elif action in (
                "midweek",
                "survey",
                "rate",
                "complain",
                "decline",
                "postpone",
                "postpone_accept",
                "postpone_decline",
            ):
                self._on_meeting_action(session, user, mm_user_id, action, context)
            else:
                log.warning("Неизвестное действие кнопки: %s от %s", action, mm_user_id)

    def _on_meeting_action(
        self, session: Session, user: User | None, mm_user_id: str, action: str, context: dict
    ) -> None:
        meeting = meetings_svc.get(session, int(context.get("meeting_id", 0)))
        if user is None or meeting is None:
            log.warning("Действие %s: нет пользователя/встречи (%s)", action, context)
            return
        if meetings_svc.user_slot(meeting, user) is None:
            self.gateway.dm(mm_user_id, texts.NOT_YOUR_MEETING)
            return
        value = context.get("value")
        if action == "midweek":
            if meetings_svc.set_midweek_status(session, meeting, user, str(value)):
                self.gateway.dm(mm_user_id, texts.MIDWEEK_THANKS[str(value)])
        elif action == "survey":
            happened = value == "yes"
            meetings_svc.set_survey_answer(session, meeting, user, happened)
            if happened:
                self.gateway.dm(
                    mm_user_id,
                    texts.SURVEY_YES,
                    cards.rating_attachments(meeting.id, self.settings.actions_url),
                )
            else:
                self.gateway.dm(mm_user_id, texts.SURVEY_NO)
        elif action == "rate":
            if meetings_svc.set_rating(session, meeting, user, int(value)):
                self.gateway.dm(mm_user_id, texts.RATING_THANKS.format(value=value))
            else:
                self.gateway.dm(mm_user_id, texts.MEETING_NOT_RATEABLE)
        elif action == "complain":
            self._confirm_complain(session, meeting, user, mm_user_id)
        elif action == "decline":
            self._on_decline(session, meeting, user, mm_user_id)
        elif action == "postpone":
            self._on_postpone(session, meeting, user, mm_user_id)
        elif action == "postpone_accept":
            self._on_postpone_accept(session, meeting, user, mm_user_id)
        elif action == "postpone_decline":
            self._on_postpone_decline(session, meeting, user, mm_user_id)

    # --- отказ от пары и перенос (этап 3) -----------------------------------

    def _on_decline(self, session: Session, meeting, user: User, mm_user_id: str) -> None:
        partner = meetings_svc.partner_of(meeting, user)
        if not meetings_svc.decline_pair(session, meeting, user):
            self.gateway.dm(mm_user_id, texts.PAIR_ACTION_TOO_LATE)
            return
        week_start = matching.current_week_start(datetime.now(self.tz).date())
        new_meetings = matching.domatch(session, week_start)
        self._notify_pairs(session, week_start)
        matched = {m.user1_id for m in new_meetings} | {m.user2_id for m in new_meetings}
        self.gateway.dm(
            mm_user_id,
            texts.DECLINE_DONE_REMATCHED if user.id in matched else texts.DECLINE_DONE_POOLED,
        )
        partner_text = (
            texts.PARTNER_DECLINED_REMATCHED
            if partner.id in matched
            else texts.PARTNER_DECLINED_POOLED
        )
        try:
            self.gateway.dm(partner.mm_user_id, partner_text.format(partner=user.username))
        except Exception:
            log.exception("Не удалось уведомить @%s об отказе от пары", partner.username)

    def _on_postpone(self, session: Session, meeting, user: User, mm_user_id: str) -> None:
        partner = meetings_svc.partner_of(meeting, user)
        if not meetings_svc.propose_postpone(session, meeting, user):
            self.gateway.dm(mm_user_id, texts.PAIR_ACTION_TOO_LATE)
            return
        self.gateway.dm(mm_user_id, texts.POSTPONE_PROPOSED.format(partner=partner.username))
        try:
            self.gateway.dm(
                partner.mm_user_id,
                texts.POSTPONE_REQUEST.format(partner=user.username),
                cards.postpone_confirm_attachments(meeting.id, self.settings.actions_url),
            )
        except Exception:
            log.exception("Не удалось отправить запрос переноса @%s", partner.username)

    def _on_postpone_accept(
        self, session: Session, meeting, user: User, mm_user_id: str
    ) -> None:
        proposer = meetings_svc.partner_of(meeting, user)  # инициатор переноса
        if meetings_svc.accept_postpone(session, meeting, user) is None:
            self.gateway.dm(mm_user_id, texts.PAIR_ACTION_TOO_LATE)
            return
        self.gateway.dm(
            mm_user_id, texts.POSTPONE_ACCEPTED_DONE.format(partner=proposer.username)
        )
        try:
            self.gateway.dm(
                proposer.mm_user_id,
                texts.POSTPONE_ACCEPTED_NOTIFY.format(partner=user.username),
            )
        except Exception:
            log.exception("Не удалось уведомить @%s о согласии на перенос", proposer.username)

    def _on_postpone_decline(
        self, session: Session, meeting, user: User, mm_user_id: str
    ) -> None:
        proposer = meetings_svc.partner_of(meeting, user)
        if not meetings_svc.decline_postpone(session, meeting, user):
            self.gateway.dm(mm_user_id, texts.PAIR_ACTION_TOO_LATE)
            return
        self.gateway.dm(
            mm_user_id, texts.POSTPONE_DECLINED_DONE.format(partner=proposer.username)
        )
        try:
            self.gateway.dm(
                proposer.mm_user_id,
                texts.POSTPONE_DECLINED_NOTIFY.format(partner=user.username),
            )
        except Exception:
            log.exception("Не удалось уведомить @%s об отказе от переноса", proposer.username)

    def _maybe_domatch_after_join(self, session: Session, user: User) -> None:
        """Домэтч присоединившегося среди недели участника (этап 3)."""
        if user.state != UserState.ACTIVE:
            return
        week_start = matching.current_week_start(datetime.now(self.tz).date())
        if not matching.matching_done(session, week_start):
            return  # матчинга на этой неделе ещё не было — ждём понедельника
        if matching.domatch(session, week_start):
            self._notify_pairs(session, week_start)

    # --- жалобы --------------------------------------------------------------

    def _do_complain(self, session: Session, user: User | None, dm: IncomingDM) -> None:
        if user is None:
            self._send_menu(dm.user_id, None, texts.NOT_REGISTERED_HINT)
            return
        week_start = matching.current_week_start(datetime.now(self.tz).date())
        meeting = meetings_svc.user_meeting_of_week(session, user, week_start)
        if meeting is None:
            self.gateway.dm(dm.user_id, texts.COMPLAIN_NO_MEETING)
            return
        accused = meetings_svc.partner_of(meeting, user)
        self.gateway.dm(
            dm.user_id,
            texts.COMPLAIN_CONFIRM.format(accused=f"@{accused.username}"),
            cards.complain_confirm_attachments(meeting.id, self.settings.actions_url),
        )

    def _confirm_complain(
        self, session: Session, meeting, reporter: User, mm_user_id: str
    ) -> None:
        accused = meetings_svc.partner_of(meeting, reporter)
        mention = f"@{accused.username}"
        if accused.state == UserState.PAUSED_BY_COMPLAINT:
            self.gateway.dm(mm_user_id, texts.COMPLAIN_ALREADY.format(accused=mention))
            return
        complaint = complaints_svc.create(session, meeting, reporter, accused)
        self.gateway.dm(mm_user_id, texts.COMPLAIN_DONE.format(accused=mention))
        self._notify_admins(
            texts.COMPLAIN_ADMIN_ALERT.format(
                complaint_id=complaint.id,
                reporter=reporter.username,
                accused=accused.username,
                meeting_id=meeting.id,
            )
        )

    def _notify_admins(self, message: str) -> None:
        for admin_name in sorted(self.settings.admin_username_set):
            try:
                self.gateway.dm(self.gateway.user_id_by_username(admin_name), message)
            except Exception:
                log.exception("Не удалось уведомить админа @%s", admin_name)

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
        self._maybe_domatch_after_join(session, user)

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
            self._maybe_domatch_after_join(session, user)
        else:
            self.gateway.dm(mm_user_id, texts.PAUSED_BY_ADMIN)

    def _do_profile(self, session: Session, user: User | None, dm: IncomingDM) -> None:
        if user is None:
            self._send_menu(dm.user_id, None, texts.NOT_REGISTERED_HINT)
            return
        parts = dm.text.split(maxsplit=1)
        if len(parts) > 1:  # «профиль <текст>» — сохранить сразу
            if users.set_profile(session, user, parts[1]):
                self.gateway.dm(dm.user_id, texts.PROFILE_SAVED.format(profile=user.profile))
            else:
                self.gateway.dm(
                    dm.user_id, texts.PROFILE_TOO_LONG.format(max_len=users.PROFILE_MAX_LEN)
                )
        elif user.profile:
            attachments = cards.menu_attachments(user, self.settings.actions_url)
            self.gateway.dm(
                dm.user_id, texts.PROFILE_SHOW.format(profile=user.profile), attachments
            )
        else:
            users.start_profile_edit(session, user)
            self.gateway.dm(dm.user_id, texts.PROFILE_EMPTY + " " + texts.PROFILE_EDIT_PROMPT)

    # --- админка -------------------------------------------------------------

    def _on_admin(self, session: Session, dm: IncomingDM) -> None:
        username = dm.username or self.gateway.username(dm.user_id)
        if username not in self.settings.admin_username_set:
            self.gateway.dm(dm.user_id, texts.ADMIN_ONLY)
            return
        parts = dm.text.split()
        sub = parts[1].lower() if len(parts) > 1 else "помощь"
        arg = parts[2] if len(parts) > 2 else None
        if sub in ("участники", "users"):
            self.gateway.dm(dm.user_id, self._report_users(session))
        elif sub in ("встречи", "meetings"):
            self.gateway.dm(dm.user_id, self._report_meetings(session))
        elif sub in ("жалобы", "complaints"):
            self.gateway.dm(dm.user_id, self._report_complaints(session))
        elif sub in ("отменить", "cancel") and arg:
            self._admin_cancel(session, dm.user_id, arg)
        elif sub in ("пауза", "pause") and arg:
            self._admin_pause(session, dm.user_id, arg)
        elif sub in ("снять-паузу", "unpause", "разблокировать") and arg:
            self._admin_unpause(session, dm.user_id, arg)
        else:
            self.gateway.dm(dm.user_id, texts.ADMIN_HELP)

    def _report_users(self, session: Session) -> str:
        all_users = users.all_users(session)
        if not all_users:
            return texts.ADMIN_NO_USERS
        ratings = meetings_svc.ratings(session)
        lines = [texts.ADMIN_USERS_HEADER.format(n=len(all_users))]
        for u in all_users:
            lines.append(
                texts.ADMIN_USER_LINE.format(
                    username=u.username,
                    state=texts.STATE_LABELS.get(u.state.value, u.state.value),
                    rating=ratings.get(u.id, 0),
                    streak=u.unmatched_streak,
                    profile="" if u.profile else " (без профиля)",
                )
            )
        return "\n".join(lines)

    def _report_meetings(self, session: Session) -> str:
        week_start = matching.current_week_start(datetime.now(self.tz).date())
        meetings = meetings_svc.week_meetings(session, week_start)
        if not meetings:
            return texts.ADMIN_NO_MEETINGS
        lines = [texts.ADMIN_MEETINGS_HEADER.format(week=week_start, n=len(meetings))]
        for m in meetings:
            midweek = ""
            if m.midweek_status_u1 or m.midweek_status_u2:
                midweek = f", ср: {m.midweek_status_u1 or '—'}/{m.midweek_status_u2 or '—'}"
            ratings = ""
            if m.rating_u1 is not None or m.rating_u2 is not None:
                r1 = m.rating_u1 if m.rating_u1 is not None else "—"
                r2 = m.rating_u2 if m.rating_u2 is not None else "—"
                ratings = f", оценки: {r1}/{r2}"
            lines.append(
                texts.ADMIN_MEETING_LINE.format(
                    id=m.id,
                    u1=m.user1.username,
                    u2=m.user2.username,
                    status=m.status.value,
                    midweek=midweek,
                    ratings=ratings,
                )
            )
        return "\n".join(lines)

    def _report_complaints(self, session: Session) -> str:
        complaints = complaints_svc.open_list(session)
        if not complaints:
            return texts.ADMIN_NO_COMPLAINTS
        lines = [texts.ADMIN_COMPLAINTS_HEADER.format(n=len(complaints))]
        for c in complaints:
            lines.append(
                texts.ADMIN_COMPLAINT_LINE.format(
                    id=c.id,
                    reporter=c.reporter.username,
                    accused=c.accused.username,
                    meeting_id=c.meeting_id,
                    created=c.created_at.date(),
                )
            )
        return "\n".join(lines)

    def _admin_cancel(self, session: Session, admin_id: str, arg: str) -> None:
        meeting = meetings_svc.get(session, int(arg)) if arg.isdigit() else None
        if meeting is None:
            self.gateway.dm(admin_id, texts.ADMIN_CANCEL_NOT_FOUND.format(id=arg))
            return
        if not meetings_svc.admin_cancel(session, meeting):
            self.gateway.dm(
                admin_id,
                texts.ADMIN_CANCEL_FINAL.format(id=meeting.id, status=meeting.status.value),
            )
            return
        for user in (meeting.user1, meeting.user2):
            partner = meetings_svc.partner_of(meeting, user)
            try:
                self.gateway.dm(
                    user.mm_user_id,
                    texts.MEETING_CANCELLED_BY_ADMIN.format(partner=partner.username),
                )
            except Exception:
                log.exception("Не удалось уведомить @%s об отмене", user.username)
        self.gateway.dm(
            admin_id,
            texts.ADMIN_CANCELLED.format(
                id=meeting.id, u1=meeting.user1.username, u2=meeting.user2.username
            ),
        )

    def _admin_pause(self, session: Session, admin_id: str, arg: str) -> None:
        user = users.get_by_username(session, arg)
        if user is None:
            self.gateway.dm(admin_id, texts.ADMIN_USER_NOT_FOUND.format(username=arg))
            return
        users.admin_pause(session, user)
        self.gateway.dm(admin_id, texts.ADMIN_PAUSED.format(username=user.username))
        try:
            self.gateway.dm(user.mm_user_id, texts.USER_PAUSED_BY_ADMIN_DM)
        except Exception:
            log.exception("Не удалось уведомить @%s о паузе", user.username)

    def _admin_unpause(self, session: Session, admin_id: str, arg: str) -> None:
        user = users.get_by_username(session, arg)
        if user is None:
            self.gateway.dm(admin_id, texts.ADMIN_USER_NOT_FOUND.format(username=arg))
            return
        resolved = complaints_svc.resolve_for(session, user)
        users.admin_unpause(session, user)
        complaints_note = (
            texts.ADMIN_UNPAUSED_COMPLAINTS.format(n=resolved) if resolved else ""
        )
        self.gateway.dm(
            admin_id,
            texts.ADMIN_UNPAUSED.format(username=user.username, complaints=complaints_note),
        )
        try:
            self.gateway.dm(user.mm_user_id, texts.USER_UNPAUSED_DM)
        except Exception:
            log.exception("Не удалось уведомить @%s о снятии паузы", user.username)

    # --- еженедельный матчинг ----------------------------------------------

    def run_matching_job(self) -> None:
        """Понедельничный матчинг + уведомления + анонс. Идемпотентно."""
        today = datetime.now(self.tz).date()
        week_start = matching.current_week_start(today)
        with self.session_factory() as session:
            meetings_svc.close_stale(session, week_start)  # прошлая неделя без итога
            result = matching.run_weekly_matching(session, week_start)
            self._notify_pairs(session, week_start)
            if result is not None:
                self._announce(result)

    def run_midweek_job(self) -> None:
        """Среда: напоминание + опрос статуса каждому участнику пары. Идемпотентно."""
        week_start = matching.current_week_start(datetime.now(self.tz).date())
        with self.session_factory() as session:
            for meeting in meetings_svc.for_midweek_poll(session, week_start):
                attachments = cards.midweek_attachments(meeting.id, self.settings.actions_url)
                try:
                    for user in (meeting.user1, meeting.user2):
                        partner = meetings_svc.partner_of(meeting, user)
                        self.gateway.dm(
                            user.mm_user_id,
                            texts.MIDWEEK_POLL.format(partner=f"@{partner.username}"),
                            attachments,
                        )
                except Exception:
                    log.exception("Опрос среды: не удалось отправить по %s", meeting)
                    continue
                meeting.midweek_sent_at = datetime.now(UTC).replace(tzinfo=None)
                session.commit()

    def run_survey_job(self) -> None:
        """Воскресенье: итоговый опрос (состоялась? + оценка). Идемпотентно."""
        week_start = matching.current_week_start(datetime.now(self.tz).date())
        with self.session_factory() as session:
            for meeting in meetings_svc.for_survey(session, week_start):
                attachments = cards.survey_attachments(meeting.id, self.settings.actions_url)
                try:
                    for user in (meeting.user1, meeting.user2):
                        partner = meetings_svc.partner_of(meeting, user)
                        self.gateway.dm(
                            user.mm_user_id,
                            texts.SURVEY.format(partner=f"@{partner.username}"),
                            attachments,
                        )
                except Exception:
                    log.exception("Итоговый опрос: не удалось отправить по %s", meeting)
                    continue
                meeting.survey_sent_at = datetime.now(UTC).replace(tzinfo=None)
                session.commit()

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
                # sanitize и при отправке — защищает и профили, сохранённые
                # до введения санитизации
                self.gateway.post(
                    channel_id,
                    texts.PAIR_CARD.format(
                        mention1=f"@{u1.username}",
                        mention2=f"@{u2.username}",
                        profile1=users.sanitize_profile(u1.profile or "")
                        or texts.PROFILE_NOT_FILLED,
                        profile2=users.sanitize_profile(u2.profile or "")
                        or texts.PROFILE_NOT_FILLED,
                    ),
                    cards.pair_card_attachments(meeting.id, self.settings.actions_url),
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
