"""Run artifacts: the single source of truth for `_meta/schema.md`."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActionKind(StrEnum):
    ISSUE_CREDIT = "issue_credit"
    SEND_MESSAGE = "send_message"
    UPDATE_CONTACT_ATTRIBUTES = "update_contact_attributes"
    DELETE_CONTACTS = "delete_contacts"


class Reversibility(StrEnum):
    REVERSIBLE = "reversible"
    RECALLABLE = "recallable"
    COMPENSABLE = "compensable"
    IRREVERSIBLE = "irreversible"


class Tier(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


REVERSIBILITY: dict[ActionKind, Reversibility] = {
    ActionKind.ISSUE_CREDIT: Reversibility.COMPENSABLE,
    ActionKind.SEND_MESSAGE: Reversibility.RECALLABLE,
    ActionKind.UPDATE_CONTACT_ATTRIBUTES: Reversibility.REVERSIBLE,
    ActionKind.DELETE_CONTACTS: Reversibility.REVERSIBLE,
}


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Action(_Frozen):
    kind: ActionKind
    selector: dict[str, Any] = Field(description="Filters over live data; never a model-typed id list")
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class ActionPlan(_Frozen):
    run_id: str
    request: str
    actions: tuple[Action, ...]
    notes: str = ""


class Effect(_Frozen):
    action_index: int
    system: str
    record_id: str
    subject: str = Field(description="Who or what is affected, as a person reads it")
    before: dict[str, Any]
    after: dict[str, Any]


class Blocker(_Frozen):
    action_index: int = Field(description="-1 for a plan-level limit")
    record_id: str
    rule: str
    detail: str
    hard: bool = Field(default=False, description="True: only excluding the item resolves it; no override")
    fix: dict[str, Any] = Field(
        default_factory=dict, description="A suggested plan edit, e.g. {'selector': {'label': 'spam-import-2026-11'}}"
    )


class SideEffect(_Frozen):
    description: str
    likelihood: str = Field(pattern="^(low|medium|high)$")
    source: str = Field(description="'engine' or 'critic'")
    expected: dict[str, int] = Field(
        default_factory=dict, description="Counts the verifier can check, e.g. {'tickets_opened': 7}"
    )


class Simulation(_Frozen):
    plan_hash: str
    state_fingerprint: str
    effects: tuple[Effect, ...]
    side_effects: tuple[SideEffect, ...] = ()
    blockers: tuple[Blocker, ...] = ()
    impacted: tuple[str, ...] = ()
    rollback: tuple[str, ...] = ()
    notes: tuple[str, ...] = Field(default=(), description="Items left out or included, and why")
    tier: Tier
    totals: dict[str, Any] = Field(default_factory=dict)


class Decision(_Frozen):
    verdict: str = Field(pattern="^(approve|reject)$")
    plan_hash: str
    state_fingerprint: str
    approver: str
    decided_at: datetime
    expires_at: datetime


class JournalEntry(_Frozen):
    action_index: int
    item_id: str
    phase: str = Field(pattern="^(canary|batch|rollback)$")
    idempotency_key: str
    status: str = Field(description="done | unknown | failed | needs_recovery | rolled_back")
    external_ref: str | None = None
    snapshot_ref: int | None = None
    detail: str = ""


class Journal(_Frozen):
    run_id: str
    outcome: str = Field(description="completed | halted | drift | refused")
    reason: str = ""
    entries: tuple[JournalEntry, ...] = ()


class Diff(_Frozen):
    action_index: int
    record_id: str
    field: str
    predicted: Any
    observed: Any


class InvariantResult(_Frozen):
    name: str
    held: bool
    detail: str = ""


class Verification(_Frozen):
    outcome: str = Field(description="match | rolled_back | halted | drift | refused")
    summary: str
    diffs: tuple[Diff, ...] = ()
    unpredicted: dict[str, int] = Field(default_factory=dict)
    invariants: tuple[InvariantResult, ...] = ()
    rollback: tuple[JournalEntry, ...] = ()
