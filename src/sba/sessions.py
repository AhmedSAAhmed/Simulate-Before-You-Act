"""Per-visitor sandboxes for the public demo.

Every visitor (a browser, a Telegram chat, or both once linked) gets their own copy of the
scenario in its own sandbox. A visitor's Telegram chat is their demo inbox, so the agent can
only ever message the person who is trying it.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    delete,
    insert,
    select,
    update,
)

from sba.crm.schema import SANDBOXED_TABLES
from sba.crm.seed import seed_demo
from sba.crm.service import CrmService, as_utc, utcnow
from sba.store.runs import run_artifacts

DAILY_RUNS = 10
RETENTION = timedelta(days=7)
LINK_TTL = timedelta(minutes=30)

metadata = MetaData()

sessions_table = Table(
    "sba_sessions",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("sandbox", String(64), nullable=False, unique=True),
    Column("telegram_chat_id", String(32), unique=True),
    Column("first_name", String(64)),
    Column("link_code", String(40), index=True),
    Column("link_expires", DateTime(timezone=True)),
    Column("runs_day", Date),
    Column("runs_today", Integer, nullable=False, default=0),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_seen", DateTime(timezone=True), nullable=False),
)
session_runs = Table(
    "sba_session_runs",
    metadata,
    Column("run_id", String(64), primary_key=True),
    Column("session_id", String(40), nullable=False, index=True),
)


@dataclass(frozen=True)
class Session:
    id: str
    sandbox: str
    telegram_chat_id: str | None
    first_name: str | None

    @property
    def linked(self) -> bool:
        return self.telegram_chat_id is not None


class RunLimit(RuntimeError):
    pass


@dataclass
class SessionManager:
    engine: Engine
    clock: Callable[[], datetime] = field(default=utcnow)
    daily_runs: int = DAILY_RUNS
    _busy: set[str] = field(default_factory=set, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        metadata.create_all(self.engine)

    # ---------- lifecycle ----------

    def create(self, *, chat_id: str | None = None, first_name: str | None = None) -> Session:
        sid = secrets.token_urlsafe(18)
        now = self.clock()
        session = Session(sid, f"s-{secrets.token_hex(6)}", chat_id, _name(first_name))
        with self.engine.begin() as conn:
            conn.execute(insert(sessions_table).values(
                id=sid, sandbox=session.sandbox, telegram_chat_id=chat_id, first_name=session.first_name,
                runs_today=0, created_at=now, last_seen=now))
        self._seed(session)
        return session

    def get(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        return self._one(sessions_table.c.id == session_id, touch=True)

    def by_chat(self, chat_id: str) -> Session | None:
        return self._one(sessions_table.c.telegram_chat_id == str(chat_id), touch=True)

    def get_or_create_for_chat(self, chat_id: str, first_name: str | None) -> tuple[Session, bool]:
        found = self.by_chat(chat_id)
        return (found, False) if found else (self.create(chat_id=str(chat_id), first_name=first_name), True)

    def reset(self, session: Session) -> None:
        self._seed(session)

    def forget(self, session: Session) -> None:
        """Delete the visitor's sandbox, their runs and the session itself."""
        with self.engine.begin() as conn:
            for table in SANDBOXED_TABLES:
                conn.execute(delete(table).where(table.c.sandbox == session.sandbox))
            run_ids = [r[0] for r in conn.execute(
                select(session_runs.c.run_id).where(session_runs.c.session_id == session.id))]
            if run_ids:
                conn.execute(delete(run_artifacts).where(run_artifacts.c.run_id.in_(run_ids)))
            conn.execute(delete(session_runs).where(session_runs.c.session_id == session.id))
            conn.execute(delete(sessions_table).where(sessions_table.c.id == session.id))

    def purge_expired(self) -> int:
        cutoff = self.clock() - RETENTION
        with self.engine.connect() as conn:
            rows = conn.execute(select(sessions_table).where(sessions_table.c.last_seen < cutoff)).mappings().all()
        for row in rows:
            self.forget(_session(row))
        return len(rows)

    # ---------- linking a browser to a phone ----------

    def new_link_code(self, session: Session) -> str:
        code = secrets.token_urlsafe(12)  # 16 chars, within Telegram's 64-char start parameter
        with self.engine.begin() as conn:
            conn.execute(update(sessions_table).where(sessions_table.c.id == session.id)
                         .values(link_code=code, link_expires=self.clock() + LINK_TTL))
        return code

    def link_chat(self, code: str, chat_id: str, first_name: str | None) -> Session | None:
        """Attach a Telegram chat to the browser session that issued `code`.

        The chat's older session, if any, is forgotten, and the scenario is reloaded so the
        visitor is customer #1 and their chat is the demo inbox.
        """
        target = self._one(sessions_table.c.link_code == code)
        if target is None:
            return None
        with self.engine.connect() as conn:
            expires = conn.execute(select(sessions_table.c.link_expires)
                                   .where(sessions_table.c.id == target.id)).scalar_one()
        if as_utc(expires) is None or as_utc(expires) < self.clock():
            return None
        previous = self.by_chat(chat_id)
        if previous is not None and previous.id != target.id:
            self.forget(previous)
        with self.engine.begin() as conn:
            conn.execute(update(sessions_table).where(sessions_table.c.id == target.id).values(
                telegram_chat_id=str(chat_id), first_name=_name(first_name), link_code=None, link_expires=None))
        linked = Session(target.id, target.sandbox, str(chat_id), _name(first_name))
        self._seed(linked)
        return linked

    # ---------- runs ----------

    @contextmanager
    def slot(self, session: Session, *, new_run: bool) -> Iterator[None]:
        """Hold the visitor's single working slot. A new request also counts against today's limit;
        tweaks, approvals and rollbacks of an existing run don't."""
        today = self.clock().date()
        with self._lock:
            if session.id in self._busy:
                raise RunLimit("a run is already in progress; wait for it to finish")
            if new_run:
                with self.engine.connect() as conn:
                    row = conn.execute(select(sessions_table.c.runs_day, sessions_table.c.runs_today)
                                       .where(sessions_table.c.id == session.id)).one()
                count = row.runs_today if row.runs_day == today else 0
                if count >= self.daily_runs:
                    raise RunLimit(f"the demo allows {self.daily_runs} new requests a day per visitor; "
                                   "try again tomorrow")
                with self.engine.begin() as conn:
                    conn.execute(update(sessions_table).where(sessions_table.c.id == session.id)
                                 .values(runs_day=today, runs_today=count + 1))
            self._busy.add(session.id)
        try:
            yield
        finally:
            with self._lock:
                self._busy.discard(session.id)

    def remember_run(self, session: Session, run_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(session_runs).where(session_runs.c.run_id == run_id))
            conn.execute(insert(session_runs).values(run_id=run_id, session_id=session.id))

    def owns(self, session: Session, run_id: str) -> bool:
        with self.engine.connect() as conn:
            owner = conn.execute(select(session_runs.c.session_id)
                                 .where(session_runs.c.run_id == run_id)).scalar_one_or_none()
        return owner == session.id

    def crm(self, session: Session) -> CrmService:
        return CrmService(self.engine, sandbox=session.sandbox, clock=self.clock)

    # ---------- internals ----------

    def _seed(self, session: Session) -> None:
        seed_demo(self.crm(session), your_chat_id=session.telegram_chat_id)

    def _one(self, condition, *, touch: bool = False) -> Session | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(sessions_table).where(condition)).mappings().first()
        if row is None:
            return None
        if touch:
            with self.engine.begin() as conn:
                conn.execute(update(sessions_table).where(sessions_table.c.id == row["id"])
                             .values(last_seen=self.clock()))
        return _session(row)


def _session(row) -> Session:
    return Session(row["id"], row["sandbox"], row["telegram_chat_id"], row["first_name"])


def _name(first_name: str | None) -> str | None:
    return first_name.strip()[:64] if first_name and first_name.strip() else None
