"""Check every key in .env with one read-only call each. Never prints a secret.

Usage (from the repo root): python scripts/check_setup.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OK, FAIL, SKIP = "pass", "FAIL", "skip"
QUOTES = "\"'“”‘’"


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip(QUOTES).strip())


def get_json(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "sba-setup-check", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, {}
    except (urllib.error.URLError, TimeoutError) as err:
        return 0, {"error": str(err)}
    except UnicodeEncodeError:
        return -1, {"error": "value contains non-ASCII characters (a pasted curly quote?)"}


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def check_groq(key: str) -> tuple[str, str]:
    code, _ = get_json("https://api.groq.com/openai/v1/models", bearer(key))
    return (OK, "key accepted") if code == 200 else (FAIL, f"HTTP {code}")


def check_openrouter(key: str) -> tuple[str, str]:
    code, _ = get_json("https://openrouter.ai/api/v1/key", bearer(key))
    return (OK, "key accepted") if code == 200 else (FAIL, f"HTTP {code}")


def check_gemini(key: str) -> tuple[str, str]:
    code, _ = get_json(
        "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1", {"x-goog-api-key": key}
    )
    return (OK, "key accepted") if code == 200 else (FAIL, f"HTTP {code}")


def check_telegram(token: str, chat_id: str) -> tuple[str, str]:
    code, me = get_json(f"https://api.telegram.org/bot{token}/getMe")
    if code != 200 or not me.get("ok"):
        return FAIL, f"HTTP {code}: token rejected"
    name = me["result"].get("username", "?")
    if chat_id:
        return OK, f"bot @{name}, demo chat set"
    _, updates = get_json(f"https://api.telegram.org/bot{token}/getUpdates")
    chats = {}
    for upd in updates.get("result", []):
        chat = (upd.get("message") or upd.get("my_chat_member") or {}).get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or chat.get("first_name") or "private chat"
    if not chats:
        return FAIL, f"bot @{name} works; open it in Telegram, press Start, then run this again"
    found = ", ".join(f"{cid} ({label})" for cid, label in chats.items())
    return FAIL, f"bot @{name} works; set TELEGRAM_DEMO_CHAT_ID to one of: {found}"


def check_database(url: str) -> tuple[str, str]:
    from sba.config import normalize_db_url

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        return FAIL, "install dependencies first: pip install -r requirements.txt"
    try:
        engine = create_engine(normalize_db_url(url), pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return OK, engine.dialect.name
    except Exception as err:  # noqa: BLE001 - report any driver error plainly
        return FAIL, type(err).__name__


def main() -> int:
    load_env()
    env = os.environ.get
    rows: list[tuple[str, str, str]] = []

    def run(name: str, key: str, fn, *extra: str) -> None:
        if not key:
            rows.append((name, SKIP, "not set"))
            return
        rows.append((name, *fn(key, *extra)))

    run("Groq", env("GROQ_API_KEY", ""), check_groq)
    run("OpenRouter", env("OPENROUTER_API_KEY", ""), check_openrouter)
    run("Gemini", env("GEMINI_API_KEY", ""), check_gemini)
    run("Telegram", env("TELEGRAM_BOT_TOKEN", ""), check_telegram, env("TELEGRAM_DEMO_CHAT_ID", ""))
    db = env("DATABASE_URL", "")
    if db:
        rows.append(("Database", *check_database(db)))
    else:
        rows.append(("Database", SKIP, "not set; local SQLite will be used"))

    width = max(len(r[0]) for r in rows)
    for name, status, detail in rows:
        print(f"{name:<{width}}  {status:<4}  {detail}")
    llm_ok = sum(1 for r in rows[:3] if r[1] == OK)
    print(f"\nLLM providers working: {llm_ok} (two are needed for planner + critic)")
    return 1 if any(r[1] == FAIL for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
