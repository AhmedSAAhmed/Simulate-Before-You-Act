"""Set the bot's public profile: what strangers see before pressing Start, and its command menu.

Usage (from the repo root): python scripts/configure_bot.py [--webhook https://your-app.onrender.com]
--webhook also registers the Telegram webhook with the same secret the app checks; the deployed app does
this itself on every start, so it's only needed after a local `python -m sba.bot --poll` removed it.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sba.config import settings  # noqa: E402

DESCRIPTION = (
    "A DOO-style ops agent that simulates every change before it makes it.\n\n"
    "You get your own copy of a small CRM where 9 customers were charged twice. Ask it to fix things in "
    "plain words: it shows what would change, who is affected and how to undo it, and runs only what you "
    "approve. Its messages go to you and nobody else. Your data is deleted after 7 days."
)
SHORT = "Simulates every change before it acts. Try a real approve, execute, roll back cycle."
COMMANDS = [
    {"command": "demo", "description": "Run the example request"},
    {"command": "reset", "description": "Fresh copy of the demo data"},
    {"command": "forget", "description": "Delete your data and chat id"},
    {"command": "help", "description": "What you can ask"},
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--webhook", metavar="BASE_URL")
    args = parser.parse_args()
    token = settings.telegram_bot_token
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set")
        return 1
    api = f"https://api.telegram.org/bot{token}/"

    def call(method: str, **params) -> None:
        reply = httpx.post(api + method, json=params, timeout=30).json()
        print(f"{method:<22} {'ok' if reply.get('ok') else 'FAILED: ' + str(reply.get('description'))}")

    call("setMyDescription", description=DESCRIPTION)
    call("setMyShortDescription", short_description=SHORT)
    call("setMyCommands", commands=COMMANDS)
    if args.webhook:
        secret = hashlib.sha256(f"sba-webhook:{token}".encode()).hexdigest()[:48]  # as in sba.services
        call("setWebhook", url=args.webhook.rstrip("/") + "/telegram/webhook", secret_token=secret,
             allowed_updates=["message", "callback_query"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
