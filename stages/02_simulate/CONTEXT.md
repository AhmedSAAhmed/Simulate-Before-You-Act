# 02_simulate - predict effects from live state

One job: resolve the plan's selectors against the real systems with read-only calls, compute every effect in code, and list what could go wrong that the code didn't model.

Two parts. The effect engine (`src/sba/agents/simulator.py`) is code and produces every number. The critic (`src/sba/agents/critic.py`) is a second model, from a different family than the planner. It reads this file as its system prompt and may only add `side_effects` with a likelihood; it can't change numbers.

## Inputs
- Working (this run): `runs/{run-id}/01_intent/output/plan.json`
- Reference (every run): `../../_shared/action-catalog.md`
- Reference (every run): `../../_shared/risk-policy.md`

Do NOT load: the planner's prompt, earlier simulations, records outside the resolved selectors.

## Process
1. If `plan.json` is missing or its check failed, stop.
2. For each action, call its adapter's `read` and then `simulate`. Record every `(system, id, field, value)` read, for the state fingerprint.
3. Compute effects (before → after per record), totals, impacted people, rollback per action, and the tier from `risk-policy.md`.
4. Raise every blocker listed in `risk-policy.md` that applies.
5. Critic: given the plan and the effects, name side effects the effects list doesn't cover. Each needs a reason and a likelihood (`low`/`medium`/`high`).

## Outputs
- `simulation.json` -> `runs/{run-id}/02_simulate/output/`

## Check
Run `python -m sba.checks simulate {run-id}`: `pass` when there are no unresolved blockers; otherwise `fail: <blockers>`, and 03_present shows them for the operator to resolve.
