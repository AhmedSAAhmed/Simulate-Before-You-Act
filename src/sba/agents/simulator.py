"""Stage 02, the effect engine: every number in a simulation comes from here, never from a model."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sba.adapters.base import Adapter, SelectorError, SimContext
from sba.crm.service import utcnow
from sba.domain import policy
from sba.domain.hashing import plan_hash, state_fingerprint
from sba.domain.models import ActionKind, ActionPlan, Blocker, Simulation

# Things the engine can be told not to look at. The Failure Lab uses this to make the
# simulation under-predict on purpose, so the downstream safety nets can be shown working.
BLIND_SPOTS = frozenset({"automations"})


def simulate(
    plan: ActionPlan,
    adapters: Mapping[ActionKind, Adapter],
    *,
    now: datetime | None = None,
    blind_spots: Iterable[str] = (),
) -> Simulation:
    blind = frozenset(blind_spots)
    if blind - BLIND_SPOTS:
        raise ValueError(f"unknown blind spots: {sorted(blind - BLIND_SPOTS)}")
    ctx = SimContext(now=now or utcnow(), blind_spots=blind)
    effects, blockers, side_effects, notes, rollback = [], [], [], [], []
    totals: dict[str, Any] = {}

    for i, action in enumerate(plan.actions):
        adapter = adapters.get(action.kind)
        if adapter is None:
            blockers.append(Blocker(action_index=i, record_id="plan", rule="no_adapter", hard=True,
                                    detail=f"action {i}: no system is connected for {action.kind}"))
            continue
        try:
            result = adapter.simulate(i, action, ctx)
        except SelectorError as err:
            blockers.append(Blocker(action_index=i, record_id="plan", rule="invalid_selector", hard=True,
                                    detail=f"action {i} ({action.kind}): {err}"))
            continue
        ctx.targets[i] = result.targets
        if not (result.effects or result.blockers or result.notes):
            # An action that touches nothing isn't what the operator asked for: make someone look.
            result.blockers.append(Blocker(action_index=i, record_id="plan", rule="empty_selector", hard=True,
                                           detail=f"action {i} ({action.kind}) matched nothing, so it would do "
                                                  f"nothing. Check its selector."))
        effects.extend(result.effects)
        blockers.extend(result.blockers)
        side_effects.extend(result.side_effects)
        notes.extend(result.notes)
        rollback.append(f"{i}. {action.kind}: {result.rollback}")
        _merge(totals, result.totals)

    blockers.extend(policy.limit_blockers(totals))
    kinds = {i: a.kind for i, a in enumerate(plan.actions)}
    return Simulation(
        plan_hash=plan_hash(plan),
        state_fingerprint=state_fingerprint(ctx.reads),
        effects=tuple(effects),
        side_effects=tuple(side_effects),
        blockers=tuple(blockers),
        impacted=tuple(sorted({e.subject for e in effects})),
        rollback=tuple(rollback),
        notes=tuple(notes),
        tier=policy.tier(effects, kinds),
        totals=totals,
    )


def has_drifted(
    simulation: Simulation, plan: ActionPlan, adapters: Mapping[ActionKind, Adapter], *, blind_spots: Iterable[str] = ()
) -> bool:
    """Re-read live state; True when anything the prediction depended on has changed."""
    fresh = simulate(plan, adapters, blind_spots=blind_spots)
    return fresh.state_fingerprint != simulation.state_fingerprint


def _merge(totals: dict[str, Any], part: dict[str, Any]) -> None:
    for key, value in part.items():
        if isinstance(value, int) and not isinstance(value, bool):
            totals[key] = totals.get(key, 0) + value
        else:
            totals.setdefault(key, value)
