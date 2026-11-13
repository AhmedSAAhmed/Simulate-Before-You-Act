# 04_execute - do exactly what was approved

One job: perform the approved writes and nothing else, journaling every item so that any outcome can be traced or rolled back.

Code only (`src/sba/agents/executor.py`); no model runs in this stage.

## Inputs
- Working (this run): `runs/{run-id}/01_intent/output/plan.json`
- Working (this run): `runs/{run-id}/02_simulate/output/simulation.json`
- Working (this run): `runs/{run-id}/03_present/output/decision.json`
- Reference (every run): `../../_shared/risk-policy.md`

Do NOT load: model prompts. Never regenerate message text; send the exact approved text.

## Process
1. Binding: the decision verdict is `approve`, it hasn't expired, and its `plan_hash` equals the hash of `plan.json`. Otherwise stop.
2. Drift: re-read the same state and recompute the fingerprint. If it differs, stop the affected items and send only them back to 02_simulate.
3. Snapshot every record a `reversible` action will touch.
4. Canary: run the first 5% of items (at least 1), then hand over to 05_verify before continuing.
5. Each write carries an idempotency key `{run-id}:{action}:{item}`. A failed or unconfirmed write becomes `unknown` and is never retried automatically.

## Outputs
- `journal.json` -> `runs/{run-id}/04_execute/output/`

## Check
Run `python -m sba.checks execute {run-id}`: binding and fingerprint matched, the canary verified, and there are no `unknown` items. Otherwise `fail` and the run halts.
