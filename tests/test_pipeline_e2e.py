"""Phase 2 exit check: intent -> simulate -> approve -> execute -> verify, with a journal.

Models and Telegram are faked; the CRM is a real (in-memory SQLite) database.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from sba.crm.seed import CURRENCY, DEMO_REQUEST, demo_plan
from sba.llm.router import LLMRouter, UsageMeter, parse_chain
from sba.pipeline import Pipeline, StageFailed, resolve_blockers
from sba.store.approvals import ApprovalError
from sba.store.runs import RunStore
from tests.conftest import CRITIC_NOTE, NOW, FakeModels, plan_json

ACCEPT = "Billing wants a ticket for every affected customer"


def _pipeline(crm, adapters, tmp_path, models: FakeModels) -> Pipeline:
    router = LLMRouter({"groq": "k", "gemini": "k"},
                       chains={"planner": parse_chain("groq:planner-model"),
                               "critic": parse_chain("groq:planner-model,gemini:critic-model")},
                       meter=UsageMeter(10**6), transport=models)
    return Pipeline(crm, adapters, RunStore(tmp_path, crm.engine), router, clock=lambda: NOW)


def _approved(pipe):
    plan = pipe.plan(DEMO_REQUEST)
    sim = pipe.simulate(plan)
    assert len(sim.blockers) == 6
    plan = resolve_blockers(plan, sim, accept_rules_reason=ACCEPT)
    sim = pipe.simulate(plan)
    assert sim.blockers == ()
    return plan, sim, pipe.decide(plan, sim, approver="Ahmed", verdict="approve")


def test_full_run_executes_everything_and_matches(crm, adapters, fake_telegram, tmp_path) -> None:
    models = FakeModels()
    pipe = _pipeline(crm, adapters, tmp_path, models)
    plan, sim, decision = _approved(pipe)

    result = pipe.execute(plan, sim, decision)

    assert result.verification.outcome == "match"
    assert result.journal.outcome == "completed"
    # resolve_blockers leaves Nadia out (an override needs a person's reason): 6 credits, 4 messages, 6 labels, 3 deletes
    assert [e.status for e in result.journal.entries] == ["done"] * 19
    assert {e.phase for e in result.journal.entries} == {"canary", "batch"}
    assert all(c.held for c in result.verification.invariants)
    assert crm.wallet_balance("c_001") == 14_500
    # 4 apologies + 5 automation notices: Mariam has no Telegram, so her notice is recorded, not delivered.
    # (Khalid opted out of messages, yet the CRM's own automation still notifies him: a real gap.)
    assert len(fake_telegram.sent) == 4 + 5
    assert len(crm.notifications_for_run(plan.run_id)) == 6
    assert pipe.store.status(plan.run_id) == {s: "pass" for s in
                                              ("01_intent", "02_simulate", "03_present", "04_execute", "05_verify")}
    assert (tmp_path / plan.run_id / "05_verify" / "output" / "report.md").is_file()
    assert any(s.source == "critic" and s.description == CRITIC_NOTE for s in sim.side_effects)
    assert "gemini:critic-model" in models.calls  # the critic avoided the planner's provider


def test_drift_after_approval_writes_nothing(crm, adapters, fake_telegram, tmp_path) -> None:
    pipe = _pipeline(crm, adapters, tmp_path, FakeModels())
    plan, sim, decision = _approved(pipe)

    def reem_credits_by_hand() -> None:
        crm.add_ledger_entry(contact_id="c_001", amount_minor=2_500, currency=CURRENCY, kind="credit",
                             actor="human:reem", charge_id="ch_d01")

    pipe.clock = lambda: NOW + timedelta(minutes=2)  # execution happens a little later than approval
    result = pipe.execute(plan, sim, decision, before_writes=reem_credits_by_hand)

    assert result.verification.outcome == "drift"
    assert crm.ledger_for_run(plan.run_id) == [] and fake_telegram.sent == []
    # Only what Reem's credit really changed: her charge, and c_001's message and label (not the purge clock).
    assert {d.record_id for d in result.verification.diffs} == {"ch_d01", "c_001"}
    assert any(d.field == "blocker" and "already credited" in str(d.observed) for d in result.verification.diffs)
    assert ("ch_d01", "partly_credited") in {(b.record_id, b.rule) for b in result.fresh.blockers}
    assert pipe.store.status(plan.run_id)["04_execute"].startswith("fail: drift")


def test_blind_simulation_is_caught_by_the_canary_and_rolled_back(crm, adapters, fake_telegram, tmp_path) -> None:
    """The failure test: the simulator misses the automation; the safety net catches it."""
    pipe = _pipeline(crm, adapters, tmp_path, FakeModels())
    plan = pipe.plan(DEMO_REQUEST)
    sim = pipe.simulate(plan, blind_spots={"automations"})
    plan = resolve_blockers(plan, sim)  # no automation blocker appears, so nothing to accept
    sim = pipe.simulate(plan, blind_spots={"automations"})
    assert sim.blockers == () and not [s for s in sim.side_effects if s.expected]
    decision = pipe.decide(plan, sim, approver="Ahmed", verdict="approve")

    result = pipe.execute(plan, sim, decision, blind_spots={"automations"})

    v = result.verification
    assert v.outcome == "rolled_back"
    assert v.unpredicted == {"tickets_opened": 1, "notices_sent": 1}
    assert "canary for action 2" in v.summary
    assert crm.wallet_balance("c_001") == 2_000 and crm.wallet_balance("c_006") == 500  # credits reversed
    assert crm.contact("c_001")["labels"] == []
    assert all(t["status"] == "closed" for t in crm.tickets_for_run(plan.run_id))
    assert len(fake_telegram.deleted) == len(fake_telegram.sent) == 4 + 1  # apologies and the stray notice
    report = (tmp_path / plan.run_id / "05_verify" / "output" / "report.md").read_text(encoding="utf-8")
    assert "1 ticket opened" in report and "automation rules" in report


def test_expired_approval_is_refused(crm, adapters, fake_telegram, tmp_path) -> None:
    pipe = _pipeline(crm, adapters, tmp_path, FakeModels())
    plan, sim, decision = _approved(pipe)
    late = decision.model_copy(update={"expires_at": NOW - timedelta(seconds=1)})

    result = pipe.execute(plan, sim, late)

    assert result.verification.outcome == "refused" and "expired" in result.verification.summary
    assert fake_telegram.sent == [] and crm.ledger_for_run(plan.run_id) == []


def test_approve_is_impossible_while_blockers_remain(crm, adapters, tmp_path) -> None:
    pipe = _pipeline(crm, adapters, tmp_path, FakeModels())
    plan = pipe.plan(DEMO_REQUEST)
    sim = pipe.simulate(plan)
    with pytest.raises(ApprovalError, match="blocker"):
        pipe.decide(plan, sim, approver="Ahmed", verdict="approve")


def test_planner_gets_one_retry_with_its_errors(crm, adapters, tmp_path) -> None:
    bad = json.dumps({"actions": [{"kind": "issue_credit", "selector": {"everyone": True}}]})
    models = FakeModels(planner_replies=[bad, plan_json()])
    plan = _pipeline(crm, adapters, tmp_path, models).plan(DEMO_REQUEST)
    assert len(plan.actions) == 4 and models.calls.count("groq:planner-model") == 2


def test_planner_that_never_fits_stops_the_run_at_01(crm, adapters, tmp_path) -> None:
    bad = json.dumps({"actions": [{"kind": "wire_money", "selector": {}}]})
    pipe = _pipeline(crm, adapters, tmp_path, FakeModels(planner_replies=[bad]))
    with pytest.raises(StageFailed) as err:
        pipe.plan("send everyone 1000")
    assert err.value.stage == "01_intent"


def test_critic_failure_is_visible_not_silent(crm, adapters, tmp_path) -> None:
    pipe = _pipeline(crm, adapters, tmp_path, FakeModels(critic_fails=True))
    sim = pipe.simulate(pipe.plan(DEMO_REQUEST))
    assert any(s.source == "critic" and "unavailable" in s.description for s in sim.side_effects)
