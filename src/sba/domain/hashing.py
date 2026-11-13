"""Canonical hashes that bind an approval to one plan and one observed state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from sba.domain.models import ActionPlan

StateRead = tuple[str, str, str, Any]  # (system, record_id, field, value)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def plan_hash(plan: ActionPlan) -> str:
    """Hash of the actions only: rewording the request doesn't change what runs."""
    actions = [a.model_dump(mode="json") for a in plan.actions]
    return _sha256(canonical_json(actions))


def state_fingerprint(reads: Iterable[StateRead]) -> str:
    """Order-independent hash of every field the simulator read."""
    rows = sorted(canonical_json(list(r)) for r in reads)
    return _sha256("\n".join(rows))
