# 0002 - Real systems: Telegram, Stripe test mode, Neon Postgres

Date: 2026-11-14 · Status: accepted

## Context
The bonus asks for a real API, not a mock, and at least one high-stakes action must be gated. There's no DOO API access. Hosting is Render's free tier, which has an ephemeral disk, blocks SMTP ports, and deletes free Postgres databases after 30 days (judging runs past the Dec 15 deadline).

## Decision
- **Money:** Stripe test mode. A real API with real refund objects and no real money.
- **Mass message:** Telegram Bot API. It's free and instant, a reviewer can receive the message on their own phone, and `deleteMessage` is a real 48-hour recall.
- **CRM and ledger:** Postgres on Neon's free tier (no expiry), with tables shaped like DOO's `contacts` / `custom_attributes` API. SQLite stands in locally.

## Alternatives considered
- DOO API: not available to us; the CRM mirrors its shapes so that swapping it in is one adapter.
- Email (Resend, SMTP): can't recall a sent email, and Render blocks SMTP ports.
- Render Postgres: expires during judging. Supabase: pauses after a week idle.

## Consequences
- Each system has one adapter with `read`, `simulate`, `execute`, `verify` and `compensate`.
- The public demo must sandbox Stripe test objects and Telegram recipients per visitor, and cap LLM spend.
