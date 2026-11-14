"""The public demo: per-visitor sandboxes, the Telegram bot, the web actions and the webhook.

Telegram and the models are faked; the CRM is a real (in-memory SQLite) database.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sba.adapters.fake_telegram import FakeTelegram
from sba.bot import STALE, Bot
from sba.crm.schema import contacts, init_db, make_engine, wallet_ledger
from sba.llm.router import LLMRouter, UsageMeter, parse_chain
from sba.services import Services
from sba.sessions import SessionManager
from sba.store.runs import RunStore
from sba.ui.actions import WebActions
from tests.conftest import NOW, FakeModels

A, B, C = "5001", "5002", "5003"


@pytest.fixture
def services(tmp_path, fake_telegram) -> Services:
    engine = make_engine("sqlite://")
    init_db(engine)
    router = LLMRouter({"groq": "k", "gemini": "k"},
                       chains={"planner": parse_chain("groq:planner-model"), "critic": parse_chain("gemini:critic")},
                       meter=UsageMeter(10**6), transport=FakeModels())
    return Services(engine=engine, store=RunStore(tmp_path, engine), sessions=SessionManager(engine, clock=lambda: NOW),
                    router=router, telegram=fake_telegram.client(), public_url="https://demo.example",
                    clock=lambda: NOW, bot_username="FakeSbaBot", webhook_secret="s3cret")


@pytest.fixture
def bot(services) -> Bot:
    return Bot(services)


def message(chat: str, text: str, name: str = "Judy", kind: str = "private") -> dict:
    return {"update_id": 1, "message": {"message_id": 1, "text": text, "from": {"first_name": name},
                                        "chat": {"id": int(chat), "type": kind}}}


def press(chat: str, data: str, message_id: int = 1) -> dict:
    return {"update_id": 2, "callback_query": {"id": f"cb-{data}", "data": data, "from": {"first_name": "Judy"},
                                               "message": {"message_id": message_id, "chat": {"id": int(chat)}}}}


def last_card(fake: FakeTelegram, chat: str) -> tuple[str, dict]:
    """The newest message to `chat` that has buttons, with its markup."""
    for chat_id, text, msg_id in reversed(fake.sent):
        if chat_id == chat and fake.markups.get(msg_id):
            return text, fake.markups[msg_id]
    raise AssertionError("no card with buttons")


def button(markup: dict, startswith: str) -> str:
    for row in markup["inline_keyboard"]:
        for b in row:
            if b.get("callback_data", "").startswith(startswith):
                return b["callback_data"]
    raise AssertionError(f"no button {startswith!r} in {markup}")


def to_approvable_card(bot: Bot, fake: FakeTelegram, chat: str) -> str:
    bot.handle(message(chat, "/start"))
    bot.handle(press(chat, "ex"))
    _, card = last_card(fake, chat)
    bot.handle(press(chat, button(card, "x:")))   # leave out the blocked items
    _, card = last_card(fake, chat)
    bot.handle(press(chat, button(card, "y:")))   # accept the automation
    _, card = last_card(fake, chat)
    return button(card, "a:")


# ---------- Telegram ----------

def test_start_gives_each_chat_its_own_seeded_sandbox(bot, services, fake_telegram) -> None:
    bot.handle(message(A, "/start"))
    session = services.sessions.by_chat(A)
    assert session is not None and session.first_name == "Judy"
    crm = services.sessions.crm(session)
    assert crm.contact("c_001")["telegram_chat_id"] == A  # the visitor is customer #1
    assert "Simulate Before You Act" in fake_telegram.texts_to(A)[0]


def test_full_telegram_flow_sends_only_to_the_visitor_and_rolls_back(bot, services, fake_telegram) -> None:
    approve = to_approvable_card(bot, fake_telegram, A)
    before = len(fake_telegram.sent)

    bot.handle(press(A, approve))

    result, markup = last_card(fake_telegram, A)
    assert result.startswith("✅ <b>Done.</b>")
    customer_messages = [t for c, t, _ in fake_telegram.sent[before:] if "We've" in t or "خُصم" in t
                         or "billing case" in t or "فتحنا" in t]
    assert len(customer_messages) == 4 + 5  # apologies + automation notices (Mariam has no chat)
    assert {c for c, _, _ in fake_telegram.sent} == {A}  # nobody else was ever messaged

    bot.handle(press(A, button(markup, "u:")))
    assert "Rolled back" in fake_telegram.texts_to(A)[-1]
    assert len(fake_telegram.deleted) == 9  # every customer message recalled
    assert services.sessions.crm(services.sessions.by_chat(A)).wallet_balance("c_001") == 2_000


def test_visitors_cannot_touch_each_other(bot, services, fake_telegram) -> None:
    approve = to_approvable_card(bot, fake_telegram, A)
    bot.handle(message(B, "/start"))
    bot.handle(press(B, approve))  # B presses A's button
    assert "belongs to someone else" in fake_telegram.texts_to(B)[-1]

    bot.handle(press(A, approve))
    b_crm = services.sessions.crm(services.sessions.by_chat(B))
    assert b_crm.wallet_balance("c_001") == 2_000  # B's copy untouched by A's run


def test_an_older_card_cannot_release_the_newer_plan(bot, fake_telegram) -> None:
    bot.handle(message(A, "/start"))
    bot.handle(press(A, "ex"))
    _, first = last_card(fake_telegram, A)
    old_leave_out = button(first, "x:")
    bot.handle(press(A, old_leave_out))  # the plan changes; the first card is now stale
    bot.handle(press(A, old_leave_out))
    assert fake_telegram.texts_to(A)[-1] == STALE


def test_drift_lab_refuses_and_shows_the_new_simulation(bot, fake_telegram) -> None:
    approve = to_approvable_card(bot, fake_telegram, A)
    _, card = last_card(fake_telegram, A)
    bot.handle(press(A, button(card, "fd:")))
    texts = fake_telegram.texts_to(A)
    assert any("The data changed after you approved" in t for t in texts)
    assert "partly_credited" in texts[-1]  # the fresh card shows the new blocker
    assert approve  # the original approve button was never used


def test_blind_lab_is_caught_by_the_canary_and_recalled(bot, fake_telegram) -> None:
    bot.handle(message(A, "/start"))
    bot.handle(press(A, "ex"))
    _, card = last_card(fake_telegram, A)
    bot.handle(press(A, button(card, "x:")))
    _, card = last_card(fake_telegram, A)
    bot.handle(press(A, button(card, "y:")))
    _, card = last_card(fake_telegram, A)
    bot.handle(press(A, button(card, "fb:")))  # simulate again without seeing automations
    _, blind_card = last_card(fake_telegram, A)
    bot.handle(press(A, button(blind_card, "a:")))
    final = fake_telegram.texts_to(A)[-1]
    assert "Stopped by the safety net" in final and "unpredicted" in final
    assert fake_telegram.deleted  # what went out was recalled


def test_group_chats_are_ignored(bot, fake_telegram) -> None:
    bot.handle(message(A, "/start", kind="group"))
    assert fake_telegram.sent == []


def test_past_the_daily_quota_runs_use_the_example_plan_instead_of_refusing(bot, services, fake_telegram) -> None:
    """Found live: the owner hit the limit while testing and was locked out. Nobody should be."""
    services.sessions.daily_runs = 1
    bot.handle(message(A, "/start"))
    bot.handle(message(A, "credit back the doubles"))
    model_calls = len(services.router._transport.calls)
    bot.handle(message(A, "credit back the doubles again"))

    texts = fake_telegram.texts_to(A)
    assert any("used today's 1 model-planned requests" in t for t in texts)
    card, _ = last_card(fake_telegram, A)
    assert "Planner: example plan" in card  # a full simulation card, not a refusal
    assert services.router._transport.calls[model_calls:].count("groq:planner-model") == 0


def test_web_past_the_quota_still_simulates(services) -> None:
    services.sessions.daily_runs = 0
    web = WebActions(services)
    view = web.simulate(web.session(None).id, "credit back the doubles", blind=False)
    assert "blocker" in view.review_html and "example plan" in view.notice


def test_forget_deletes_the_sandbox_and_runs(bot, services) -> None:
    bot.handle(message(A, "/start"))
    bot.handle(press(A, "ex"))
    sandbox = services.sessions.by_chat(A).sandbox
    bot.handle(message(A, "/forget"))
    assert services.sessions.by_chat(A) is None
    with services.engine.connect() as conn:
        assert conn.execute(contacts.select().where(contacts.c.sandbox == sandbox)).first() is None
        assert conn.execute(wallet_ledger.select().where(wallet_ledger.c.sandbox == sandbox)).first() is None


def test_spent_model_budget_falls_back_to_the_example_plan(bot, services, fake_telegram) -> None:
    services.router.meter.daily_limit = 0
    bot.handle(message(A, "/start"))
    bot.handle(message(A, "credit back the doubles"))
    text, _ = last_card(fake_telegram, A)
    assert "Planner: example plan: no model could answer (BudgetExceeded)" in text


def test_long_polling_passes_telegrams_own_timeout(fake_telegram) -> None:
    """Found live: getUpdates' `timeout` parameter clashed with the client's HTTP timeout."""
    assert fake_telegram.client().get_updates(offset=7, wait=1) == []
    assert fake_telegram.calls[-1] == "getUpdates"


def test_a_dropped_connection_is_retried_because_nothing_was_sent(fake_telegram) -> None:
    """Found live: three bot replies were lost to ConnectError on a flaky network."""
    fake_telegram.connect_errors_next = 2
    fake_telegram.client().send_message("42", "hello")
    assert fake_telegram.texts_to("42") == ["hello"]


def test_a_429_from_telegram_is_waited_out_not_lost(fake_telegram) -> None:
    client = fake_telegram.client()
    fake_telegram.rate_limit_next = 1
    client.send_message("42", "hello")
    assert fake_telegram.texts_to("42") == ["hello"] and 1.0 in fake_telegram.slept


# ---------- web, and the bridge to the phone ----------

def test_web_link_code_connects_the_browser_to_the_phone(bot, services, fake_telegram) -> None:
    web = WebActions(services)
    session = web.session(None)
    card, code = web.telegram(session, None)
    assert f"https://t.me/FakeSbaBot?start={code}" in card and "<svg" in card

    bot.handle(message(C, f"/start {code}"))

    linked = services.sessions.get(session.id)
    assert linked.telegram_chat_id == C
    assert "Linked to your web demo" in fake_telegram.texts_to(C)[-1]
    assert "Connected as Judy" in web.telegram(linked, None)[0]
    assert services.sessions.crm(linked).contact("c_001")["telegram_chat_id"] == C


def test_web_run_without_a_phone_holds_messages_and_completes(services, fake_telegram) -> None:
    web = WebActions(services)
    sid = web.session(None).id
    view = web.simulate(sid, "", blind=False)
    assert "blocker" in view.review_html and not view.can_approve
    view = web.leave_out(sid, view.run_id, view.shown_hash)
    view = web.accept(sid, view.run_id, view.shown_hash, "Billing wants tickets")
    assert view.can_approve and "held (no phone linked)" in view.review_html

    done = web.approve(sid, view.run_id, view.shown_hash, "Judge", drift=False)

    assert "Done:" in done.result_html and done.can_roll_back
    assert fake_telegram.sent == []  # nothing left the machine: no phone is linked
    back = web.roll_back(sid, done.run_id)
    assert "Rolled back" in back.result_html


def test_tweaks_reuse_the_critic_instead_of_calling_it_again(services) -> None:
    """Found live: every tweak re-ran the critic, and one click took 26 seconds."""
    web = WebActions(services)
    sid = web.session(None).id
    view = web.simulate(sid, "", blind=False)
    calls = list(services.router._transport.calls)
    tweaked = web.leave_out(sid, view.run_id, view.shown_hash)
    assert services.router._transport.calls == calls  # no new model call
    assert "inbox will get a burst of questions" in tweaked.review_html  # the critic's note is still shown


def test_web_refuses_a_stale_screen(services) -> None:
    web = WebActions(services)
    sid = web.session(None).id
    view = web.simulate(sid, "", blind=False)
    newer = web.leave_out(sid, view.run_id, view.shown_hash)
    stale = web.leave_out(sid, view.run_id, view.shown_hash)
    assert newer.shown_hash != view.shown_hash and "out of date" in stale.notice


# ---------- webhook ----------

def test_webhook_checks_the_secret_and_handles_the_update(services, fake_telegram, monkeypatch) -> None:
    monkeypatch.setenv("SBA_SKIP_STARTUP", "1")
    monkeypatch.setattr("sba.services.get_services", lambda: services)
    from sba.main import app

    client = TestClient(app)
    assert client.post("/telegram/webhook", json=message(A, "/start")).status_code == 403
    bad = {"X-Telegram-Bot-Api-Secret-Token": "nope"}
    assert client.post("/telegram/webhook", json=message(A, "/start"), headers=bad).status_code == 403
    good = {"X-Telegram-Bot-Api-Secret-Token": "s3cret"}
    assert client.post("/telegram/webhook", json=message(A, "/start"), headers=good).json() == {"ok": True}
    assert fake_telegram.texts_to(A)  # the background task ran and welcomed the visitor
