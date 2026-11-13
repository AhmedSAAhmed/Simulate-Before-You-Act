# Schema: the shape of every run artifact

The Pydantic models in `src/sba/domain/models.py` are the single source of truth; this file names them and their key fields. If the two disagree, the code wins and this file is fixed.

| Artifact | Model | Key fields |
|---|---|---|
| `plan.json` | `ActionPlan` | `run_id`, `request`, `actions[]` (each: `kind`, `selector`, `params`, `reason`) |
| `simulation.json` | `Simulation` | `plan_hash`, `state_fingerprint`, `effects[]`, `side_effects[]`, `blockers[]`, `impacted`, `rollback[]`, `tier`, `totals` |
| `decision.json` | `Decision` | `verdict` (`approve`/`reject`), `plan_hash`, `state_fingerprint`, `approver`, `decided_at`, `expires_at` |
| `journal.json` | `Journal` | `entries[]` (each: `action_index`, `item_id`, `idempotency_key`, `status`, `snapshot_ref`, `external_ref`) |
| `verification.json` | `Verification` | `predicted`, `observed`, `diffs[]`, `invariants[]`, `outcome` (`match`/`halted`/`rolled_back`) |

## Hashing

- `plan_hash` = sha256 of the canonical JSON of `ActionPlan.actions` (sorted keys, no whitespace).
- `state_fingerprint` = sha256 of the sorted `(system, id, field, value)` tuples the simulator read.
- A `Decision` releases execution only when both hashes match the live values at execute time and `expires_at` hasn't passed.

## Item status (journal)

`pending` → `held` → `dispatching` → `done` | `unknown` | `rolled_back`. `unknown` never moves on without a person.
