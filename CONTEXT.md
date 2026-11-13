# Pipeline: intent → simulate → present → execute → verify

Every run passes through five stages in order. Each stage reads exact inputs, writes one output, and ends at a check. A stage whose check fails stops the run; nothing downstream runs.

| Stage | Job | Output (in `runs/{run-id}/`) | Check |
|---|---|---|---|
| [01_intent](stages/01_intent/CONTEXT.md) | request → typed action plan | `01_intent/output/plan.json` | schema + hard limits (script) |
| [02_simulate](stages/02_simulate/CONTEXT.md) | plan + live state → predicted effects | `02_simulate/output/simulation.json` | no unresolved blockers (script) |
| [03_present](stages/03_present/CONTEXT.md) | simulation → decision | `03_present/output/decision.json` | a person approves, tweaks or rejects |
| [04_execute](stages/04_execute/CONTEXT.md) | approved plan → journaled writes | `04_execute/output/journal.json` | binding, drift and canary checks (script) |
| [05_verify](stages/05_verify/CONTEXT.md) | predicted vs actual | `05_verify/output/verification.json` | invariants hold, else rollback (script) |

A tweak in 03 sends the run back to 02 with the edited plan; that's the only backward edge.

## Run folder layout

```
runs/{run-id}/
├─ 00_request.md              the operator's words, verbatim
├─ 01_intent/output/plan.json      + check.md
├─ 02_simulate/output/simulation.json + check.md
├─ 03_present/output/decision.json   + check.md
├─ 04_execute/output/journal.json    + check.md
└─ 05_verify/output/verification.json + report.md + check.md
```

`check.md` is written by the stage's check. Its first line is `pass` or `fail: <why>`. Status is what exists on disk (mirrored to the database on the hosted demo).

## Factory (read by stages, never written by a run)

- [_shared/action-catalog.md](_shared/action-catalog.md): actions, reversibility, rollback
- [_shared/risk-policy.md](_shared/risk-policy.md): tiers, blockers, limits
- [_shared/doo-voice.md](_shared/doo-voice.md): how customer messages sound
- [_meta/schema.md](_meta/schema.md): shapes of every output above
