# Simulate Before You Act

An agent that thinks through consequences before it changes anything. Every write (a wallet credit, a mass message, a data deletion) is first simulated against the real systems. A person sees the projected effects, side effects, who is affected and the rollback path, and approves, tweaks or rejects it in one step. Execution then runs only the approved plan, against the state it was simulated on, and checks what actually happened against what was predicted.

Built for DOO's Builders League challenge *Simulate Before You Act*.

> Status: Phase 3 done; the Render deploy is next.
> - **Review screen:** the web page shows the before/after diff, blockers, side effects and undo path, and lets you approve, tweak or reject.
> - **Telegram:** anyone can try the same flow from their phone with [@SimulateBeforeYouAct_bot](https://t.me/SimulateBeforeYouAct_bot). Each visitor gets their own sandbox, and the agent can only message them.
>
> See [docs/execution-plan.md](docs/execution-plan.md). Example runs, including both failure tests, are in [runs/_examples/](runs/_examples/).

## Pipeline

`01 intent → 02 simulate → 03 present → 04 execute → 05 verify`. Each stage ends at a check, and a failed check stops the run. Stage contracts are in [stages/](stages/); the entry point for agents is [AGENTS.md](AGENTS.md).

## Real systems

| System | Used for | Mode |
|---|---|---|
| Telegram Bot API | customer messages (mass message) | real bot |
| Postgres CRM (DOO-shaped) | wallet credits (moves money), contact attributes, deletion | Neon, or SQLite locally |
| Groq / OpenRouter / Gemini | planner, critic, narrator | real APIs |

## Quickstart

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env    # then fill in keys: docs/setup.md
.venv/Scripts/python scripts/check_setup.py
.venv/Scripts/python -m pytest
.venv/Scripts/python scripts/seed_demo.py                  # load the double-charge scenario
.venv/Scripts/python scripts/simulate_demo.py --resolved   # see the prediction; writes nothing
.venv/Scripts/python scripts/run_demo.py --resolve --fake-telegram   # plan with a model, simulate, stop before approval
.venv/Scripts/python -m sba    # http://localhost:7860
```

On macOS or Linux use `.venv/bin/python`.

## Deliverables

| Deliverable | Where |
|---|---|
| Live demo | added when deployed |
| Architecture snapshot | `docs/architecture.md` (Phase 6) |
| Failure test | `docs/failure-test.md` (Phase 4) |
| Two-year thesis | `docs/thesis.md` (Phase 6) |
| 90-second walkthrough | added when recorded |
