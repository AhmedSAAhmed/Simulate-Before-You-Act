# src - the code that runs the pipeline

One package, `sba`. Each stage in [../CONTEXT.md](../CONTEXT.md) maps to one module; adapters hold everything that touches a real system.

| Module | Holds | Stage |
|---|---|---|
| `sba/domain/` | models, hashing, money, policy | all |
| `sba/crm/` | the CRM itself (the real system): tables, service, automations, demo seed | — |
| `sba/adapters/` | `crm.py` (credits, labels, deletions) and `telegram.py` (messages); each has `simulate`, `execute`, `compensate`, `observe` | 02, 04, 05 |
| `sba/agents/` | `simulator.py` now; planner, critic, executor, verifier next | 01–05 |
| `sba/llm/` | provider router (Groq, OpenRouter, Gemini), budget cap | 01–03 |
| `sba/store/` | run ledger, approvals, journal | 03–05 |
| `sba/ui/` | Gradio app, Navy-style theme, diff rendering | 03 |
| `sba/main.py` | FastAPI app: UI mount, webhooks, `/healthz` | — |

Rules: numbers come from adapters, never from a model. Adapters never write during `read` or `simulate`. Every adapter has a test in `tests/`.
