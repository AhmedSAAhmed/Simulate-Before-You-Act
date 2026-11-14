"""What each web button does. Plain functions over `Services`, so they're testable without a browser."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace

from sba.bot_cards import can_leave_out
from sba.crm.seed import DEMO_REQUEST
from sba.pipeline import StageFailed, colleague_credits_first_customer, resolve_blockers
from sba.services import Services
from sba.sessions import RunLimit, Session
from sba.store.approvals import ApprovalError
from sba.ui import render

log = logging.getLogger(__name__)
STALE = "This screen is out of date: the plan changed (perhaps from Telegram). Simulate again to review it."


@dataclass(frozen=True)
class View:
    run_id: str | None = None
    shown_hash: str | None = None
    review_html: str = ""
    result_html: str = ""
    notice: str = ""
    can_approve: bool = False
    can_leave_out: bool = False
    can_accept: bool = False
    can_roll_back: bool = False


@dataclass
class WebActions:
    services: Services

    # ---------- session and Telegram card ----------

    def session(self, session_id: str | None) -> Session:
        found = self.services.sessions.get(session_id)
        return found or self.services.sessions.create()

    def telegram(self, session: Session, code: str | None) -> tuple[str, str | None]:
        """The phone card, and the link code it shows (kept until the phone is linked)."""
        if session.linked:
            return render.telegram_card(None, session.first_name, True), None
        if self.services.bot_link() and not code:  # bot_link() also retries the bot lookup
            code = self.services.sessions.new_link_code(session)
        return render.telegram_card(self.services.bot_link(code) if code else None, None, False), code

    def reset(self, session_id: str) -> str:
        self.services.sessions.reset(self.session(session_id))
        return "Fresh scenario loaded: 9 double-charged customers, wallets back to how they were."

    # ---------- the run ----------

    def simulate(self, session_id: str, request: str, blind: bool) -> View:
        session = self.session(session_id)
        request = (request or "").strip() or DEMO_REQUEST
        try:
            with self.services.sessions.slot(session, new_run=True):
                pipe = self.services.pipeline(session)
                run_id = self.services.store.new_run_id(self.services.clock())
                self.services.sessions.remember_run(session, run_id)
                plan = pipe.plan(request, fallback_to_example=True, run_id=run_id)
                sim = pipe.simulate(plan, blind_spots=("automations",) if blind else ())
        except StageFailed as err:
            return View(notice=f"Couldn't turn that into something this demo can do: {err.why[:300]}")
        except RunLimit as err:
            return View(notice=str(err))
        return self._review(plan, sim, blind)

    def leave_out(self, session_id: str, run_id: str | None, shown_hash: str | None) -> View:
        return self._tweak(session_id, run_id, shown_hash, exclude=True, reason=None)

    def accept(self, session_id: str, run_id: str | None, shown_hash: str | None, reason: str) -> View:
        reason = (reason or "").strip()
        if not reason:
            return View(run_id=run_id, shown_hash=shown_hash, notice="Accepting an automation needs a reason.")
        return self._tweak(session_id, run_id, shown_hash, exclude=False, reason=reason[:200])

    def approve(self, session_id: str, run_id: str | None, shown_hash: str | None, approver: str,
                drift: bool) -> View:
        loaded = self._load(session_id, run_id, shown_hash)
        if isinstance(loaded, View):
            return loaded
        session, pipe, saved = loaded
        try:
            with self.services.sessions.slot(session, new_run=False):
                decision = pipe.decide(saved.plan, saved.simulation, approver=approver or "Web reviewer",
                                       verdict="approve")
                before = colleague_credits_first_customer(pipe.crm, saved.simulation) if drift else None
                result = pipe.execute(saved.plan, saved.simulation, decision, blind_spots=saved.blind_spots,
                                      before_writes=before)
                fresh = pipe.simulate(saved.plan, blind_spots=saved.blind_spots, reuse_critic_from=saved.simulation) \
                    if result.verification.outcome == "drift" else None
        except (ApprovalError, RunLimit) as err:
            return View(run_id=run_id, shown_hash=shown_hash, notice=str(err))
        if fresh is not None:  # show what changed, ready to approve again
            return replace(self._review(saved.plan, fresh, bool(saved.blind_spots)),
                           result_html=render.result(result))
        return View(run_id=run_id, result_html=render.result(result),
                    can_roll_back=result.verification.outcome == "match")

    def reject(self, session_id: str, run_id: str | None, shown_hash: str | None, approver: str) -> View:
        loaded = self._load(session_id, run_id, shown_hash)
        if isinstance(loaded, View):
            return loaded
        _, pipe, saved = loaded
        pipe.decide(saved.plan, saved.simulation, approver=approver or "Web reviewer", verdict="reject")
        return View(notice="Rejected. Nothing was written.")

    def roll_back(self, session_id: str, run_id: str | None) -> View:
        session = self.session(session_id)
        if not run_id or not self.services.sessions.owns(session, run_id):
            return View(notice="There's no run of yours to roll back.")
        try:
            with self.services.sessions.slot(session, new_run=False):
                entries = self.services.pipeline(session).roll_back_completed(run_id)
        except (ValueError, RunLimit) as err:
            return View(run_id=run_id, notice=str(err))
        return View(run_id=run_id, result_html=render.rolled_back(entries))

    # ---------- helpers ----------

    def _tweak(self, session_id, run_id, shown_hash, *, exclude: bool, reason: str | None) -> View:
        loaded = self._load(session_id, run_id, shown_hash)
        if isinstance(loaded, View):
            return loaded
        session, pipe, saved = loaded
        tweaked = resolve_blockers(saved.plan, saved.simulation, exclude_items=exclude, accept_rules_reason=reason)
        try:
            with self.services.sessions.slot(session, new_run=False):
                sim = pipe.simulate(tweaked, blind_spots=saved.blind_spots, reuse_critic_from=saved.simulation)
        except RunLimit as err:
            return View(run_id=run_id, shown_hash=shown_hash, notice=str(err))
        return self._review(tweaked, sim, bool(saved.blind_spots))

    def _load(self, session_id, run_id, shown_hash):
        session = self.session(session_id)
        if not run_id or not self.services.sessions.owns(session, run_id):
            return View(notice="Simulate something first.")
        pipe = self.services.pipeline(session)
        saved = pipe.load(run_id)
        if shown_hash != saved.simulation.plan_hash:
            return View(notice=STALE)
        return session, pipe, saved

    def _review(self, plan, sim, blind: bool) -> View:
        meta = json.loads(self.services.store.load(plan.run_id, "02_simulate/output/meta.json") or "{}")
        model = json.loads(self.services.store.load(plan.run_id, "01_intent/output/meta.json") or "{}").get("model", "")
        critic = (meta.get("critic") or {}).get("model")
        html = render.review(plan, sim, model=model, critic=critic, blind=blind)
        return View(
            run_id=plan.run_id, shown_hash=sim.plan_hash, review_html=html,
            can_approve=not sim.blockers,
            can_leave_out=can_leave_out(sim),
            can_accept=any(b.record_id.startswith("rule:") for b in sim.blockers),
        )
