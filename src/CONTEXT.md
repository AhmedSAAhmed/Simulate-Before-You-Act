# src - the code that runs the pipeline

One package, `sba`. Each stage in [../CONTEXT.md](../CONTEXT.md) maps to one module; adapters hold everything that touches a real system.

| Module | Holds | Stage |
|---|---|---|
| `sba/domain/` | models, hashing, policy | all |
| `sba/adapters/` | Stripe, Telegram, CRM database; each has `read`, `simulate`, `execute`, `verify`, `compensate` | 02, 04, 05 |
| `sba/agents/` | planner, simulator, critic, executor, verifier | 01–05 |
| `sba/llm/` | provider router (Groq, OpenRouter, Gemini), budget cap | 01–03 |
| `sba/store/` | run ledger, approvals, journal | 03–05 |
| `sba/ui/` | Gradio app, Navy-style theme, diff rendering | 03 |
| `sba/main.py` | FastAPI app: UI mount, webhooks, `/healthz` | — |

Rules: numbers come from adapters, never from a model. Adapters never write during `read` or `simulate`. Every adapter has a test in `tests/`.
