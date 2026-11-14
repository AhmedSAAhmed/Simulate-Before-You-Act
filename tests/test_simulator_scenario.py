"""Phase 1 exit check: simulating the seeded scenario reproduces hand-computed numbers exactly.

The arithmetic (amounts in fils; BHD has 3 decimals) is in `src/sba/crm/seed.py`.
"""

from __future__ import annotations

from sba.agents.simulator import has_drifted, simulate
from sba.crm.seed import CURRENCY, demo_plan
from sba.domain import policy
from sba.domain.models import Action, ActionKind, ActionPlan, Tier
from tests.conftest import NOW


def _credits(sim):
    return {e.record_id: (e.before["wallet_balance"], e.after["wallet_balance"], e.after["credit"])
            for e in sim.effects if e.action_index == 0}


def test_unresolved_plan_matches_hand_computed_numbers(adapters) -> None:
    sim = simulate(demo_plan(), adapters, now=NOW)

    assert sim.tier is Tier.HIGH
    assert sim.totals == {"credits": 6, "credit_total_minor": 76_650, "currency": CURRENCY,
                          "messages": 4, "label_changes": 6, "deletions": 3}
    assert _credits(sim) == {
        "ch_d01": (2_000, 14_500, 12_500),
        "ch_d02": (0, 8_750, 8_750),
        "ch_d06": (500, 30_500, 30_000),
        "ch_d07": (500, 10_400, 9_900),
        "ch_d08": (0, 11_000, 11_000),
        "ch_d09": (750, 5_250, 4_500),
    }
    assert {(b.record_id, b.rule) for b in sim.blockers} == {
        ("ch_d04", "partly_credited"),
        ("ch_d05", "disputed"),
        ("c_008", "opted_out"),
        ("c_009", "no_channel"),
        ("rule:r_billing", "automation_match"),
        ("c_103", "open_ticket"),
    }
    assert any(n.startswith("ch_d03") and "automatically" in n for n in sim.notes)
    routes = {e.record_id: e.after["route"] for e in sim.effects if e.action_index == 1}
    assert routes == {"c_001": "own chat", "c_002": "demo inbox", "c_006": "demo inbox", "c_007": "demo inbox"}


def test_messages_are_rendered_in_each_customers_language(adapters) -> None:
    sim = simulate(demo_plan(), adapters, now=NOW)
    texts = {e.record_id: e.after["text"] for e in sim.effects if e.action_index == 1}
    assert texts["c_001"].startswith("Hi Demo Reviewer, ") and "BHD 12.500" in texts["c_001"]
    assert texts["c_002"].startswith("To: Sara Al-Mansouri · demo inbox")
    assert "BHD 8.750" in texts["c_002"] and "محفظتك" in texts["c_002"]


def test_resolving_every_blocker_changes_the_plan_and_the_numbers(adapters) -> None:
    base = simulate(demo_plan(), adapters, now=NOW)
    sim = simulate(demo_plan(resolved=True), adapters, now=NOW)

    assert sim.blockers == ()
    assert sim.plan_hash != base.plan_hash
    assert sim.totals == {"credits": 7, "credit_total_minor": 86_650, "currency": CURRENCY,
                          "messages": 5, "label_changes": 7, "deletions": 3}
    assert _credits(sim)["ch_d04"] == (5_000, 15_000, 10_000)  # Reem's 5.000 is already in the wallet
    assert "ch_d05" not in _credits(sim)
    assert any("Automation 'Billing follow-up' fires for 7 contacts" in s.description for s in sim.side_effects)
    assert any("Reem's 5.000 was a partial fix" in n for n in sim.notes)


def test_blind_spot_hides_the_automation_side_effect(adapters) -> None:
    sim = simulate(demo_plan(resolved=True), adapters, now=NOW, blind_spots={"automations"})
    assert sim.blockers == ()
    assert not any("Automation" in s.description for s in sim.side_effects)


def test_a_manual_credit_after_simulation_is_detected_as_drift(adapters, crm) -> None:
    plan = demo_plan(resolved=True)
    sim = simulate(plan, adapters, now=NOW)
    assert not has_drifted(sim, plan, adapters)

    crm.add_ledger_entry(contact_id="c_001", amount_minor=2_500, currency=CURRENCY, kind="credit",
                         actor="human:reem", charge_id="ch_d01")

    assert has_drifted(sim, plan, adapters)
    again = simulate(plan, adapters, now=NOW)
    assert ("ch_d01", "partly_credited") in {(b.record_id, b.rule) for b in again.blockers}


def test_hard_limit_blocks_the_whole_plan(adapters, monkeypatch) -> None:
    monkeypatch.setattr(policy, "CREDIT_TOTAL_LIMIT_UNITS", 50)
    sim = simulate(demo_plan(resolved=True), adapters, now=NOW)
    limit = [b for b in sim.blockers if b.rule == "credit_total_limit"]
    assert limit and limit[0].hard and limit[0].record_id == "plan"


def test_unsafe_selector_becomes_a_hard_blocker(adapters) -> None:
    plan = ActionPlan(run_id="r", request="credit everyone", actions=(
        Action(kind=ActionKind.ISSUE_CREDIT, selector={"charges_created_on": "2026-11-13", "duplicates_only": False}),
    ))
    sim = simulate(plan, adapters, now=NOW)
    assert [(b.rule, b.hard) for b in sim.blockers] == [("invalid_selector", True)]
    assert sim.effects == ()


def test_a_mistyped_label_blocks_and_suggests_the_real_one(adapters) -> None:
    """Found live: the planner wrote 'spam-import-2026-11-13' and the deletion silently matched nothing."""
    plan = demo_plan()
    typo = plan.actions[3].model_copy(update={"selector": {"label": "spam-import-2026-11-13"}})
    sim = simulate(plan.model_copy(update={"actions": plan.actions[:3] + (typo,)}), adapters, now=NOW)
    empty = [b for b in sim.blockers if b.rule == "empty_selector"]
    assert empty and empty[0].hard and "Did you mean 'spam-import-2026-11' (4 contacts)?" in empty[0].detail


def test_any_action_that_matches_nothing_is_a_blocker(adapters) -> None:
    plan = ActionPlan(run_id="r", request="credit last year's doubles", actions=(
        Action(kind=ActionKind.ISSUE_CREDIT, selector={"charges_created_on": "2025-01-01", "duplicates_only": True}),
    ))
    assert [b.rule for b in simulate(plan, adapters, now=NOW).blockers] == ["empty_selector"]


def test_unreachable_chat_is_a_hard_blocker(adapters, fake_telegram) -> None:
    fake_telegram.blocked.add("111")
    sim = simulate(demo_plan(), adapters, now=NOW)
    assert ("c_001", "unreachable", True) in {(b.record_id, b.rule, b.hard) for b in sim.blockers}


def test_network_trouble_is_not_mistaken_for_a_blocked_chat(adapters, fake_telegram) -> None:
    """Found live: a flaky connection used to report every customer as having blocked the bot."""
    fake_telegram.network_down = True
    sim = simulate(demo_plan(), adapters, now=NOW)
    rules = {b.rule for b in sim.blockers if b.action_index == 1}
    assert "reachability_unknown" in rules and "unreachable" not in rules
    assert fake_telegram.calls.count("getChat") == 4  # two chats, one retry each

    fake_telegram.network_down = False  # not cached: simulating again recovers
    assert "reachability_unknown" not in {b.rule for b in simulate(demo_plan(), adapters, now=NOW).blockers}
