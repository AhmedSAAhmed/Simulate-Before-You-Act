"""Each adapter's execute, compensate and observe against the seeded CRM and a fake Telegram."""

from __future__ import annotations

from sba.agents.simulator import simulate
from sba.crm.seed import CURRENCY, demo_plan
from sba.domain.models import ActionKind
from tests.conftest import DEMO_CHAT, NOW

RUN = "run-test"


def _effects(adapters, index, **kw):
    sim = simulate(demo_plan(resolved=True), adapters, now=NOW, **kw)
    return [e for e in sim.effects if e.action_index == index]


def test_credit_executes_once_and_reverses_while_unspent(adapters, crm) -> None:
    credit = adapters[ActionKind.ISSUE_CREDIT]
    effect = next(e for e in _effects(adapters, 0) if e.record_id == "ch_d01")

    first = credit.execute(effect, run_id=RUN)
    again = credit.execute(effect, run_id=RUN)  # a retry with the same idempotency key
    assert first.status == "done" and first.external_ref == again.external_ref
    assert credit.observe(effect) == {"credited_for_charge": 12_500}
    assert crm.wallet_balance("c_001") == 14_500

    undone = credit.compensate(effect, first, run_id=RUN)
    assert undone.status == "rolled_back"
    assert crm.wallet_balance("c_001") == 2_000


def test_spent_credit_cannot_be_reversed_automatically(adapters, crm) -> None:
    credit = adapters[ActionKind.ISSUE_CREDIT]
    effect = next(e for e in _effects(adapters, 0) if e.record_id == "ch_d06")
    result = credit.execute(effect, run_id=RUN)
    crm.add_ledger_entry(contact_id="c_006", amount_minor=-25_000, currency=CURRENCY, kind="spend", actor="seed")

    undone = credit.compensate(effect, result, run_id=RUN)
    assert undone.status == "needs_recovery"
    assert crm.wallet_balance("c_006") == 5_500  # nothing was taken back


def test_labels_fire_the_automation_and_rollback_cleans_up(adapters, crm) -> None:
    labels = adapters[ActionKind.UPDATE_CONTACT_ATTRIBUTES]
    effect = next(e for e in _effects(adapters, 2) if e.record_id == "c_002")

    result = labels.execute(effect, run_id=RUN)
    assert labels.observe(effect) == {"labels": ["dup-charge-2026-11"]}
    assert [t["status"] for t in crm.tickets_for_run(RUN)] == ["open"]
    assert len(crm.notifications_for_run(RUN)) == 1

    undone = labels.compensate(effect, result, run_id=RUN)
    assert undone.status == "rolled_back"
    assert labels.observe(effect) == {"labels": []}
    assert [t["status"] for t in crm.tickets_for_run(RUN)] == ["closed"]


def test_blind_simulation_misses_what_execution_then_triggers(adapters, crm) -> None:
    """The failure-test setup: predicted no side effect, observed a ticket and a notice."""
    sim = simulate(demo_plan(resolved=True), adapters, now=NOW, blind_spots={"automations"})
    assert not sim.side_effects
    effect = next(e for e in sim.effects if e.action_index == 2)
    adapters[ActionKind.UPDATE_CONTACT_ATTRIBUTES].execute(effect, run_id=RUN)
    assert crm.tickets_for_run(RUN) and crm.notifications_for_run(RUN)


def test_deletion_is_soft_and_undoable(adapters, crm) -> None:
    delete = adapters[ActionKind.DELETE_CONTACTS]
    effect = _effects(adapters, 3)[0]
    assert effect.after["purge_after"] == "2026-11-15T09:00:00+00:00"

    result = delete.execute(effect, run_id=RUN)
    assert delete.observe(effect) == {"status": "soft-deleted"}
    assert effect.record_id not in [c["id"] for c in crm.contacts_with_label("spam-import-2026-11")]

    delete.compensate(effect, result, run_id=RUN)
    assert delete.observe(effect) == {"status": "active"}


def test_message_sends_exact_text_and_recalls(adapters, fake_telegram) -> None:
    message = adapters[ActionKind.SEND_MESSAGE]
    effect = next(e for e in _effects(adapters, 1) if e.record_id == "c_002")

    result = message.execute(effect, run_id=RUN)
    assert result.status == "done"
    chat, text, msg_id = fake_telegram.sent[-1]
    assert chat == DEMO_CHAT and text == effect.after["text"]

    message.compensate(effect, result, run_id=RUN)
    assert fake_telegram.deleted == [(DEMO_CHAT, msg_id)]


def test_template_placeholders_cannot_reach_python_attributes() -> None:
    from sba.adapters.telegram import render

    assert render("{name.__class__} {amount} {name}", name="Sara", amount="BHD 1.000") == \
        "{name.__class__} BHD 1.000 Sara"
