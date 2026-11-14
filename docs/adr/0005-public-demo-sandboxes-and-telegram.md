# 0005 - The public demo: a sandbox per visitor, and Telegram as their inbox

Date: 2026-11-14 · Status: accepted

## Context
Anyone with the demo link should be able to try a real run, including from their phone over Telegram. Until now, every run's messages went to the owner's chat, every visitor shared one copy of the data, and nothing stopped one visitor's approval from changing what another was reviewing.

## Decision
- **One sandbox per visitor.** A browser (via an encrypted session in local storage), a Telegram chat, or both once linked, get their own copy of the scenario. Every CRM table already carries a `sandbox` column.
- **The visitor's chat is their demo inbox.** A Telegram bot can only message people who pressed Start, so the agent can't reach a stranger even if a request tries to steer it. Visitors without a linked phone get **held** messages: simulated and journaled, never sent.
- **The web page links to the phone** with a one-time code in the bot's start link (QR code plus button). Pressing Start attaches the chat to that browser's sandbox; both surfaces then drive the same runs.
- **Binding survives the chat.** Every button carries the run id and the plan-hash prefix it was drawn for. A button from an older card is refused, as is a run owned by another visitor.
- **Guardrails:** direct messages only; one run at a time; 10 model-planned requests a day per visitor, after which runs use the example plan instead of being refused; the daily model budget falls back to the example plan instead of failing; Telegram's per-chat pacing and `retry_after` are honoured; data is deleted after 7 days or on `/forget`.
- **Webhook on Render, polling locally.** On boot, the app registers its webhook (`RENDER_EXTERNAL_URL`) with a secret derived from the bot token, which Telegram echoes back in a header; `python -m sba.bot --poll` serves local testing.

## Alternatives considered
- A shared public "demo inbox" channel: anyone could steer the bot into posting their own text there.
- Judge-only access codes: safer against strangers, but an extra step for judges; isolation and limits made it unnecessary.

## Consequences
- The owner's chat is no longer the inbox for the public demo (`TELEGRAM_DEMO_CHAT_ID` is now only for the CLI scripts).
- Local testing against Neon is slow (about 270 ms per round trip from the Gulf to Frankfurt). Simulations were batched from 47 queries to 9, and execution from 188 to 96. On Render, next to Neon, both take well under a second.
- The bot token must be regenerated before the link goes public, since it was shared during development.
