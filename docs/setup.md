# Setup: the fastest path to real systems (about 15 minutes)

You create the accounts and paste keys into `.env`; nothing here needs a credit card. After each step, run `python scripts/check_setup.py`. It makes read-only calls, never prints a key, and refuses Stripe live keys.

Order matters only for Render, which comes last.

| Step | Time | Why this one |
|---|---|---|
| 1. Telegram bot | 3 min | the mass-message system; free, instant, and `deleteMessage` gives a real recall |
| 2. Stripe test mode | 4 min | the money system; a real API with no real money and no business verification |
| 3. Neon Postgres | 3 min | the CRM and ledger; free with no expiry (Render's free Postgres is deleted after 30 days) |
| 4. LLM keys | 0 min | already in your `.env` (Groq, OpenRouter, Gemini) |
| 5. Render | 5 min | the live demo; do this once the first push is on GitHub |

## 1. Telegram bot

1. In Telegram, open **@BotFather** and send `/newbot`.
2. Give it a name (for example *SBA Demo*) and a username ending in `bot`.
3. Copy the token it replies with into `.env` as `TELEGRAM_BOT_TOKEN=`.
4. Open your new bot and press **Start**. You become demo customer #1, and you'll receive the real messages.
5. Run `python scripts/check_setup.py`. It prints your chat id; paste it into `.env` as `TELEGRAM_DEMO_CHAT_ID=`.

## 2. Stripe test mode

1. Register at `dashboard.stripe.com/register` with your email. Skip the business details; test mode works without them.
2. Make sure the dashboard is in **Test mode** (or a **Sandbox**).
3. Go to **Developers → API keys**, reveal the **Secret key**, which starts with `sk_test_`.
4. Paste it into `.env` as `STRIPE_SECRET_KEY=`. Never paste a key that starts with `sk_live_`; the app refuses it.

## 3. Neon Postgres (optional until deploy)

The app uses a local SQLite file until `DATABASE_URL` is set, so you can skip this step for local work.

1. Sign up at `neon.tech` with your GitHub account.
2. Create a project. Pick the **Frankfurt** region (the same as the Render service, and closest to the Gulf).
3. Copy the **pooled** connection string into `.env` as `DATABASE_URL=`.

## 4. LLM keys

`GROQ_API_KEY`, `OPENROUTER_API_KEY` and `GEMINI_API_KEY` are already in `.env`. One working key is enough to start; two from different providers are needed for the critic.

## 5. Render (after the first push)

1. Sign in at `render.com` with GitHub and allow access to `Simulate-Before-You-Act`.
2. Choose **New → Blueprint** and pick the repo. Render reads `render.yaml`.
3. Fill in the secret values it asks for, copied from your `.env`.
4. Deploy. The first build takes about 5 minutes; `/healthz` should return `{"status": "ok"}`.

The free service sleeps after 15 idle minutes and takes about a minute to wake.

## Local run

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest
.venv/Scripts/python -m sba
```

Then open `http://localhost:7860`. On macOS or Linux, use `.venv/bin/python`.
