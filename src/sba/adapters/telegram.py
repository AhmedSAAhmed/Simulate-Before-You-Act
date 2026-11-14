"""`send_message` over the Telegram Bot API. Recallable for 48 hours with deleteMessage."""

from __future__ import annotations

import logging
import re
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


class TelegramError(RuntimeError):
    def __init__(self, description: str, code: int | None = None) -> None:
        super().__init__(description)
        self.code = code


class TelegramClient:
    """Thin Bot API client. Never logs or returns the token."""

    def __init__(self, token: str, *, transport: httpx.BaseTransport | None = None, timeout: float = 10.0) -> None:
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set")
        self._http = httpx.Client(base_url=f"https://api.telegram.org/bot{token}/", transport=transport,
                                  timeout=timeout)

    def _call(self, method: str, **params: Any) -> Any:
        try:
            resp = self._http.post(method, json=params)
            data = resp.json()
        except (httpx.HTTPError, ValueError) as err:
            raise TelegramError(f"{method}: {type(err).__name__}") from None
        if not data.get("ok"):
            raise TelegramError(str(data.get("description", "request failed")), data.get("error_code"))
        return data["result"]

    def get_chat(self, chat_id: str) -> dict[str, Any]:
        return self._call("getChat", chat_id=chat_id)

    def send_message(self, chat_id: str, text: str) -> dict[str, Any]:
        return self._call("sendMessage", chat_id=chat_id, text=text)

    def delete_message(self, chat_id: str, message_id: int) -> bool:
        return bool(self._call("deleteMessage", chat_id=chat_id, message_id=message_id))


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
        for target in _one_per_contact(targets):
            contact = self.crm.contact(target.contact_id)
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
                sim.blockers.append(Blocker(action_index=index, record_id=cid, rule="no_demo_inbox", hard=True,
                                            detail=f"{who} routes to the demo inbox, which isn't set "
                                                   f"(TELEGRAM_DEMO_CHAT_ID)."))
                continue
            reach = ctx.read("telegram", chat_id, "reachable", self._reach(chat_id, this_run)) if self.client else "yes"
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
            if route == "demo inbox":
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
        for _ in range(2):
            try:
                self.client.get_chat(chat_id)  # type: ignore[union-attr]
                self._reachable[chat_id] = "yes"
                return "yes"
            except TelegramError as err:
                if err.code is not None:  # Telegram answered: a real refusal, not a glitch
                    self._reachable[chat_id] = "no"
                    return "no"
        return "unknown"

    def execute(self, effect: Effect, *, run_id: str) -> ExecResult:
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
