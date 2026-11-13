"""The contract every adapter implements: simulate (read-only), execute, compensate, observe."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sba.domain.hashing import StateRead
from sba.domain.models import Action, ActionKind, Blocker, Effect, SideEffect

LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class SelectorError(ValueError):
    """The plan names targets in a way this adapter can't resolve safely."""


@dataclass(frozen=True)
class Target:
    """An item an action will touch, passed on so later actions can reuse it (`from_action`)."""

    record_id: str
    contact_id: str
    amount_minor: int = 0
    currency: str = ""


@dataclass
class SimContext:
    now: datetime
    blind_spots: frozenset[str] = frozenset()
    targets: dict[int, list[Target]] = field(default_factory=dict)
    reads: list[StateRead] = field(default_factory=list)
    balances: dict[str, int] = field(default_factory=dict)

    def read(self, system: str, record_id: str, name: str, value: Any) -> Any:
        """Record a value the prediction depends on; it becomes part of the state fingerprint."""
        self.reads.append((system, record_id, name, value))
        return value


@dataclass
class ActionSim:
    effects: list[Effect] = field(default_factory=list)
    blockers: list[Blocker] = field(default_factory=list)
    side_effects: list[SideEffect] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    targets: list[Target] = field(default_factory=list)
    totals: dict[str, Any] = field(default_factory=dict)
    rollback: str = ""


@dataclass(frozen=True)
class ExecResult:
    status: str  # done | unknown | failed | needs_recovery | rolled_back
    external_ref: str | None = None
    snapshot_ref: int | None = None
    detail: str = ""


class Adapter(Protocol):
    kind: ActionKind
    system: str

    def simulate(self, index: int, action: Action, ctx: SimContext) -> ActionSim: ...

    def execute(self, effect: Effect, *, run_id: str) -> ExecResult: ...

    def compensate(self, effect: Effect, result: ExecResult, *, run_id: str) -> ExecResult: ...

    def observe(self, effect: Effect) -> dict[str, Any]: ...


def idempotency_key(run_id: str, effect: Effect, suffix: str = "") -> str:
    return f"{run_id}:{effect.action_index}:{effect.record_id}{suffix}"


def item_controls(action: Action) -> tuple[frozenset[str], dict[str, str]]:
    """The operator's tweaks: ids to leave out, and ids to include despite a blocker (with a reason)."""
    exclude = action.params.get("exclude", [])
    override = action.params.get("override", {})
    if not isinstance(exclude, list) or not all(isinstance(x, str) for x in exclude):
        raise SelectorError("params.exclude must be a list of record ids")
    if not isinstance(override, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in override.items()
    ):
        raise SelectorError("params.override must map record ids to a written reason")
    return frozenset(exclude), {k: v.strip() for k, v in override.items()}


def require_keys(
    where: str, given: dict[str, Any], allowed: frozenset[str], required: frozenset[str] = frozenset()
) -> None:
    unknown = set(given) - allowed
    missing = set(required) - set(given)
    if unknown:
        raise SelectorError(f"{where}: unknown keys {sorted(unknown)}")
    if missing:
        raise SelectorError(f"{where}: missing keys {sorted(missing)}")


def from_action_targets(index: int, selector: dict[str, Any], ctx: SimContext) -> list[Target]:
    source = selector.get("from_action")
    if not isinstance(source, int) or isinstance(source, bool) or not 0 <= source < index:
        raise SelectorError("selector.from_action must name an earlier action by its index")
    return ctx.targets.get(source, [])
