"""Stage 05: compare what happened with what was predicted, and undo what can be undone."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sba.adapters.base import Adapter, ExecResult, idempotency_key
from sba.domain.money import count_phrase
from sba.domain.models import (
    ActionKind,
    ActionPlan,
    Diff,
    Effect,
    InvariantResult,
    JournalEntry,
    Simulation,
)

Done = Sequence[tuple[Effect, ExecResult]]


def record_diffs(done: Done, adapters: Mapping[ActionKind, Adapter], kinds: dict[int, ActionKind]) -> list[Diff]:
    """Per-record check: every field an adapter can observe must equal the predicted value.

    Records are read in one batch per action where the adapter supports it (`observe_many`)."""
    by_action: dict[int, list[Effect]] = {}
    for effect, _ in done:
        by_action.setdefault(effect.action_index, []).append(effect)
    diffs = []
    for index, effects in sorted(by_action.items()):
        adapter = adapters[kinds[index]]
        many = getattr(adapter, "observe_many", None)
        observed = many(effects) if many else {e.record_id: adapter.observe(e) for e in effects}
        for effect in effects:
            for name, value in observed[effect.record_id].items():
                if name in effect.after and effect.after[name] != value:
                    diffs.append(Diff(action_index=effect.action_index, record_id=effect.record_id, field=name,
                                      predicted=effect.after[name], observed=value))
    return diffs


def unpredicted(simulation: Simulation, adapters: Mapping[ActionKind, Adapter], run_id: str) -> dict[str, int]:
    """Effect classes the systems produced beyond what the simulation said they would."""
    expected: dict[str, int] = {}
    for side in simulation.side_effects:
        for name, count in side.expected.items():
            expected[name] = expected.get(name, 0) + count
    observed: dict[str, int] = {}
    for adapter in {id(a): a for a in adapters.values()}.values():
        probe = getattr(adapter, "side_observations", None)
        for name, count in (probe(run_id) if probe else {}).items():
            observed[name] = observed.get(name, 0) + count
    return {name: count - expected.get(name, 0) for name, count in observed.items() if count > expected.get(name, 0)}


def invariants(
    done: Done, adapters: Mapping[ActionKind, Adapter], kinds: dict[int, ActionKind], run_id: str
) -> list[InvariantResult]:
    results: list[InvariantResult] = []
    for adapter in {id(a): a for a in adapters.values()}.values():
        check = getattr(adapter, "invariants", None)
        if check:
            mine = [(e, r) for e, r in done if adapters[kinds[e.action_index]] is adapter]
            results.extend(check([e for e, _ in mine], run_id))
    return results


def rollback(
    done: Done, adapters: Mapping[ActionKind, Adapter], kinds: dict[int, ActionKind], run_id: str
) -> list[JournalEntry]:
    """Compensate every completed item, newest first."""
    entries = []
    for effect, result in reversed(list(done)):
        adapter = adapters[kinds[effect.action_index]]
        try:
            undo = adapter.compensate(effect, result, run_id=run_id)
        except Exception as err:  # noqa: BLE001 - record and keep undoing the rest
            undo = ExecResult("failed", detail=f"{type(err).__name__}: {err}")
        entries.append(JournalEntry(
            action_index=effect.action_index, item_id=effect.record_id, phase="rollback",
            idempotency_key=idempotency_key(run_id, effect, ":rollback"), status=undo.status,
            external_ref=undo.external_ref, detail=undo.detail,
        ))
    return entries


VOLATILE = frozenset({"purge_after"})  # derived from the clock, so it moves without the data moving


def _stable(values: dict) -> dict:
    return {k: v for k, v in values.items() if k not in VOLATILE}


def drift_diffs(approved: Simulation, fresh: Simulation) -> list[Diff]:
    """What changed between the approved simulation and a fresh one over the same plan."""
    old = {(e.action_index, e.record_id): e for e in approved.effects}
    new = {(e.action_index, e.record_id): e for e in fresh.effects}
    diffs = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if a is None or b is None or (a.before, _stable(a.after)) != (b.before, _stable(b.after)):
            diffs.append(Diff(action_index=key[0], record_id=key[1], field="effect",
                              predicted=a.model_dump(mode="json") if a else None,
                              observed=b.model_dump(mode="json") if b else None))
    before_rules = {(b.record_id, b.rule) for b in approved.blockers}
    for blocker in fresh.blockers:
        if (blocker.record_id, blocker.rule) not in before_rules:
            diffs.append(Diff(action_index=blocker.action_index, record_id=blocker.record_id, field="blocker",
                              predicted=None, observed=blocker.detail))
    return diffs


def report_markdown(plan: ActionPlan, simulation: Simulation, outcome: str, summary: str,
                    diffs: Sequence[Diff], extra: dict[str, int], checks: Sequence[InvariantResult],
                    undo: Sequence[JournalEntry]) -> str:
    """`report.md`, following `_templates/run-report.md`."""
    lines = [f"# Run report: {plan.run_id}", "", f"Outcome: {outcome}", "", "## Request", plan.request, "",
             "## Summary", summary, "", "## Predicted vs observed", ""]
    if diffs or extra:
        lines += ["| Item | Field | Predicted | Observed |", "|---|---|---|---|"]
        lines += [f"| {d.record_id} | {d.field} | {_cell(d.predicted)} | {_cell(d.observed)} |" for d in diffs]
        lines += [f"| (system) | {name} | {_expected(simulation, name)} | {_expected(simulation, name) + n} |"
                  for name, n in extra.items()]
    else:
        lines.append("Everything observed matched the prediction.")
    lines += ["", "## Invariants"] + [f"- {c.name}: {'held' if c.held else 'broken: ' + c.detail}" for c in checks]
    if not checks:
        lines.append("- none checked (nothing ran)")
    lines += ["", "## Rollback"] + ([f"- {u.item_id}: {u.status}. {u.detail}".rstrip() for u in undo] or
                                    ["- not needed"])
    lines += ["", "## What the simulator missed",
              (", ".join(count_phrase(n, name) for name, n in extra.items()) or "nothing"),
              "", "## New simulator rule",
              ("Read the CRM's automation rules before predicting label changes (see blind spot 'automations')."
               if extra else "none")]
    return "\n".join(lines) + "\n"


def _expected(simulation: Simulation, name: str) -> int:
    return sum(s.expected.get(name, 0) for s in simulation.side_effects)


def _cell(value: object) -> str:
    text = str(value)
    return (text[:60] + "...") if len(text) > 63 else text
