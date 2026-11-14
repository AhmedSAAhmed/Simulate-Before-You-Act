"""One run through the five stages, writing the ICM run folder as it goes.

Every stage saves its output and its `check.md`; a failed check stops the run there.
The UI and the CLI both drive this class.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime

from sba import checks
from sba.adapters.base import Adapter
from sba.agents import critic as critic_agent
from sba.agents import verifier
from sba.agents.executor import ExecutionResult, execute_plan
from sba.agents.planner import PlanError, plan_request
from sba.agents.simulator import simulate
from sba.crm.seed import demo_plan
from sba.crm.service import CrmService, utcnow
from sba.domain.models import Action, ActionKind, ActionPlan, Decision, Simulation
from sba.llm.router import LLMError, LLMRouter
from sba.store.approvals import decide
from sba.store.runs import RunStore


class StageFailed(RuntimeError):
    def __init__(self, stage: str, why: str) -> None:
        super().__init__(f"{stage} check failed: {why}")
        self.stage, self.why = stage, why


@dataclass
class Pipeline:
    crm: CrmService
    adapters: dict[ActionKind, Adapter]
    store: RunStore
    router: LLMRouter | None = None
    clock: Callable[[], datetime] = field(default=utcnow)
    planner_model: dict[str, str] = field(default_factory=dict)

    # 00 + 01
    def plan(self, request: str, *, use_example: bool = False, today: date | None = None) -> ActionPlan:
        run_id = self.store.new_run_id(self.clock())
        self.store.save_request(run_id, request)
        if use_example or self.router is None or not self.router.available("planner"):
            plan = demo_plan(run_id).model_copy(update={"request": request or demo_plan().request})
            model = "example plan (no model used)"
        else:
            try:
                result = plan_request(request, self.router, run_id=run_id, today=today or self.clock().date())
            except (PlanError, LLMError) as err:
                why = "; ".join(getattr(err, "errors", [])) or str(err)
                self.store.save_check(run_id, "01_intent", False, why)
                raise StageFailed("01_intent", why) from err
            plan, model = result.plan, result.model
        self.planner_model[run_id] = model
        self.store.save(run_id, "01_intent", "plan.json", plan)
        self.store.save(run_id, "01_intent", "meta.json", {"model": model})
        passed, why = checks.intent(plan)
        self.store.save_check(run_id, "01_intent", passed, why)
        if not passed:
            raise StageFailed("01_intent", why)
        return plan

    # 02 (a failed check here is normal: it means blockers for the operator to resolve)
    def simulate(self, plan: ActionPlan, *, blind_spots: Iterable[str] = (), use_critic: bool = True) -> Simulation:
        blind = tuple(blind_spots)
        sim = simulate(plan, self.adapters, now=self.clock(), blind_spots=blind)
        meta: dict[str, object] = {"blind_spots": sorted(blind), "critic": None}
        if use_critic and self.router is not None and self.router.available("critic"):
            planner = self.planner_model.get(plan.run_id, "")
            found = critic_agent.critique(plan, sim, self.router, avoid_provider=planner.split(":")[0] or None)
            sim = critic_agent.with_critique(sim, found)
            meta["critic"] = {"model": found.model, "error": found.error}
        self.store.save(plan.run_id, "01_intent", "plan.json", plan)  # the latest tweaked plan
        self.store.save(plan.run_id, "02_simulate", "simulation.json", sim)
        self.store.save(plan.run_id, "02_simulate", "meta.json", meta)
        self.store.save_check(plan.run_id, "02_simulate", *checks.simulate(sim))
        return sim

    # 03
    def decide(self, plan: ActionPlan, sim: Simulation, *, approver: str, verdict: str) -> Decision:
        decision = decide(plan, sim, approver=approver, verdict=verdict, now=self.clock())
        self.store.save(plan.run_id, "03_present", "decision.json", decision)
        self.store.save_check(plan.run_id, "03_present", *checks.present(decision))
        return decision

    # 04 + 05
    def execute(
        self, plan: ActionPlan, sim: Simulation, decision: Decision, *, blind_spots: Iterable[str] = (),
        before_writes: Callable[[], None] | None = None,
    ) -> ExecutionResult:
        result = execute_plan(plan, sim, decision, self.adapters, now=self.clock(), blind_spots=blind_spots,
                              before_writes=before_writes)
        v = result.verification
        self.store.save(plan.run_id, "04_execute", "journal.json", result.journal)
        self.store.save_check(plan.run_id, "04_execute", *checks.execute(result.journal))
        self.store.save(plan.run_id, "05_verify", "verification.json", v)
        self.store.save(plan.run_id, "05_verify", "report.md", verifier.report_markdown(
            plan, sim, v.outcome, v.summary, v.diffs, v.unpredicted, v.invariants, v.rollback))
        self.store.save_check(plan.run_id, "05_verify", *checks.verify(v))
        return result


def resolve_blockers(plan: ActionPlan, sim: Simulation, *, accept_rules_reason: str | None = None) -> ActionPlan:
    """The 'leave out everything blocked' tweak: exclude each blocked item; accept automation
    rules only when a person gives a reason. Plan-level limits can't be resolved this way."""
    exclude: dict[int, list[str]] = {}
    override: dict[int, dict[str, str]] = {}
    for b in sim.blockers:
        if b.record_id == "plan":
            continue
        if b.record_id.startswith("rule:"):
            if accept_rules_reason:
                override.setdefault(b.action_index, {})[b.record_id] = accept_rules_reason
            continue
        exclude.setdefault(b.action_index, []).append(b.record_id)
    actions = []
    for i, action in enumerate(plan.actions):
        params = dict(action.params)
        if i in exclude:
            params["exclude"] = sorted(set(params.get("exclude", [])) | set(exclude[i]))
        if i in override:
            params["override"] = {**params.get("override", {}), **override[i]}
        actions.append(Action(kind=action.kind, selector=action.selector, params=params, reason=action.reason))
    return plan.model_copy(update={"actions": tuple(actions)})
