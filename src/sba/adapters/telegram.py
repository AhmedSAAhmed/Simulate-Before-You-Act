"""`send_message` over the Telegram Bot API. Recallable for 48 hours with deleteMessage."""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from sba.adapters.base import (
    ActionSim,
    ExecResult,
    SelectorError,
    SimContext,
    Target,
    from_action_targets,
    check_shape,
    item_controls,
)
from sba.crm.service import CrmService, Notice, Notifier
from sba.domain.models import Action, ActionKind, Blocker, Effect, SideEffect
from sba.domain.money import fmt

# httpx logs request URLs at INFO, and Telegram puts the bot token in the URL path.
logging.getLogger("httpx").setLevel(logging.WARNING)

PLACEHOLDER = re.compile(r"\{(name|amount)\}")
MAX_TEXT = 4096
LANGUAGES = ("en", "ar")
HELD = "held (no phone linked)"


PER_CHAT_INTERVAL = 1.05  # Telegram allows about one message per second to the same chat
MAX_RETRY_AFTER = 15.0


class TelegramError(RuntimeError):
    def __init__(self, description: str, code: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(description)
        self.code = code
        self.retry_after = retry_after


class TelegramClient:
    """Thin Bot API client. Never logs or returns the token.

    Sends to one chat are paced, and a 429 "retry after N" is waited out and retried: Telegram
    refused that message, so retrying can't send it twice.
    """

    def __init__(
        self,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set")
        self._http = httpx.Client(base_url=f"https://api.telegram.org/bot{token}/", transport=transport,
                                  timeout=timeout)
        self._sleep, self._clock = sleep, clock
        self._last_send: dict[str, float] = {}
        self._pace_lock = threading.Lock()
        self.username: str | None = None

    def _call(self, method: str, *, http_timeout: float | None = None, **params: Any) -> Any:
        # `http_timeout` is ours; a Bot API parameter may itself be called `timeout` (getUpdates).
        for attempt in range(3):
            try:
                resp = self._http.post(method, json=params, **({"timeout": http_timeout} if http_timeout else {}))
                data = resp.json()
            except httpx.ConnectError:
                # The request never reached Telegram, so retrying can't deliver anything twice.
                if attempt < 2:
                    self._sleep(1.0)
                    continue
                raise TelegramError(f"{method}: ConnectError") from None
            except (httpx.HTTPError, ValueError) as err:  # a timeout may have been delivered: don't retry
                raise TelegramError(f"{method}: {type(err).__name__}") from None
            if data.get("ok"):
                return data["result"]
            retry = (data.get("parameters") or {}).get("retry_after")
            if data.get("error_code") == 429 and retry is not None and retry <= MAX_RETRY_AFTER and attempt < 2:
                self._sleep(float(retry))
                continue
            raise TelegramError(str(data.get("description", "request failed")), data.get("error_code"), retry)
        raise TelegramError(f"{method}: still rate-limited", 429)

    def _pace(self, chat_id: str) -> None:
        with self._pace_lock:
            wait = self._last_send.get(chat_id, -1e9) + PER_CHAT_INTERVAL - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last_send[chat_id] = self._clock()

    def get_me(self) -> dict[str, Any]:
        me = self._call("getMe")
        self.username = me.get("username")
        return me

    def get_chat(self, chat_id: str) -> dict[str, Any]:
        return self._call("getChat", chat_id=chat_id)

    def send_message(
        self, chat_id: str, text: str, *, parse_mode: str | None = None, reply_markup: dict | None = None
    ) -> dict[str, Any]:
        self._pace(str(chat_id))
        params: dict[str, Any] = {"chat_id": chat_id, "text": text, "link_preview_options": {"is_disabled": True}}
        if parse_mode:
            params["parse_mode"] = parse_mode
        if reply_markup:
            params["reply_markup"] = reply_markup
        return self._call("sendMessage", **params)

    def edit_reply_markup(self, chat_id: str, message_id: int, reply_markup: dict | None = None) -> None:
        params: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id}
        if reply_markup:
            params["reply_markup"] = reply_markup
        try:
            self._call("editMessageReplyMarkup", **params)
        except TelegramError:
            pass  # the message may be too old or already edited; the buttons just stay

    def answer_callback(self, callback_id: str, text: str | None = None) -> None:
        try:
            self._call("answerCallbackQuery", callback_query_id=callback_id, **({"text": text} if text else {}))
        except TelegramError:
            pass  # a slow answer only means the button spinner times out on the user's side

    def delete_message(self, chat_id: str, message_id: int) -> bool:
        return bool(self._call("deleteMessage", chat_id=chat_id, message_id=message_id))

    def set_webhook(self, url: str, secret_token: str) -> bool:
        return bool(self._call("setWebhook", url=url, secret_token=secret_token,
                               allowed_updates=["message", "callback_query"], drop_pending_updates=True))

    def delete_webhook(self) -> bool:
        return bool(self._call("deleteWebhook", drop_pending_updates=False))

    def get_updates(self, offset: int | None, wait: int = 25) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": wait, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        return self._call("getUpdates", http_timeout=wait + 10, **params)


def render(template: str, *, name: str, amount: str) -> str:
    """Fill only {name} and {amount}; any other braces stay literal (no format-string tricks)."""
    values = {"name": name, "amount": amount}
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


@dataclass
class MessageAdapter:
    crm: CrmService
    client: TelegramClient | None
    demo_chat_id: str | None
    kind: ActionKind = ActionKind.SEND_MESSAGE
    system: str = "telegram"
    _reachable: dict[str, str] = field(default_factory=dict, repr=False)

    def simulate(self, index: int, action: Action, ctx: SimContext) -> ActionSim:
        check_shape(action, index)
        templates = action.params["templates"]
        if not isinstance(templates, dict) or not all(
            k in LANGUAGES and isinstance(v, str) and v.strip() for k, v in templates.items()
        ):
            raise SelectorError("params.templates must map 'en'/'ar' to message text")
        exclude, _ = item_controls(action)  # message blockers are all hard: exclusion is the only fix
        targets = from_action_targets(index, action.selector, ctx)
        sim = ActionSim(rollback="Recall each message with deleteMessage within 48 hours. A customer may "
                                 "already have read it, so a short correction message is drafted as well.")
        if self.client is None:
            sim.side_effects.append(SideEffect(description="Telegram isn't configured, so delivery can't be "
                                                           "checked or performed.", likelihood="high",
                                               source="engine"))
        this_run: dict[str, str] = {}
        merged = _one_per_contact(targets)
        people = self.crm.contacts_by_ids([t.contact_id for t in merged])  # one read for everyone
        for target in merged:
            contact = people.get(target.contact_id)
            if contact is None or contact["deleted_at"] is not None:
                continue
            cid, who = contact["id"], f"{contact['name']} ({contact['id']})"
            opted_out = ctx.read("crm", cid, "opted_out", bool(contact["opted_out"]))
            chat = ctx.read("crm", cid, "telegram_chat_id", contact["telegram_chat_id"])
            lang = ctx.read("crm", cid, "language", contact["language"])
            if cid in exclude:
                sim.notes.append(f"{who} left out by the operator.")
                continue
            if opted_out:
                sim.blockers.append(Blocker(action_index=index, record_id=cid, rule="opted_out", hard=True,
                                            detail=f"{who} opted out of messages; leave them out."))
                continue
            if chat is None:
                sim.blockers.append(Blocker(action_index=index, record_id=cid, rule="no_channel", hard=True,
                                            detail=f"{who} has no Telegram chat; leave them out and reach "
                                                   f"them another way."))
                continue
            route, chat_id = ("demo inbox", self.demo_chat_id) if chat == "demo" else ("own chat", chat)
            if not chat_id:
                route = HELD  # no phone linked: the message is simulated and journaled, never sent
            reach = "yes" if route == HELD or not self.client else \
                ctx.read("telegram", chat_id, "reachable", self._reach(chat_id, this_run))
            if reach == "no":
                sim.blockers.append(Blocker(action_index=index, record_id=cid, rule="unreachable", hard=True,
                                            detail=f"{who}: Telegram says the bot can't reach this chat "
                                                   f"(blocked, or never started)."))
                continue
            if reach == "unknown":
                sim.blockers.append(Blocker(action_index=index, record_id=cid, rule="reachability_unknown",
                                            hard=True, detail=f"{who}: couldn't reach Telegram to check this "
                                                              f"chat (network error). Simulate again."))
                continue
            template = templates.get(lang)
            if template is None:
                sim.blockers.append(Blocker(action_index=index, record_id=cid, rule="missing_template", hard=True,
                                            detail=f"{who} reads {lang!r}, and the plan has no {lang!r} text."))
                continue
            amount = fmt(target.amount_minor, target.currency) if target.currency else ""
            text = render(template, name=contact["name"], amount=amount)
            if route != "own chat":
                text = f"To: {contact['name']} · demo inbox\n\n{text}"
            if len(text) > MAX_TEXT:
                sim.blockers.append(Blocker(action_index=index, record_id=cid, rule="too_long", hard=True,
                                            detail=f"{who}: the message is over Telegram's {MAX_TEXT} limit."))
                continue
            sim.effects.append(Effect(
                action_index=index, system=self.system, record_id=cid, subject=who,
                before={"messages_from_this_run": 0},
                after={"route": route, "chat_id": chat_id, "language": lang, "text": text},
            ))
            sim.targets.append(Target(record_id=cid, contact_id=cid, amount_minor=target.amount_minor,
                                      currency=target.currency))
        sim.totals = {"messages": len(sim.effects)}
        return sim

    def _reach(self, chat_id: str, this_run: dict[str, str]) -> str:
        """'yes', 'no' (Telegram refused) or 'unknown' (network trouble).

        'unknown' is remembered only for the current simulation, so the next one retries.
        """
        if chat_id in self._reachable:
            return self._reachable[chat_id]
        if chat_id in this_run:
            return this_run[chat_id]
        this_run[chat_id] = "unknown"
        try:
            self.client.get_chat(chat_id)  # type: ignore[union-attr]  # the client retries dropped connections
            self._reachable[chat_id] = "yes"
            return "yes"
        except TelegramError as err:
            if err.code is not None:  # Telegram answered: a real refusal, not a glitch
                self._reachable[chat_id] = "no"
                return "no"
        return "unknown"

    def execute(self, effect: Effect, *, run_id: str) -> ExecResult:
        if effect.after["route"] == HELD:
            return ExecResult("done", detail="held: no Telegram chat is linked, so nothing was sent")
        if self.client is None:
            return ExecResult("failed", detail="Telegram isn't configured")
        try:
            sent = self.client.send_message(effect.after["chat_id"], effect.after["text"])
        except TelegramError as err:
            # A timeout may still have delivered: never assume it didn't.
            status = "unknown" if err.code is None else "failed"
            return ExecResult(status, detail=str(err))
        return ExecResult("done", external_ref=f"{effect.after['chat_id']}:{sent['message_id']}")

    def compensate(self, effect: Effect, result: ExecResult, *, run_id: str) -> ExecResult:
        if effect.after["route"] == HELD:
            return ExecResult("rolled_back", detail="held message: nothing was sent, nothing to recall")
        if self.client is None or not result.external_ref:
            return ExecResult("failed", detail="nothing to recall")
        chat_id, message_id = result.external_ref.rsplit(":", 1)
        try:
            self.client.delete_message(chat_id, int(message_id))
        except TelegramError as err:
            return ExecResult("failed", detail=f"recall failed: {err}")
        return ExecResult("rolled_back", detail="message recalled")

    def observe(self, effect: Effect) -> dict[str, Any]:
        # The Bot API can't read a sent message back; the journal's send receipt is the evidence.
        return {"route": effect.after["route"]}


def telegram_notifier(client: TelegramClient, demo_chat_id: str | None) -> Notifier:
    """How the CRM's automations deliver their notices: same routing as agent messages."""

    def send(notice: Notice) -> str | None:
        if notice.telegram_chat_id is None:
            return None
        if notice.telegram_chat_id == "demo":
            if not demo_chat_id:
                return None
            target, text = demo_chat_id, f"To: {notice.contact_name} · demo inbox\n\n{notice.text}"
        else:
            target, text = notice.telegram_chat_id, notice.text
        try:
            sent = client.send_message(target, text)
        except TelegramError:
            return None  # recorded as an undelivered notice (delivery_ref stays empty)
        return f"{target}:{sent['message_id']}"

    return send


def telegram_recall(client: TelegramClient) -> Callable[[str], bool]:
    def recall(delivery_ref: str) -> bool:
        chat_id, message_id = delivery_ref.rsplit(":", 1)
        try:
            return client.delete_message(chat_id, int(message_id))
        except TelegramError:
            return False

    return recall


def _one_per_contact(targets: list[Target]) -> list[Target]:
    """A customer with two duplicates gets one message, naming the total credited."""
    merged: dict[str, Target] = {}
    for t in targets:
        if t.contact_id in merged:
            prev = merged[t.contact_id]
            merged[t.contact_id] = Target(prev.record_id, t.contact_id, prev.amount_minor + t.amount_minor,
                                          prev.currency or t.currency)
        else:
            merged[t.contact_id] = t
    return [merged[k] for k in sorted(merged)]
