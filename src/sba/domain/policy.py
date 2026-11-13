"""The values in `_shared/risk-policy.md`, enforced in code. No model can change them."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from typing import Any

from sba.domain.models import REVERSIBILITY, ActionKind, Blocker, Effect, Reversibility, Tier
from sba.domain.money import fmt, to_minor

CREDIT_TOTAL_LIMIT_UNITS = 5_000
MAX_RECIPIENTS = 500
MAX_DELETIONS = 50
APPROVAL_TTL = timedelta(minutes=10)
SOFT_DELETE_WINDOW = timedelta(hours=24)
CANARY_SHARE = 0.05

MONEY_ACTIONS = frozenset({ActionKind.ISSUE_CREDIT})


def tier(effects: Iterable[Effect], kinds: dict[int, ActionKind]) -> Tier:
    by_kind: dict[ActionKind, int] = {}
    for e in effects:
        kind = kinds[e.action_index]
        by_kind[kind] = by_kind.get(kind, 0) + 1
    if (
        any(k in MONEY_ACTIONS for k in by_kind)
        or any(REVERSIBILITY[k] is Reversibility.IRREVERSIBLE for k in by_kind)
        or by_kind.get(ActionKind.SEND_MESSAGE, 0) > 50
        or by_kind.get(ActionKind.DELETE_CONTACTS, 0) > 0
    ):
        return Tier.HIGH
    if any(REVERSIBILITY[k] is Reversibility.RECALLABLE for k in by_kind) or sum(by_kind.values()) > 10:
        return Tier.MEDIUM
    return Tier.LOW


def limit_blockers(totals: dict[str, Any]) -> list[Blocker]:
    """Plan-level hard limits. They can't be overridden, only brought under by excluding items."""
    out: list[Blocker] = []
    currency = totals.get("currency")
    credit_total = int(totals.get("credit_total_minor", 0))
    if currency and credit_total > to_minor(CREDIT_TOTAL_LIMIT_UNITS, currency):
        out.append(Blocker(
            action_index=-1, record_id="plan", rule="credit_total_limit", hard=True,
            detail=f"credits total {fmt(credit_total, currency)}, above the "
            f"{fmt(to_minor(CREDIT_TOTAL_LIMIT_UNITS, currency), currency)} limit per plan",
        ))
    if int(totals.get("messages", 0)) > MAX_RECIPIENTS:
        out.append(Blocker(action_index=-1, record_id="plan", rule="recipient_limit", hard=True,
                           detail=f"{totals['messages']} recipients, above the {MAX_RECIPIENTS} limit per plan"))
    if int(totals.get("deletions", 0)) > MAX_DELETIONS:
        out.append(Blocker(action_index=-1, record_id="plan", rule="deletion_limit", hard=True,
                           detail=f"{totals['deletions']} deletions, above the {MAX_DELETIONS} limit per plan"))
    return out


def canary_size(item_count: int) -> int:
    return max(1, round(item_count * CANARY_SHARE)) if item_count else 0
