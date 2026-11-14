# Simulate Before You Act: agent entry

A DOO-style ops copilot that simulates every write against real systems (Telegram, and a Postgres CRM with a wallet ledger) and executes only what a person approved, bound to that exact simulation. What leaves this workspace: a deployed demo, a run ledger per action, and the challenge deliverables in `docs/`.

## Where things live

| Folder | What it holds |
|---|---|
| `stages/` | the runtime pipeline, in order; each `CONTEXT.md` is that stage's contract and prompt |
| `_shared/` | factory: action catalog, risk policy, customer voice (stable every run) |
| `_meta/` | schema of plans, simulations, decisions and journals |
| `_templates/` | blank starters: scenarios, run reports |
| `src/sba/` | the Python package that runs the stages ([src/CONTEXT.md](src/CONTEXT.md)) |
| `tests/`, `evals/` | unit/scenario/failure tests; simulator-accuracy evals |
| `runs/` | one folder per run, the product; only `runs/_examples/` is committed |
| `docs/` | plan, setup, architecture, failure test, thesis, ADRs |

## Route by task

| If you are | Go to | Then stop at |
|---|---|---|
| orienting on the pipeline | [CONTEXT.md](CONTEXT.md) | the stage table |
| adding or changing an action | [_shared/action-catalog.md](_shared/action-catalog.md), then `src/sba/adapters/` | its simulator test passing |
| changing what needs approval | [_shared/risk-policy.md](_shared/risk-policy.md) | `pytest tests/` green |
| working on one stage | `stages/NN_*/CONTEXT.md` | that stage's `## Check` |
| changing the UI | `src/sba/ui/` | a cold reviewer approves in under 90s |
| asked for a run's status | `runs/{run-id}/*/check.md` | report what exists |
| setting up accounts or keys | [docs/setup.md](docs/setup.md) | `python scripts/check_setup.py` passes |
| planning work | [docs/execution-plan.md](docs/execution-plan.md) | the current phase's exit check |

## Commands (from the repo root)

- Run: `python -m sba` (serves on `http://localhost:7860`)
- Test: `python -m pytest`
- Check keys: `python scripts/check_setup.py`
- Reset the demo data: `python scripts/seed_demo.py`
- Simulate the demo plan (writes nothing): `python scripts/simulate_demo.py [--resolved] [--blind automations]`
- One full run: `python scripts/run_demo.py --help` (executes only with `--approve NAME`)
- Re-check a stage: `python -m sba.checks <intent|simulate|present|execute|verify> {run-id}`

## The one rule

Nothing is written to a real system unless the approval matches the plan hash and the live state fingerprint it was simulated against. A failed check stops the run.
