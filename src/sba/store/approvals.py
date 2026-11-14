"""Stage 03's output: a decision bound to one plan hash and one state fingerprint (ADR 0001)."""

from __future__ import annotations

from datetime import datetime

from sba.domain.hashing import plan_hash
from sba.domain.models import ActionPlan, Decision, Simulation
from sba.domain.policy import APPROVAL_TTL


class ApprovalError(ValueError):
    pass


def decide(
    plan: ActionPlan, simulation: Simulation, *, approver: str, verdict: str, now: datetime
) -> Decision:
    approver = approver.strip()
    if not approver:
        raise ApprovalError("a decision needs the approver's name")
    if plan_hash(plan) != simulation.plan_hash:
        raise ApprovalError("the plan changed after this simulation; simulate again")
    if verdict == "approve" and simulation.blockers:
        raise ApprovalError(f"{len(simulation.blockers)} blocker(s) are unresolved; Approve stays disabled")
    return Decision(verdict=verdict, plan_hash=simulation.plan_hash, state_fingerprint=simulation.state_fingerprint,
                    approver=approver, decided_at=now, expires_at=now + APPROVAL_TTL)


def binding_errors(decision: Decision, plan: ActionPlan, simulation: Simulation, now: datetime) -> list[str]:
    """Why this decision may not release this plan right now (empty means it may)."""
    errors = []
    if decision.verdict != "approve":
        errors.append(f"the plan was {decision.verdict}ed")
    if now >= decision.expires_at:
        errors.append(f"the approval expired at {decision.expires_at:%H:%M:%S} UTC")
    if decision.plan_hash != plan_hash(plan) or decision.plan_hash != simulation.plan_hash:
        errors.append("the plan differs from the one approved")
    if decision.state_fingerprint != simulation.state_fingerprint:
        errors.append("the approval was made against a different simulation")
    if simulation.blockers:
        errors.append("the simulation still has blockers")
    return errors
