# 05_verify - compare what happened with what was predicted

One job: re-read the real systems after each batch, diff observed effects against the simulation, and halt and roll back when they diverge.

Code only (`src/sba/agents/verifier.py`). It also consumes webhook events (Stripe `charge.refunded`, Telegram updates) as evidence.

## Inputs
- Working (this run): `runs/{run-id}/02_simulate/output/simulation.json`
- Working (this run): `runs/{run-id}/04_execute/output/journal.json`
- Reference (every run): `../../_shared/risk-policy.md`
- Reference (every run): `../../_shared/action-catalog.md`

Do NOT load: model prompts, other runs.

## Process
1. Re-read every touched record, plus anything linked to it (tickets, automations, messages).
2. Diff observed against predicted, per record and per effect class.
3. Invariants: refunds per customer ≤ the duplicate amount; nobody refunded twice; only predicted effect classes appear.
4. On divergence: stop remaining items, restore snapshots of `reversible` steps, recall `recallable` ones, and draft compensations for the rest. Compensations need a new approval.
5. Write `report.md` from `_templates/run-report.md`: predicted vs actual, what was rolled back, and the new simulator rule the gap suggests.

## Outputs
- `verification.json` -> `runs/{run-id}/05_verify/output/`
- `report.md` -> `runs/{run-id}/05_verify/output/`

## Check
Run `python -m sba.checks verify {run-id}`: `pass` when every invariant holds and the outcome is `match`; otherwise `fail: <divergence>`, with the rollback outcome recorded.
