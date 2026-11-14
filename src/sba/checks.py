"""The `## Check` of each stage contract, as code.

Usage: python -m sba.checks <stage> <run-id>   (stage: intent | simulate | present | execute | verify)
Re-reads that stage's output from the run folder and rewrites its `check.md`.
"""

from __future__ import annotations

import json
import sys

from sba.adapters.specs import static_errors
from sba.domain.models import ActionPlan, Decision, Journal, Simulation, Verification

Verdict = tuple[bool, str]


def intent(plan: ActionPlan) -> Verdict:
    errors = [e for i, a in enumerate(plan.actions) for e in static_errors(a, i)]
    if not plan.actions:
        errors.append("the plan has no actions")
    return (not errors, "; ".join(errors))


def simulate(sim: Simulation) -> Verdict:
    if not sim.blockers:
        return True, ""
    rules = sorted({b.rule for b in sim.blockers})
    return False, f"{len(sim.blockers)} unresolved blocker(s): {', '.join(rules)}"


def present(decision: Decision) -> Verdict:
    return (decision.verdict == "approve", f"rejected by {decision.approver}")


def execute(journal: Journal) -> Verdict:
    if journal.outcome == "completed" and not any(e.status == "unknown" for e in journal.entries):
        return True, ""
    return False, f"{journal.outcome}: {journal.reason}"


def verify(verification: Verification) -> Verdict:
    return (verification.outcome == "match", f"{verification.outcome}: {verification.summary}")


_STAGES = {
    "intent": ("01_intent", "plan.json", ActionPlan, intent),
    "simulate": ("02_simulate", "simulation.json", Simulation, simulate),
    "present": ("03_present", "decision.json", Decision, present),
    "execute": ("04_execute", "journal.json", Journal, execute),
    "verify": ("05_verify", "verification.json", Verification, verify),
}


def main(argv: list[str]) -> int:
    from sba.config import ROOT
    from sba.store.runs import RunStore

    if len(argv) != 2 or argv[0] not in _STAGES:
        print(__doc__)
        return 2
    stage_name, run_id = argv
    folder, artifact, model, check = _STAGES[stage_name]
    store = RunStore(ROOT / "runs")
    text = store.load(run_id, f"{folder}/output/{artifact}")
    if text is None:
        store.save_check(run_id, folder, False, f"{artifact} is missing")
        print(f"fail: {artifact} is missing")
        return 1
    passed, why = check(model.model_validate(json.loads(text)))
    store.save_check(run_id, folder, passed, why)
    print("pass" if passed else f"fail: {why}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
