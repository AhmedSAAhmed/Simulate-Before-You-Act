"""Settings read once from the environment (and `.env` when present)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False)


_QUOTES = "\"'“”‘’"


def clean_value(value: str) -> str:
    """Strip whitespace and any straight or curly quotes pasted around a value."""
    return value.strip().strip(_QUOTES).strip()


def _env(name: str, default: str = "") -> str:
    return clean_value(os.environ.get(name, default))


def normalize_db_url(url: str) -> str:
    """Point Postgres URLs (Neon gives `postgresql://`) at the psycopg 3 driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _db_url() -> str:
    return normalize_db_url(_env("DATABASE_URL") or f"sqlite:///{(ROOT / 'sba.sqlite3').as_posix()}")


@dataclass(frozen=True)
class Settings:
    host: str = field(default_factory=lambda: _env("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_env("PORT", "7860")))
    database_url: str = field(default_factory=_db_url)
    groq_api_key: str = field(default_factory=lambda: _env("GROQ_API_KEY"))
    openrouter_api_key: str = field(default_factory=lambda: _env("OPENROUTER_API_KEY"))
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    telegram_bot_token: str = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN"))
    telegram_demo_chat_id: str = field(default_factory=lambda: _env("TELEGRAM_DEMO_CHAT_ID"))
    def systems(self) -> dict[str, bool]:
        """Which real systems are configured (keys present, not validated)."""
        providers = sum(bool(k) for k in (self.groq_api_key, self.openrouter_api_key, self.gemini_api_key))
        return {
            "Planner LLM": providers >= 1,
            "Critic LLM (second provider)": providers >= 2,
            "Telegram bot": bool(self.telegram_bot_token and self.telegram_demo_chat_id),
            "CRM and wallet ledger (Neon)": self.database_url.startswith("postgresql"),
        }


settings = Settings()
