# src - the code that runs the pipeline

One package, `sba`. Each stage in [../CONTEXT.md](../CONTEXT.md) maps to one module; adapters hold everything that touches a real system.

| Module | Holds | Stage |
|---|---|---|
| `sba/domain/` | models, hashing, money, policy | all |
| `sba/crm/` | the CRM itself (the real system): tables, service, automations, demo seed | — |
| `sba/adapters/` | `crm.py` (credits, labels, deletions) and `telegram.py` (messages); each has `simulate`, `execute`, `compensate`, `observe` | 02, 04, 05 |
| `sba/agents/` | `planner.py` (01), `simulator.py` + `critic.py` (02), `executor.py` (04), `verifier.py` (05); `contracts.py` loads the stage `CONTEXT.md` files as prompts | 01–05 |
| `sba/llm/` | provider router (Groq, Gemini, OpenRouter) with fallback and a daily token budget | 01–02 |
| `sba/store/` | run folders mirrored to the database (`runs.py`), hash-bound approvals (`approvals.py`) | 03–05 |
| `sba/pipeline.py`, `sba/checks.py` | one run through all stages; each stage's `## Check` as code | 01–05 |
| `sba/ui/` | Gradio app, Navy-style theme, diff rendering | 03 |
| `sba/main.py` | FastAPI app: UI mount, webhooks, `/healthz` | — |

Rules: numbers come from adapters, never from a model. Adapters never write during `read` or `simulate`. Every adapter has a test in `tests/`.
