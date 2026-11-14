"""Stage 02, second opinion: a model from another provider looks for side effects the engine missed.

The critic only adds advisory side effects. It sees counts and the plan, not customer names or
chat ids, and it can't change a number, a blocker or the tier.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sba.agents import contracts
from sba.domain.models import ActionPlan, SideEffect, Simulation
from sba.llm.router import LLMError, LLMRouter

CONTRACT = ("stages/02_simulate/CONTEXT.md", "_shared/action-catalog.md", "_shared/risk-policy.md")
MAX_ITEMS = 5
MAX_CHARS = 300

OUTPUT_SPEC = """\
You are the critic in step 5 of the Process above. Reply with one JSON object and nothing else:
{"side_effects": [{"description": "<one sentence>", "likelihood": "low|medium|high"}]}
- At most 5 items, most important first. An empty list is a fine answer.
- Only effects the engine's list doesn't already cover. Don't restate blockers.
- Don't invent amounts or counts; refer to the numbers given, or none.
"""


@dataclass(frozen=True)
class Critique:
    side_effects: tuple[SideEffect, ...]
    model: str | None
    error: str | None = None


def critique(plan: ActionPlan, simulation: Simulation, router: LLMRouter, *, avoid_provider: str | None) -> Critique:
    system = f"{contracts.load(*CONTRACT)}\n\n===== output format =====\n{OUTPUT_SPEC}"
    user = "Plan and simulation summary (JSON):\n" + json.dumps(summary(plan, simulation), ensure_ascii=False)
    try:
        result = router.complete_json("critic", system=system, user=user, avoid_provider=avoid_provider)
    except LLMError as err:
        note = SideEffect(description="The critic model was unavailable, so this simulation has no second "
                                      "opinion. Review the effects without it.", likelihood="low", source="critic")
        return Critique((note,), None, str(err))
    return Critique(tuple(_parse(result.data)), str(result.model))


def summary(plan: ActionPlan, simulation: Simulation) -> dict[str, Any]:
    """What the critic may see: structure and counts, no personal data."""
    per_action: dict[int, int] = {}
    for e in simulation.effects:
        per_action[e.action_index] = per_action.get(e.action_index, 0) + 1
    blockers: dict[str, int] = {}
    for b in simulation.blockers:
        blockers[b.rule] = blockers.get(b.rule, 0) + 1
    return {
        "request": plan.request,
        "actions": [
            {"index": i, "kind": a.kind.value, "selector": a.selector,
             "params": {k: v for k, v in a.params.items() if k not in ("exclude", "override")},
             "items_affected": per_action.get(i, 0)}
            for i, a in enumerate(plan.actions)
        ],
        "totals": simulation.totals,
        "tier": simulation.tier.value,
        "open_blockers_by_rule": blockers,
        "engine_side_effects": [s.description for s in simulation.side_effects if s.source == "engine"],
        "rollback": list(simulation.rollback),
    }


def _parse(data: dict[str, Any]) -> list[SideEffect]:
    items = data.get("side_effects")
    out: list[SideEffect] = []
    if not isinstance(items, list):
        return out
    for item in items[:MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("description", "")).strip()
        likelihood = str(item.get("likelihood", "")).lower()
        if text and likelihood in ("low", "medium", "high"):
            out.append(SideEffect(description=text[:MAX_CHARS], likelihood=likelihood, source="critic"))
    return out


def with_critique(simulation: Simulation, found: Critique) -> Simulation:
    """Critic output is advisory: it never touches the hashes, blockers or tier."""
    return simulation.model_copy(update={"side_effects": simulation.side_effects + found.side_effects})
