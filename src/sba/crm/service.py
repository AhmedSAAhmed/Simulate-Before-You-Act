"""CRM operations. Every write, by the agent or by a person, goes through here,
so automations fire the same way no matter who made the change."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Engine, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from sba.crm.schema import (
    automation_rules,
    charges,
    contacts,
    notifications,
    snapshots,
    tickets,
    wallet_ledger,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite drops tz info on the way back; treat stored times as UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Notice:
    contact_id: str
    contact_name: str
    language: str
    telegram_chat_id: str | None
    text: str


# A notifier delivers an automation's notice (for example over Telegram) and returns a delivery ref.
Notifier = Callable[[Notice], str | None]


@dataclass
class CrmService:
    engine: Engine
    sandbox: str = "demo"
    notifier: Notifier | None = None
    clock: Callable[[], datetime] = field(default=utcnow)

    # ---------- reads ----------

    def contact(self, contact_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(contacts).where(contacts.c.sandbox == self.sandbox, contacts.c.id == contact_id)
            ).mappings().first()
        return _contact(row) if row else None

    def contacts_with_label(self, label: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(contacts)
                .where(contacts.c.sandbox == self.sandbox, contacts.c.deleted_at.is_(None))
                .order_by(contacts.c.id)
            ).mappings().all()
        return [_contact(r) for r in rows if label in (r["labels"] or [])]

    def label_counts(self) -> dict[str, int]:
        """Every label in use on active contacts, with how many contacts carry it."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(contacts.c.labels).where(contacts.c.sandbox == self.sandbox, contacts.c.deleted_at.is_(None))
            ).all()
        counts: dict[str, int] = {}
        for (labels,) in rows:
            for label in labels or []:
                counts[label] = counts.get(label, 0) + 1
        return counts

    def duplicate_charges_on(self, day: date) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(charges)
                .where(
                    charges.c.sandbox == self.sandbox,
                    charges.c.created_on == day,
                    charges.c.duplicate_of.is_not(None),
                )
                .order_by(charges.c.id)
            ).mappings().all()
        return [dict(r) for r in rows]

    def credited_for_charge(self, charge_id: str) -> int:
        """Net amount already returned for a charge: credits minus reversals."""
        with self.engine.connect() as conn:
            total = conn.execute(
                select(func.coalesce(func.sum(wallet_ledger.c.amount_minor), 0)).where(
                    wallet_ledger.c.sandbox == self.sandbox,
                    wallet_ledger.c.charge_id == charge_id,
                    wallet_ledger.c.kind.in_(("credit", "reversal")),
                )
            ).scalar_one()
        return int(total)

    def wallet_balance(self, contact_id: str) -> int:
        with self.engine.connect() as conn:
            total = conn.execute(
                select(func.coalesce(func.sum(wallet_ledger.c.amount_minor), 0)).where(
                    wallet_ledger.c.sandbox == self.sandbox, wallet_ledger.c.contact_id == contact_id
                )
            ).scalar_one()
        return int(total)

    def open_tickets(self, contact_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(tickets).where(
                    tickets.c.sandbox == self.sandbox,
                    tickets.c.contact_id == contact_id,
                    tickets.c.status == "open",
                )
            ).mappings().all()
        return [dict(r) for r in rows]

    def automation_rules(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(automation_rules)
                .where(automation_rules.c.sandbox == self.sandbox, automation_rules.c.enabled.is_(True))
                .order_by(automation_rules.c.id)
            ).mappings().all()
        return [dict(r) for r in rows]

    def tickets_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(tickets).where(tickets.c.sandbox == self.sandbox, tickets.c.run_id == run_id)
            ).mappings().all()
        return [dict(r) for r in rows]

    def notifications_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(notifications).where(
                    notifications.c.sandbox == self.sandbox, notifications.c.run_id == run_id
                )
            ).mappings().all()
        return [dict(r) for r in rows]

    def ledger_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(wallet_ledger).where(wallet_ledger.c.sandbox == self.sandbox, wallet_ledger.c.run_id == run_id)
            ).mappings().all()
        return [dict(r) for r in rows]

    def charge(self, charge_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(charges).where(charges.c.sandbox == self.sandbox, charges.c.id == charge_id)
            ).mappings().first()
        return dict(row) if row else None

    def get_snapshot(self, snapshot_id: int) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(snapshots).where(snapshots.c.sandbox == self.sandbox, snapshots.c.id == snapshot_id)
            ).mappings().one()
        return dict(row)

    # ---------- writes ----------

    def add_ledger_entry(
        self,
        *,
        contact_id: str,
        amount_minor: int,
        currency: str,
        kind: str,
        actor: str,
        charge_id: str | None = None,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> int:
        """Append one ledger row. Re-sending the same idempotency key returns the first row."""
        if idempotency_key:
            existing = self._ledger_id_for_key(idempotency_key)
            if existing is not None:
                return existing
        row = {
            "sandbox": self.sandbox,
            "contact_id": contact_id,
            "amount_minor": amount_minor,
            "currency": currency,
            "kind": kind,
            "charge_id": charge_id,
            "actor": actor,
            "run_id": run_id,
            "idempotency_key": idempotency_key,
            "created_at": self.clock(),
        }
        try:
            with self.engine.begin() as conn:
                return int(conn.execute(insert(wallet_ledger).values(**row)).inserted_primary_key[0])
        except IntegrityError:
            existing = self._ledger_id_for_key(idempotency_key) if idempotency_key else None
            if existing is None:
                raise
            return existing

    def set_labels(self, contact_id: str, labels: list[str], *, actor: str, run_id: str | None = None) -> list[int]:
        """Replace a contact's labels. Newly added labels fire matching automation rules.

        Returns the ids of tickets that automations opened.
        """
        current = self.contact(contact_id)
        if current is None:
            raise KeyError(contact_id)
        added = [lbl for lbl in labels if lbl not in current["labels"]]
        with self.engine.begin() as conn:
            conn.execute(
                update(contacts)
                .where(contacts.c.sandbox == self.sandbox, contacts.c.id == contact_id)
                .values(labels=list(labels), updated_at=self.clock())
            )
        return self._fire_label_automations(current, added, run_id=run_id) if added else []

    def soft_delete(self, contact_id: str, *, purge_after: datetime) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(contacts)
                .where(contacts.c.sandbox == self.sandbox, contacts.c.id == contact_id)
                .values(deleted_at=self.clock(), purge_after=purge_after, updated_at=self.clock())
            )

    def undelete(self, contact_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(contacts)
                .where(contacts.c.sandbox == self.sandbox, contacts.c.id == contact_id)
                .values(deleted_at=None, purge_after=None, updated_at=self.clock())
            )

    def close_ticket(self, ticket_id: int) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(tickets)
                .where(tickets.c.sandbox == self.sandbox, tickets.c.id == ticket_id)
                .values(status="closed")
            )

    def open_ticket(self, contact_id: str, subject: str, *, source: str = "human", run_id: str | None = None) -> int:
        with self.engine.begin() as conn:
            return int(
                conn.execute(
                    insert(tickets).values(
                        sandbox=self.sandbox,
                        contact_id=contact_id,
                        status="open",
                        subject=subject,
                        source=source,
                        run_id=run_id,
                        created_at=self.clock(),
                    )
                ).inserted_primary_key[0]
            )

    def snapshot(self, *, run_id: str, record_type: str, record_id: str, data: dict[str, Any]) -> int:
        with self.engine.begin() as conn:
            return int(
                conn.execute(
                    insert(snapshots).values(
                        sandbox=self.sandbox,
                        run_id=run_id,
                        record_type=record_type,
                        record_id=record_id,
                        data=data,
                        created_at=self.clock(),
                    )
                ).inserted_primary_key[0]
            )

    # ---------- internals ----------

    def _ledger_id_for_key(self, key: str) -> int | None:
        with self.engine.connect() as conn:
            found = conn.execute(
                select(wallet_ledger.c.id).where(wallet_ledger.c.idempotency_key == key)
            ).scalar_one_or_none()
        return int(found) if found is not None else None

    def _fire_label_automations(self, contact: dict[str, Any], added: list[str], *, run_id: str | None) -> list[int]:
        opened: list[int] = []
        for rule in self.automation_rules():
            if rule["trigger"] != "label_added" or not any(rule["match_text"] in lbl for lbl in added):
                continue
            ticket_id = self.open_ticket(
                contact["id"], f"{rule['name']}: {', '.join(added)}", source=f"automation:{rule['id']}", run_id=run_id
            )
            opened.append(ticket_id)
            text = rule["notice_ar"] if contact["language"] == "ar" else rule["notice_en"]
            ref = None
            if self.notifier is not None:
                ref = self.notifier(
                    Notice(contact["id"], contact["name"], contact["language"], contact["telegram_chat_id"], text)
                )
            with self.engine.begin() as conn:
                conn.execute(
                    insert(notifications).values(
                        sandbox=self.sandbox,
                        contact_id=contact["id"],
                        rule_id=rule["id"],
                        run_id=run_id,
                        text=text,
                        delivery_ref=ref,
                        created_at=self.clock(),
                    )
                )
        return opened


def _contact(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["labels"] = list(data.get("labels") or [])
    data["custom_attributes"] = dict(data.get("custom_attributes") or {})
    data["deleted_at"] = as_utc(data.get("deleted_at"))
    data["purge_after"] = as_utc(data.get("purge_after"))
    data["updated_at"] = as_utc(data.get("updated_at"))
    return data


__all__ = ["CrmService", "Notice", "Notifier", "as_utc", "utcnow"]
