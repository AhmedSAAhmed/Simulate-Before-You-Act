"""One run through the five stages, writing the ICM run folder as it goes.

Every stage saves its output and its `check.md`; a failed check stops the run there.
The UI and the CLI both drive this class.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime

from sba import checks
from sba.adapters.base import Adapter, ExecResult
from sba.agents import critic as critic_agent
from sba.agents import verifier
from sba.agents.executor import ExecutionResult, execute_plan
from sba.agents.planner import PlanError, plan_request
from sba.agents.simulator import simulate
from sba.crm.seed import demo_plan
from sba.crm.service import CrmService, utcnow
from sba.domain.models import Action, ActionKind, ActionPlan, Decision, Journal, JournalEntry, Simulation
from sba.llm.router import LLMError, LLMRouter
from sba.store.approvals import decide
from sba.store.runs import RunStore


EXAMPLE_MODEL = "example plan"


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
    def plan(
        self, request: str, *, use_example: bool = False, today: date | None = None,
        fallback_to_example: bool = False, run_id: str | None = None,
    ) -> ActionPlan:
        """`fallback_to_example`: if no model can answer (or today's budget is spent), use the example
        plan and say so, rather than failing. A model that answers with an invalid plan still fails."""
        run_id = run_id or self.store.new_run_id(self.clock())
        self.store.save_request(run_id, request)
        example = demo_plan(run_id).model_copy(update={"request": request or demo_plan().request})
        if use_example or self.router is None or not self.router.available("planner"):
            plan, model = example, EXAMPLE_MODEL
        else:
            try:
                result = plan_request(request, self.router, run_id=run_id, today=today or self.clock().date())
                plan, model = result.plan, result.model
            except LLMError as err:
                if not fallback_to_example:
                    self.store.save_check(run_id, "01_intent", False, str(err))
                    raise StageFailed("01_intent", str(err)) from err
                plan, model = example, f"{EXAMPLE_MODEL}: no model could answer ({type(err).__name__})"
            except PlanError as err:
                why = "; ".join(err.errors) or str(err)
                self.store.save_check(run_id, "01_intent", False, why)
                raise StageFailed("01_intent", why) from err
        self.planner_model[run_id] = model
        self.store.save(run_id, "01_intent", "plan.json", plan)
        self.store.save(run_id, "01_intent", "meta.json", {"model": model})
        passed, why = checks.intent(plan)
        self.store.save_check(run_id, "01_intent", passed, why)
        if not passed:
            raise StageFailed("01_intent", why)
        return plan

    # 02 (a failed check here is normal: it means blockers for the operator to resolve)
    def simulate(
        self, plan: ActionPlan, *, blind_spots: Iterable[str] = (), use_critic: bool = True,
        reuse_critic_from: Simulation | None = None,
    ) -> Simulation:
        blind = tuple(blind_spots)
        with self.crm.bound():  # every read of this simulation on one connection
            sim = simulate(plan, self.adapters, now=self.clock(), blind_spots=blind)
        meta: dict[str, object] = {"blind_spots": sorted(blind), "critic": None}
        if reuse_critic_from is not None:
            # A tweak only leaves items out or adds a reason: keep the critic's notes instead of paying
            # another model call (and its latency) for every click.
            notes = tuple(s for s in reuse_critic_from.side_effects if s.source == "critic")
            sim = sim.model_copy(update={"side_effects": sim.side_effects + notes})
            previous = json.loads(self.store.load(plan.run_id, "02_simulate/output/meta.json") or "{}")
            meta["critic"] = {**(previous.get("critic") or {}), "reused": True}
        elif use_critic and self.router is not None and self.router.available("critic"):
            planner = self.planner_model.get(plan.run_id) or json.loads(
                self.store.load(plan.run_id, "01_intent/output/meta.json") or "{}").get("model", "")
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


    # ---------- saved runs ----------

    def load(self, run_id: str) -> SavedRun:
        """Rebuild a run from its folder (or the database mirror)."""
        def read(path: str, model):
            text = self.store.load(run_id, path)
            return model.model_validate(json.loads(text)) if text else None

        plan = read("01_intent/output/plan.json", ActionPlan)
        sim = read("02_simulate/output/simulation.json", Simulation)
        if plan is None or sim is None:
            raise KeyError(run_id)
        meta = json.loads(self.store.load(run_id, "02_simulate/output/meta.json") or "{}")
        return SavedRun(plan, sim, read("03_present/output/decision.json", Decision),
                        read("04_execute/output/journal.json", Journal), tuple(meta.get("blind_spots", ())))

    def roll_back_completed(self, run_id: str) -> list[JournalEntry]:
        """Undo a run that finished cleanly: the 'take it all back' button after a good run."""
        saved = self.load(run_id)
        if saved.journal is None or saved.journal.outcome != "completed":
            raise ValueError("only a completed run can be rolled back this way")
        if self.store.load(run_id, "05_verify/output/rollback.json"):
            raise ValueError("this run was already rolled back")
        effects = {(e.action_index, e.record_id): e for e in saved.simulation.effects}
        done = [(effects[(j.action_index, j.item_id)],
                 ExecResult(j.status, external_ref=j.external_ref, snapshot_ref=j.snapshot_ref, detail=j.detail))
                for j in saved.journal.entries if j.phase in ("canary", "batch") and j.status == "done"]
        kinds = {i: a.kind for i, a in enumerate(saved.plan.actions)}
        undo = verifier.rollback(done, self.adapters, kinds, run_id)
        self.store.save(run_id, "05_verify", "rollback.json", {"entries": [u.model_dump(mode="json") for u in undo]})
        return undo


def colleague_credits_first_customer(crm: CrmService, sim: Simulation) -> Callable[[], None]:
    """Failure Lab, drift: after approval, a person credits the first customer BHD 2.500 by hand."""
    def change() -> None:
        first = next((e for e in sim.effects if e.system == "crm.wallet"), None)
        if first is not None:
            crm.add_ledger_entry(contact_id=first.after["contact_id"], amount_minor=2_500,
                                 currency=first.after["currency"], kind="credit", actor="human:reem",
                                 charge_id=first.record_id)
    return change


@dataclass(frozen=True)
class SavedRun:
    plan: ActionPlan
    simulation: Simulation
    decision: Decision | None
    journal: Journal | None
    blind_spots: tuple[str, ...]


def resolve_blockers(
    plan: ActionPlan, sim: Simulation, *, accept_rules_reason: str | None = None, exclude_items: bool = True
) -> ActionPlan:
    """The operator's tweaks: leave out each blocked item, apply the simulator's suggested fixes
    (e.g. the real label for a mistyped one), and accept automation rules only when a person gives
    a reason. Plan-level limits without a suggested fix can't be resolved this way."""
    exclude: dict[int, list[str]] = {}
    override: dict[int, dict[str, str]] = {}
    selectors: dict[int, dict] = {}
    for b in sim.blockers:
        if b.record_id == "plan":
            if exclude_items and "selector" in b.fix and 0 <= b.action_index < len(plan.actions):
                selectors[b.action_index] = dict(b.fix["selector"])
            continue
        if b.record_id.startswith("rule:"):
            if accept_rules_reason:
                override.setdefault(b.action_index, {})[b.record_id] = accept_rules_reason
            continue
        if exclude_items:
            exclude.setdefault(b.action_index, []).append(b.record_id)
    actions = []
    for i, action in enumerate(plan.actions):
        params = dict(action.params)
        if i in exclude:
            params["exclude"] = sorted(set(params.get("exclude", [])) | set(exclude[i]))
        if i in override:
            params["override"] = {**params.get("override", {}), **override[i]}
        actions.append(Action(kind=action.kind, selector=selectors.get(i, action.selector), params=params,
                              reason=action.reason))
    return plan.model_copy(update={"actions": tuple(actions)})
