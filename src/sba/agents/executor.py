"""Stage 04: perform exactly the approved writes, canary first, journaling every item.

Order of checks (ADR 0001): binding, then drift, then writes. After each canary and each batch
the verifier compares observed with predicted; any surprise halts the run and rolls back.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from sba.adapters.base import Adapter, ExecResult, idempotency_key
from sba.agents import verifier
from sba.agents.simulator import simulate
from sba.domain.models import ActionKind, ActionPlan, Decision, Effect, Journal, JournalEntry, Simulation, Verification
from sba.domain.policy import canary_size
from sba.store.approvals import binding_errors


@dataclass(frozen=True)
class ExecutionResult:
    journal: Journal
    verification: Verification
    fresh: Simulation | None = None  # set on drift: the simulation to review and approve again


def execute_plan(
    plan: ActionPlan,
    simulation: Simulation,
    decision: Decision,
    adapters: Mapping[ActionKind, Adapter],
    *,
    now: datetime,
    blind_spots: Iterable[str] = (),
    before_writes: Callable[[], None] | None = None,
) -> ExecutionResult:
    run_id = plan.run_id
    kinds = {i: a.kind for i, a in enumerate(plan.actions)}

    if errors := binding_errors(decision, plan, simulation, now):
        reason = "; ".join(errors)
        return ExecutionResult(Journal(run_id=run_id, outcome="refused", reason=reason),
                               Verification(outcome="refused", summary=f"Nothing was written: {reason}."))

    if before_writes is not None:  # Failure Lab: someone changes the world after approval
        before_writes()

    fresh = simulate(plan, adapters, now=now, blind_spots=blind_spots)
    if fresh.state_fingerprint != simulation.state_fingerprint:
        diffs = verifier.drift_diffs(simulation, fresh)
        summary = (f"The data changed after approval ({len(diffs)} difference(s)). Nothing was written. "
                   "Review the new simulation and approve it again.")
        return ExecutionResult(Journal(run_id=run_id, outcome="drift", reason=summary),
                               Verification(outcome="drift", summary=summary, diffs=tuple(diffs)), fresh)

    entries: list[JournalEntry] = []
    done: list[tuple[Effect, ExecResult]] = []
    for index, action in enumerate(plan.actions):
        items = [e for e in simulation.effects if e.action_index == index]
        adapter = adapters[action.kind]
        n = canary_size(len(items))
        for phase, batch in (("canary", items[:n]), ("batch", items[n:])):
            for effect in batch:
                result = _run(adapter, effect, run_id)
                entries.append(_entry(effect, phase, result, run_id))
                if result.status != "done":
                    why = f"{effect.subject}: {result.status}. {result.detail}".strip()
                    return _halt(plan, simulation, adapters, kinds, entries, done, f"A write didn't complete ({why})")
                done.append((effect, result))
            if not batch:
                continue
            diffs = verifier.record_diffs(done, adapters, kinds)
            extra = verifier.unpredicted(simulation, adapters, run_id)
            if diffs or extra:
                what = ", ".join(f"{n} unpredicted {k.replace('_', ' ')}" for k, n in extra.items()) or \
                    f"{len(diffs)} record(s) differ from the prediction"
                return _halt(plan, simulation, adapters, kinds, entries, done,
                             f"The {phase} for action {index} ({action.kind}) found {what}", diffs, extra)

    checks = verifier.invariants(done, adapters, kinds, run_id)
    if broken := [c for c in checks if not c.held]:
        return _halt(plan, simulation, adapters, kinds, entries, done,
                     "Invariant broken: " + "; ".join(f"{c.name} ({c.detail})" for c in broken), checks=checks)
    summary = f"All {len(done)} writes ran and matched the prediction."
    return ExecutionResult(Journal(run_id=run_id, outcome="completed", entries=tuple(entries)),
                           Verification(outcome="match", summary=summary, invariants=tuple(checks)))


def _run(adapter: Adapter, effect: Effect, run_id: str) -> ExecResult:
    try:
        return adapter.execute(effect, run_id=run_id)
    except Exception as err:  # noqa: BLE001 - an exception mid-write is an unknown outcome, never a retry
        return ExecResult("unknown", detail=f"{type(err).__name__}: {err}")


def _entry(effect: Effect, phase: str, result: ExecResult, run_id: str) -> JournalEntry:
    return JournalEntry(action_index=effect.action_index, item_id=effect.record_id, phase=phase,
                        idempotency_key=idempotency_key(run_id, effect), status=result.status,
                        external_ref=result.external_ref, snapshot_ref=result.snapshot_ref, detail=result.detail)


def _halt(plan, simulation, adapters, kinds, entries, done, reason, diffs=(), extra=None, checks=None):
    run_id = plan.run_id
    # Invariants describe what the run did, so they're read before the rollback undoes it.
    checks = checks if checks is not None else verifier.invariants(done, adapters, kinds, run_id)
    undo = verifier.rollback(done, adapters, kinds, run_id)
    clean = all(u.status == "rolled_back" for u in undo)
    unknown = any(e.status == "unknown" for e in entries)
    outcome = "rolled_back" if clean and not unknown else "halted"
    tail = ("Everything that ran was rolled back." if outcome == "rolled_back" else
            "Some items need a person: see the rollback entries" + (" and the unknown write." if unknown else "."))
    summary = f"{reason}. The run stopped there. {tail}"
    return ExecutionResult(
        Journal(run_id=run_id, outcome="halted", reason=reason, entries=tuple(entries) + tuple(undo)),
        Verification(outcome=outcome, summary=summary, diffs=tuple(diffs), unpredicted=dict(extra or {}),
                     invariants=tuple(checks), rollback=tuple(undo)),
    )
