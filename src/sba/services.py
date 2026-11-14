"""Everything the web UI and the Telegram bot share, built once per process."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

from sqlalchemy import Engine

from sba.adapters.registry import build_adapters
from sba.adapters.telegram import TelegramClient, TelegramError
from sba.config import ROOT, Settings, clean_value
from sba.crm.schema import init_db, make_engine
from sba.crm.service import utcnow
from sba.llm.router import LLMRouter
from sba.pipeline import Pipeline
from sba.sessions import Session, SessionManager
from sba.store.runs import RunStore


@dataclass
class Services:
    engine: Engine
    store: RunStore
    sessions: SessionManager
    router: LLMRouter | None
    telegram: TelegramClient | None
    public_url: str | None = None
    clock: Callable[[], datetime] = field(default=utcnow)
    bot_username: str | None = None
    webhook_secret: str = ""  # Telegram echoes it in a header on every webhook call

    @classmethod
    def from_settings(cls, settings: Settings) -> Services:
        engine = make_engine(settings.database_url)
        init_db(engine)
        telegram = TelegramClient(settings.telegram_bot_token) if settings.telegram_bot_token else None
        public = clean_value(os.environ.get("PUBLIC_URL", "") or os.environ.get("RENDER_EXTERNAL_URL", ""))
        secret = hashlib.sha256(f"sba-webhook:{settings.telegram_bot_token}".encode()).hexdigest()[:48]
        services = cls(engine=engine, store=RunStore(ROOT / "runs", engine), sessions=SessionManager(engine),
                       router=LLMRouter.from_settings(settings), telegram=telegram,
                       public_url=public.rstrip("/") or None, webhook_secret=secret)
        services.bot_username = services._lookup_bot()
        return services

    def pipeline(self, session: Session) -> Pipeline:
        """A pipeline over this visitor's own sandbox; their chat (if linked) is the demo inbox."""
        crm = self.sessions.crm(session)
        adapters = build_adapters(crm, telegram=self.telegram, demo_chat_id=session.telegram_chat_id)
        return Pipeline(crm, adapters, self.store, self.router, clock=self.clock)

    def bot_link(self, code: str | None = None) -> str | None:
        if not self.bot_username:
            self.bot_username = self._lookup_bot()  # a startup lookup can fail on a bad network: try again
        if not self.bot_username:
            return None
        return f"https://t.me/{self.bot_username}" + (f"?start={code}" if code else "")

    def _lookup_bot(self) -> str | None:
        if self.telegram is None:
            return None
        try:
            return self.telegram.get_me().get("username")
        except TelegramError:
            return None


@lru_cache(maxsize=1)
def get_services() -> Services:
    """Built on first use, so importing the app (tests, health checks) never touches the network."""
    from sba.config import settings

    return Services.from_settings(settings)
