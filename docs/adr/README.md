# Architecture decision records

One file per decision, numbered in the order made. A superseded record stays and links to its replacement.

| # | Decision | Status |
|---|---|---|
| [0001](0001-approval-binds-to-simulation.md) | An approval binds to a plan hash and a state fingerprint | accepted |
| [0002](0002-real-systems-telegram-stripe-neon.md) | Real systems: Telegram, Stripe test mode, Neon Postgres | amended by 0004 |
| [0003](0003-python-gradio-on-fastapi.md) | One Python process: Gradio mounted on FastAPI | accepted |
| [0004](0004-wallet-credits-instead-of-stripe.md) | Money moves as wallet credits in our own ledger, not Stripe | accepted |
| [0005](0005-public-demo-sandboxes-and-telegram.md) | The public demo: a sandbox per visitor, Telegram as their inbox | accepted |
