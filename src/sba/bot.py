"""The Telegram front door: the same pipeline as the web demo, driven from a chat.

Usage for local testing (no public URL needed): python -m sba.bot --poll
On Render the app registers a webhook instead (see `sba.main`).
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from typing import Any

from sba import bot_cards as cards
from sba.adapters.telegram import TelegramError
from sba.crm.seed import DEMO_REQUEST
from sba.pipeline import StageFailed, colleague_credits_first_customer, resolve_blockers
from sba.services import Services
from sba.sessions import RunLimit, Session
from sba.store.approvals import ApprovalError

log = logging.getLogger(__name__)
HTML = "HTML"
STALE = ("⏱ That card is out of date: the plan changed after it was sent, so its buttons can't release "
         "anything. Use the newest card.")
QUOTA_USED = ("🔎 You've used today's {n} model-planned requests, so this run uses the example plan (no model "
              "call). Everything else works the same; your quota resets tomorrow (UTC).")


@dataclass
class Bot:
    services: Services

    @property
    def tg(self):
        return self.services.telegram

    # ---------- entry point ----------

    def handle(self, update: dict[str, Any]) -> None:
        """Handle one Telegram update. Never raises: a failure is logged and told to the person."""
        chat_id = _chat_of(update)
        try:
            if "callback_query" in update:
                self._on_button(update["callback_query"])
            elif "message" in update:
                self._on_message(update["message"])
        except RunLimit as err:
            self._say(chat_id, f"⏳ {err}.")
        except Exception:  # noqa: BLE001 - one bad update must not take the bot down
            log.exception("telegram update failed")
            self._say(chat_id, "Something went wrong on my side. Nothing was written unless a result card "
                               "says so. Try again, or /reset.")

    # ---------- messages ----------

    def _on_message(self, msg: dict[str, Any]) -> None:
        chat = msg.get("chat", {})
        if chat.get("type") != "private":
            return  # direct messages only
        chat_id, name = str(chat["id"]), (msg.get("from") or {}).get("first_name")
        text = (msg.get("text") or "").strip()
        command, _, arg = text.partition(" ")
        command = command.split("@")[0].lower()
        sessions = self.services.sessions

        if command == "/start":
            code = arg.strip()
            if code and code != "demo":
                linked = sessions.link_chat(code, chat_id, name)
                if linked:
                    self._say(chat_id, "🔗 <b>Linked to your web demo.</b> This chat is now your demo inbox, and "
                                       "your scenario was reloaded with you as customer #1. Run something on "
                                       "the web page or right here.", markup=cards.EXAMPLE_BUTTON)
                    return
                self._say(chat_id, "That link expired or was already used, so here's a demo of your own.")
            sessions.get_or_create_for_chat(chat_id, name)
            self._say(chat_id, cards.WELCOME, markup=cards.EXAMPLE_BUTTON)
            return

        session, created = sessions.get_or_create_for_chat(chat_id, name)
        if created:
            self._say(chat_id, cards.WELCOME, markup=cards.EXAMPLE_BUTTON)
        if command == "/help" or not text:
            self._say(chat_id, cards.HELP, markup=cards.EXAMPLE_BUTTON)
        elif command == "/reset":
            sessions.reset(session)
            self._say(chat_id, "🔄 Fresh scenario loaded: 9 double-charged customers, wallets as they were.")
        elif command == "/forget":
            sessions.forget(session)
            self._say(chat_id, "🗑 Deleted your demo data, your runs and your chat id. /start begins again.")
        elif command in ("/demo", "/example"):
            self._new_request(session, DEMO_REQUEST)
        elif command.startswith("/"):
            self._say(chat_id, cards.HELP)
        else:
            self._new_request(session, text)

    def _new_request(self, session: Session, request: str) -> None:
        chat_id = session.telegram_chat_id
        with self.services.sessions.slot(session):
            planned = self.services.sessions.take_model_request(session)
            self._say(chat_id, "🔎 Planning and simulating against your copy of the CRM…" if planned else
                      QUOTA_USED.format(n=self.services.sessions.daily_runs))
            pipe = self.services.pipeline(session)
            run_id = self.services.store.new_run_id(self.services.clock())
            self.services.sessions.remember_run(session, run_id)
            try:
                plan = pipe.plan(request, use_example=not planned, fallback_to_example=True, run_id=run_id)
            except StageFailed as err:
                self._say(chat_id, "✏️ I couldn't turn that into something this demo can do (credits, "
                                   f"messages, tags, deletions).\n<i>{_short(err.why)}</i>\n\nTry /demo.")
                return
            sim = pipe.simulate(plan)
            self._card(session, plan, sim, pipe.planner_model.get(run_id, ""))

    # ---------- buttons ----------

    def _on_button(self, cb: dict[str, Any]) -> None:
        self.tg.answer_callback(cb["id"])
        message = cb.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id", ""))
        session = self.services.sessions.by_chat(chat_id)
        if session is None:
            self._say(chat_id, "Send /start first.")
            return
        data = cb.get("data") or ""
        if data == "ex":
            self._new_request(session, DEMO_REQUEST)
            return
        op, _, rest = data.partition(":")
        run_id, _, short_hash = rest.partition(":")
        if not run_id or not self.services.sessions.owns(session, run_id):
            self._say(chat_id, "That run belongs to someone else, or no longer exists.")
            return
        pipe = self.services.pipeline(session)
        saved = pipe.load(run_id)
        if op != "u" and short_hash != saved.simulation.plan_hash[:8]:
            self._say(chat_id, STALE)
            return
        if message.get("message_id"):
            self.tg.edit_reply_markup(chat_id, message["message_id"])  # one press per card
        name = (cb.get("from") or {}).get("first_name") or "Telegram reviewer"

        with self.services.sessions.slot(session):
            plan, sim, blind = saved.plan, saved.simulation, saved.blind_spots
            if op in ("x", "y"):
                tweaked = resolve_blockers(plan, sim, exclude_items=op == "x",
                                           accept_rules_reason=f"Accepted in Telegram by {name}" if op == "y" else None)
                self._card(session, tweaked, pipe.simulate(tweaked, blind_spots=blind, reuse_critic_from=sim), self._model(run_id), blind)
            elif op == "fb":
                self._card(session, plan, pipe.simulate(plan, blind_spots=("automations",), reuse_critic_from=sim), self._model(run_id),
                           True)
            elif op in ("a", "fd"):
                self._approve(session, pipe, saved, name, drift=op == "fd")
            elif op == "n":
                pipe.decide(plan, sim, approver=name, verdict="reject")
                self._say(chat_id, "🚫 Rejected. Nothing was written.")
            elif op == "u":
                try:
                    self._say(chat_id, cards.rollback_card(pipe.roll_back_completed(run_id)))
                except ValueError as err:
                    self._say(chat_id, f"Nothing to roll back: {err}.")

    def _approve(self, session: Session, pipe, saved, name: str, *, drift: bool) -> None:
        chat_id = session.telegram_chat_id
        try:
            decision = pipe.decide(saved.plan, saved.simulation, approver=name, verdict="approve")
        except ApprovalError as err:
            self._say(chat_id, f"⛔ Can't approve: {err}.")
            return
        self._say(chat_id, "▶️ Approved, bound to plan <code>{}</code>. Running the canary first…"
                  .format(saved.simulation.plan_hash[:8])
                  + ("\n🧪 <i>Failure lab: a colleague will credit a customer by hand right now.</i>" if drift else ""))
        before = colleague_credits_first_customer(pipe.crm, saved.simulation) if drift else None
        result = pipe.execute(saved.plan, saved.simulation, decision, blind_spots=saved.blind_spots,
                              before_writes=before)
        text, markup = cards.result_card(result, saved.plan)
        self._say(chat_id, text, markup=markup)
        if result.verification.outcome == "drift":
            fresh = pipe.simulate(saved.plan, blind_spots=saved.blind_spots,
                                  reuse_critic_from=saved.simulation)
            self._card(session, saved.plan, fresh, self._model(saved.plan.run_id), bool(saved.blind_spots))

    # ---------- helpers ----------

    def _card(self, session: Session, plan, sim, model: str, blind: bool = False) -> None:
        text, markup = cards.simulation_card(plan, sim, model=model, web_url=self.services.public_url, blind=blind)
        self._say(session.telegram_chat_id, text, markup=markup)

    def _model(self, run_id: str) -> str:
        import json

        return json.loads(self.services.store.load(run_id, "01_intent/output/meta.json") or "{}").get("model", "")

    def _say(self, chat_id: str | None, text: str, *, markup: dict | None = None) -> None:
        if not chat_id or self.tg is None:
            return
        try:
            self.tg.send_message(chat_id, text, parse_mode=HTML, reply_markup=markup)
        except TelegramError as err:
            log.warning("couldn't reply in chat: %s", err)


def _chat_of(update: dict[str, Any]) -> str | None:
    msg = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    chat = msg.get("chat") or {}
    return str(chat["id"]) if "id" in chat else None


def _short(text: str, limit: int = 300) -> str:
    from html import escape

    return escape(text if len(text) <= limit else text[:limit] + "…")


def run_polling(services: Services) -> None:
    """Long-poll Telegram (local testing). Removes any webhook first, which a deployed app would set again."""
    if services.telegram is None:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    for attempt in range(5):
        try:
            services.telegram.delete_webhook()
            break
        except TelegramError as err:
            log.warning("deleteWebhook failed (%s); retrying", err)
            time.sleep(2 * (attempt + 1))
    bot, offset, backoff = Bot(services), None, 1.0
    print(f"Polling as @{services.bot_username}. Ctrl+C to stop.", flush=True)
    while True:
        try:
            updates = services.telegram.get_updates(offset)
            backoff = 1.0
        except TelegramError as err:
            log.warning("getUpdates failed (%s); next try in %.0fs", err, backoff)
            time.sleep(backoff)  # never spin: a dead network would otherwise burn a CPU
            backoff = min(backoff * 2, 30.0)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            bot.handle(update)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if "--poll" not in sys.argv:
        print(__doc__)
        raise SystemExit(2)
    from sba.services import get_services

    run_polling(get_services())
