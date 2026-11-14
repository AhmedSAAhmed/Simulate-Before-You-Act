"""CRM tables. Portable across Postgres (Neon) and SQLite (local and tests)."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
)
from sqlalchemy.pool import StaticPool

metadata = MetaData()

contacts = Table(
    "crm_contacts",
    metadata,
    Column("sandbox", String(64), primary_key=True),
    Column("id", String(32), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("language", String(8), nullable=False),
    # A numeric Telegram chat id, "demo" (delivered to the demo inbox), or NULL (no channel).
    Column("telegram_chat_id", String(32)),
    Column("opted_out", Boolean, nullable=False, default=False),
    Column("labels", JSON, nullable=False),
    Column("custom_attributes", JSON, nullable=False),
    Column("deleted_at", DateTime(timezone=True)),
    Column("purge_after", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

charges = Table(
    "crm_charges",
    metadata,
    Column("sandbox", String(64), primary_key=True),
    Column("id", String(32), primary_key=True),
    Column("contact_id", String(32), nullable=False),
    Column("amount_minor", Integer, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("created_on", Date, nullable=False),
    Column("order_ref", String(32), nullable=False),
    Column("duplicate_of", String(32)),
    Column("disputed", Boolean, nullable=False, default=False),
)

# Append-only: a credit is a positive row, its reversal a negative row. Rows are never updated.
wallet_ledger = Table(
    "crm_wallet_ledger",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sandbox", String(64), nullable=False, index=True),
    Column("contact_id", String(32), nullable=False),
    Column("amount_minor", Integer, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("kind", String(16), nullable=False),  # opening | credit | reversal | spend
    Column("charge_id", String(32)),
    Column("actor", String(80), nullable=False),  # seed | human:<name> | agent:<run-id>
    Column("run_id", String(64)),
    Column("idempotency_key", String(200), unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

tickets = Table(
    "crm_tickets",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sandbox", String(64), nullable=False, index=True),
    Column("contact_id", String(32), nullable=False),
    Column("status", String(16), nullable=False),  # open | closed
    Column("subject", String(200), nullable=False),
    Column("source", String(80), nullable=False),  # human | automation:<rule-id>
    Column("run_id", String(64)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

automation_rules = Table(
    "crm_automation_rules",
    metadata,
    Column("sandbox", String(64), primary_key=True),
    Column("id", String(32), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("trigger", String(32), nullable=False),  # label_added
    Column("match_text", String(64), nullable=False),
    Column("action", String(32), nullable=False),  # open_ticket_and_notify
    Column("notice_en", Text, nullable=False),
    Column("notice_ar", Text, nullable=False),
    Column("enabled", Boolean, nullable=False, default=True),
)

notifications = Table(
    "crm_notifications",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sandbox", String(64), nullable=False, index=True),
    Column("contact_id", String(32), nullable=False),
    Column("rule_id", String(32), nullable=False),
    Column("run_id", String(64)),
    Column("text", Text, nullable=False),
    Column("delivery_ref", String(64)),  # "<chat>:<message>" once sent
    Column("created_at", DateTime(timezone=True), nullable=False),
)

snapshots = Table(
    "crm_snapshots",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sandbox", String(64), nullable=False, index=True),
    Column("run_id", String(64), nullable=False),
    Column("record_type", String(32), nullable=False),
    Column("record_id", String(32), nullable=False),
    Column("data", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

SANDBOXED_TABLES = (contacts, charges, wallet_ledger, tickets, automation_rules, notifications, snapshots)


def make_engine(url: str) -> Engine:
    if url in ("sqlite://", "sqlite:///:memory:"):
        return create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    # No pre-ping: it costs a full round trip before every query (about half the time, measured from the
    # Gulf to Frankfurt). Recycling connections before Neon's 5-minute idle suspend avoids stale ones instead.
    return create_engine(url, pool_pre_ping=False, pool_recycle=240, pool_size=5, max_overflow=5)


def init_db(engine: Engine) -> None:
    metadata.create_all(engine)
