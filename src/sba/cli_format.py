"""Plain-text views of a simulation and an execution, for the CLI scripts."""

from __future__ import annotations

from sba.agents.executor import ExecutionResult
from sba.domain.models import ActionPlan, Simulation
from sba.domain.money import fmt


def describe_simulation(plan: ActionPlan, sim: Simulation, *, effects: bool = True) -> str:
    t = sim.totals
    cur = t.get("currency", "BHD")
    out = [
        f"Tier {sim.tier.value} | plan {sim.plan_hash[:12]} | state {sim.state_fingerprint[:12]}",
        f"Credits {t.get('credits', 0)} totalling {fmt(t.get('credit_total_minor', 0), cur)} | "
        f"messages {t.get('messages', 0)} | label changes {t.get('label_changes', 0)} | "
        f"deletions {t.get('deletions', 0)}",
        f"\nBlockers ({len(sim.blockers)}): Approve stays disabled until each is resolved",
        *[f"  - [{b.rule}{', hard' if b.hard else ''}] {b.detail}" for b in sim.blockers],
        f"\nSide effects ({len(sim.side_effects)}):",
        *[f"  - ({s.source}, {s.likelihood}) {s.description}" for s in sim.side_effects],
        f"\nNotes ({len(sim.notes)}):",
        *[f"  - {n}" for n in sim.notes],
    ]
    if effects:
        out.append("\nBefore -> after:")
        for e in sim.effects:
            out.append(f"  {e.action_index}  {e.subject:<32} {_change(plan, e)}")
        out.append("\nRollback:")
        out.extend(f"  {r}" for r in sim.rollback)
    return "\n".join(out)


def describe_execution(result: ExecutionResult) -> str:
    j, v = result.journal, result.verification
    counts: dict[str, int] = {}
    for e in j.entries:
        key = f"{e.phase}:{e.status}"
        counts[key] = counts.get(key, 0) + 1
    lines = [f"Journal: {j.outcome} ({', '.join(f'{k} x{n}' for k, n in sorted(counts.items())) or 'no writes'})",
             f"Verify:  {v.outcome}. {v.summary}"]
    lines += [f"  unpredicted {k}: {n}" for k, n in v.unpredicted.items()]
    lines += [f"  invariant {c.name}: {'held' if c.held else 'BROKEN ' + c.detail}" for c in v.invariants]
    lines += [f"  rollback {u.item_id}: {u.status} {u.detail}".rstrip() for u in v.rollback]
    lines += [f"  diff {d.record_id} {d.field}" for d in v.diffs[:10]]
    return "\n".join(lines)


def _change(plan: ActionPlan, e) -> str:
    kind = plan.actions[e.action_index].kind.value
    if kind == "issue_credit":
        c = e.after["currency"]
        return (f"wallet {fmt(e.before['wallet_balance'], c)} -> {fmt(e.after['wallet_balance'], c)} "
                f"(+{fmt(e.after['credit'], c)})")
    if kind == "send_message":
        return f"message via {e.after['route']} ({e.after['language']})"
    if kind == "update_contact_attributes":
        return f"labels {e.before['labels']} -> {e.after['labels']}"
    return f"{e.before['status']} -> {e.after['status']}"
