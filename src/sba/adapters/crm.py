"""Adapters for the CRM: wallet credits (money), contact labels, contact deletion."""

from __future__ import annotations

import difflib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sba.adapters.base import (
    LABEL_RE,
    ActionSim,
    ExecResult,
    SelectorError,
    SimContext,
    Target,
    from_action_targets,
    idempotency_key,
    check_shape,
    item_controls,
)
from sba.crm.service import CrmService
from sba.domain.models import Action, ActionKind, Blocker, Effect, InvariantResult, SideEffect
from sba.domain.money import fmt
from sba.domain.policy import SOFT_DELETE_WINDOW


def _who(contact: dict[str, Any]) -> str:
    return f"{contact['name']} ({contact['id']})"


@dataclass
class CreditAdapter:
    """`issue_credit`: return a duplicate charge to the customer's wallet. Compensable."""

    crm: CrmService
    kind: ActionKind = ActionKind.ISSUE_CREDIT
    system: str = "crm.wallet"

    def simulate(self, index: int, action: Action, ctx: SimContext) -> ActionSim:
        check_shape(action, index)
        if action.selector["duplicates_only"] is not True:
            raise SelectorError("issue_credit only returns duplicate charges: set duplicates_only to true")
        try:
            day = date.fromisoformat(str(action.selector["charges_created_on"]))
        except ValueError as err:
            raise SelectorError("charges_created_on must be YYYY-MM-DD") from err
        exclude, override = item_controls(action)

        sim = ActionSim(rollback="Reverse each credit with a matching debit while the wallet still holds it. "
                                 "Credit a customer has already spent can only be recovered by asking them.")
        found = self.crm.duplicate_charges_on(day)
        ctx.read("crm", f"selector:{index}", "charge_ids", [c["id"] for c in found])
        # Three batched reads instead of three per charge.
        people = self.crm.contacts_by_ids([c["contact_id"] for c in found])
        credited_by = self.crm.credited_for_charges([c["id"] for c in found])
        balances = self.crm.wallet_balances(sorted(people))
        currencies: set[str] = set()
        total = 0
        for charge in found:
            cid, cur, amount = charge["contact_id"], charge["currency"], charge["amount_minor"]
            contact = people.get(cid) or {"id": cid, "name": "unknown contact"}
            who = _who(contact)
            credited = ctx.read("crm", charge["id"], "credited", credited_by.get(charge["id"], 0))
            disputed = ctx.read("crm", charge["id"], "disputed", bool(charge["disputed"]))
            ctx.read("crm", charge["id"], "amount", amount)
            remaining = amount - credited
            if charge["id"] in exclude:
                sim.notes.append(f"{charge['id']} for {who} left out by the operator.")
                continue
            if remaining <= 0:
                sim.notes.append(f"{charge['id']} for {who} left out automatically: already credited "
                                 f"{fmt(credited, cur)} of {fmt(amount, cur)}.")
                continue
            if disputed and charge["id"] not in override:
                sim.blockers.append(Blocker(action_index=index, record_id=charge["id"], rule="disputed",
                                            detail=f"{who}: the charge is disputed with the bank, so a credit "
                                                   f"would pay {fmt(amount, cur)} twice."))
                continue
            if credited > 0 and charge["id"] not in override:
                sim.blockers.append(Blocker(action_index=index, record_id=charge["id"], rule="partly_credited",
                                            detail=f"{who}: a person already credited {fmt(credited, cur)} of "
                                                   f"{fmt(amount, cur)}; including it credits the remaining "
                                                   f"{fmt(remaining, cur)}."))
                continue
            if charge["id"] in override:
                sim.notes.append(f"{charge['id']} for {who} included by the operator: {override[charge['id']]}")
            if cid not in ctx.balances:
                ctx.balances[cid] = ctx.read("crm", cid, "wallet_balance", balances.get(cid, 0))
            before = ctx.balances[cid]
            ctx.balances[cid] = before + remaining
            sim.effects.append(Effect(
                action_index=index, system=self.system, record_id=charge["id"], subject=who,
                before={"wallet_balance": before, "credited_for_charge": credited, "currency": cur},
                after={"wallet_balance": before + remaining, "credited_for_charge": credited + remaining,
                       "credit": remaining, "contact_id": cid, "currency": cur},
            ))
            sim.targets.append(Target(record_id=charge["id"], contact_id=cid, amount_minor=remaining, currency=cur))
            currencies.add(cur)
            total += remaining
        if len(currencies) > 1:
            sim.blockers.append(Blocker(action_index=index, record_id="plan", rule="mixed_currency", hard=True,
                                        detail=f"credits span {sorted(currencies)}; split the plan by currency"))
        sim.totals = {"credits": len(sim.effects), "credit_total_minor": total}
        if currencies:
            sim.totals["currency"] = min(currencies)
        return sim

    def execute(self, effect: Effect, *, run_id: str) -> ExecResult:
        entry = self.crm.add_ledger_entry(
            contact_id=effect.after["contact_id"], amount_minor=effect.after["credit"],
            currency=effect.after["currency"], kind="credit", actor=f"agent:{run_id}",
            charge_id=effect.record_id, run_id=run_id, idempotency_key=idempotency_key(run_id, effect),
        )
        return ExecResult("done", external_ref=f"ledger:{entry}")

    def compensate(self, effect: Effect, result: ExecResult, *, run_id: str) -> ExecResult:
        cid, credit, cur = effect.after["contact_id"], effect.after["credit"], effect.after["currency"]
        balance = self.crm.wallet_balance(cid)
        if balance < credit:
            return ExecResult("needs_recovery", detail=f"wallet holds {fmt(balance, cur)}, the credit was "
                                                       f"{fmt(credit, cur)}; draft a recovery request")
        entry = self.crm.add_ledger_entry(
            contact_id=cid, amount_minor=-credit, currency=cur, kind="reversal", actor=f"agent:{run_id}",
            charge_id=effect.record_id, run_id=run_id, idempotency_key=idempotency_key(run_id, effect, ":reverse"),
        )
        return ExecResult("rolled_back", external_ref=f"ledger:{entry}")

    def observe(self, effect: Effect) -> dict[str, Any]:
        return self.observe_many([effect])[effect.record_id]

    def observe_many(self, effects: list[Effect]) -> dict[str, dict[str, Any]]:
        # Per charge only: a wallet can hold several credits, so wallets are checked in invariants().
        credited = self.crm.credited_for_charges([e.record_id for e in effects])
        return {e.record_id: {"credited_for_charge": credited[e.record_id]} for e in effects}

    def invariants(self, effects: list[Effect], run_id: str) -> list[InvariantResult]:
        if not effects:
            return []
        ids = [e.record_id for e in effects]
        found, credited = self.crm.charges_by_ids(ids), self.crm.credited_for_charges(ids)
        over = [f"{cid} credited {credited[cid]}" for cid in ids
                if cid not in found or credited[cid] > found[cid]["amount_minor"]]
        per_charge = Counter(r["charge_id"] for r in self.crm.ledger_for_run(run_id) if r["kind"] == "credit")
        twice = sorted(c for c, n in per_charge.items() if n > 1)
        predicted: dict[str, int] = {}
        for e in effects:  # effects are in order, so the last one per wallet is its final balance
            predicted[e.after["contact_id"]] = e.after["wallet_balance"]
        actual = self.crm.wallet_balances(sorted(predicted))
        wrong = [f"{cid}: {actual[cid]} vs {want}" for cid, want in predicted.items() if actual[cid] != want]
        return [
            InvariantResult(name="credit_within_duplicate", held=not over, detail="; ".join(over)),
            InvariantResult(name="no_charge_credited_twice", held=not twice, detail=", ".join(twice)),
            InvariantResult(name="wallets_match_prediction", held=not wrong, detail="; ".join(wrong)),
        ]


@dataclass
class LabelAdapter:
    """`update_contact_attributes`: add or remove labels. Reversible; may trigger automations."""

    crm: CrmService
    recall: Callable[[str], bool] | None = None  # deletes a sent notice by its delivery ref
    kind: ActionKind = ActionKind.UPDATE_CONTACT_ATTRIBUTES
    system: str = "crm.contacts"

    def simulate(self, index: int, action: Action, ctx: SimContext) -> ActionSim:
        check_shape(action, index)
        add = _labels(action.params.get("add_labels", []), "add_labels")
        remove = _labels(action.params.get("remove_labels", []), "remove_labels")
        if not add and not remove:
            raise SelectorError("update_contact_attributes needs add_labels or remove_labels")
        exclude, override = item_controls(action)
        contact_ids = self._resolve(index, action.selector, ctx)
        ctx.read("crm", f"selector:{index}", "contact_ids", contact_ids)
        if not contact_ids and "label" in action.selector:
            return ActionSim(blockers=[no_label_match(index, action.selector["label"], self.crm)])

        sim = ActionSim(rollback="Restore each contact's previous labels from the snapshot, and close any "
                                 "tickets that automations opened because of this run.")
        rules = [] if "automations" in ctx.blind_spots else self.crm.automation_rules()
        for rule in rules:
            ctx.read("crm", f"rule:{rule['id']}", "match_text", rule["match_text"])
        fired: dict[str, list[str]] = {}
        people = self.crm.contacts_by_ids(contact_ids)  # one read for everyone
        for cid in contact_ids:
            contact = people.get(cid)
            if contact is None or contact["deleted_at"] is not None:
                continue
            who = _who(contact)
            old = ctx.read("crm", cid, "labels", sorted(contact["labels"]))
            new = sorted((set(old) - set(remove)) | set(add))
            if cid in exclude:
                sim.notes.append(f"{who} left out by the operator.")
                continue
            if new == old:
                sim.notes.append(f"{who} already has these labels; nothing to change.")
                continue
            added = [lbl for lbl in new if lbl not in old]
            for rule in rules:
                if rule["trigger"] == "label_added" and any(rule["match_text"] in lbl for lbl in added):
                    fired.setdefault(rule["id"], []).append(cid)
            sim.effects.append(Effect(action_index=index, system=self.system, record_id=cid, subject=who,
                                      before={"labels": old}, after={"labels": new}))
            sim.targets.append(Target(record_id=cid, contact_id=cid))
        names = {r["id"]: r["name"] for r in rules}
        for rule_id, hit in fired.items():
            key = f"rule:{rule_id}"
            what = (f"Automation '{names[rule_id]}' fires for {len(hit)} contacts: it opens {len(hit)} billing "
                    f"tickets and sends {len(hit)} Telegram notices.")
            sim.side_effects.append(SideEffect(description=what, likelihood="high", source="engine",
                                               expected={"tickets_opened": len(hit), "notices_sent": len(hit)}))
            if key in override:
                sim.notes.append(f"{what} Accepted by the operator: {override[key]}")
            else:
                sim.blockers.append(Blocker(action_index=index, record_id=key, rule="automation_match",
                                            detail=f"{what} Accept it with a reason, or change the labels."))
        sim.totals = {"label_changes": len(sim.effects)}
        return sim

    def _resolve(self, index: int, selector: dict[str, Any], ctx: SimContext) -> list[str]:
        if ("from_action" in selector) == ("label" in selector):
            raise SelectorError("selector needs exactly one of from_action or label")
        if "from_action" in selector:
            return sorted({t.contact_id for t in from_action_targets(index, selector, ctx)})
        return [c["id"] for c in self.crm.contacts_with_label(_labels([selector["label"]], "label")[0])]

    def execute(self, effect: Effect, *, run_id: str) -> ExecResult:
        snap = self.crm.snapshot(run_id=run_id, record_type="contact_labels", record_id=effect.record_id,
                                 data={"labels": effect.before["labels"]})
        self.crm.set_labels(effect.record_id, effect.after["labels"], actor=f"agent:{run_id}", run_id=run_id)
        return ExecResult("done", snapshot_ref=snap)

    def compensate(self, effect: Effect, result: ExecResult, *, run_id: str) -> ExecResult:
        if result.snapshot_ref is None:
            return ExecResult("failed", detail="no snapshot to restore from")
        labels = self.crm.get_snapshot(result.snapshot_ref)["data"]["labels"]
        self.crm.set_labels(effect.record_id, labels, actor=f"agent:{run_id}:rollback", run_id=run_id)
        closed = recalled = 0
        for ticket in self.crm.tickets_for_run(run_id):
            if ticket["contact_id"] == effect.record_id and ticket["status"] == "open":
                self.crm.close_ticket(ticket["id"])
                closed += 1
        for notice in self.crm.notifications_for_run(run_id):
            if notice["contact_id"] == effect.record_id and notice["delivery_ref"] and self.recall:
                recalled += int(self.recall(notice["delivery_ref"]))
        return ExecResult("rolled_back", detail=f"labels restored; {closed} automation tickets closed; "
                                                f"{recalled} notices recalled")

    def observe(self, effect: Effect) -> dict[str, Any]:
        return self.observe_many([effect])[effect.record_id]

    def observe_many(self, effects: list[Effect]) -> dict[str, dict[str, Any]]:
        people = self.crm.contacts_by_ids([e.record_id for e in effects])
        return {e.record_id: {"labels": sorted(people[e.record_id]["labels"]) if e.record_id in people else None}
                for e in effects}

    def side_observations(self, run_id: str) -> dict[str, int]:
        """Effects the CRM produced on its own because of this run (automations)."""
        opened = [t for t in self.crm.tickets_for_run(run_id) if t["source"].startswith("automation:")]
        return {"tickets_opened": len(opened), "notices_sent": len(self.crm.notifications_for_run(run_id))}


@dataclass
class DeleteAdapter:
    """`delete_contacts`: soft-delete now, purge after 24 hours. Reversible until the purge."""

    crm: CrmService
    kind: ActionKind = ActionKind.DELETE_CONTACTS
    system: str = "crm.contacts"

    def simulate(self, index: int, action: Action, ctx: SimContext) -> ActionSim:
        check_shape(action, index)
        label = _labels([action.selector["label"]], "label")[0]
        exclude, override = item_controls(action)
        purge_at = ctx.now + SOFT_DELETE_WINDOW
        found = self.crm.contacts_with_label(label)
        ctx.read("crm", f"selector:{index}", "contact_ids", [c["id"] for c in found])
        if not found:
            sim = ActionSim()
            sim.blockers.append(no_label_match(index, label, self.crm))
            return sim
        sim = ActionSim(rollback=f"Undelete from the snapshot any time before the purge at "
                                 f"{purge_at:%Y-%m-%d %H:%M} UTC; after the purge the records are gone.")
        open_by = self.crm.open_ticket_counts([c["id"] for c in found])  # one read for everyone
        for contact in found:
            who = _who(contact)
            open_count = ctx.read("crm", contact["id"], "open_tickets", open_by.get(contact["id"], 0))
            if contact["id"] in exclude:
                sim.notes.append(f"{who} left out by the operator.")
                continue
            if open_count and contact["id"] not in override:
                sim.blockers.append(Blocker(action_index=index, record_id=contact["id"], rule="open_ticket",
                                            detail=f"{who} has {open_count} open ticket(s); deleting the contact "
                                                   f"loses that conversation's context."))
                continue
            if contact["id"] in override:
                sim.notes.append(f"{who} included by the operator: {override[contact['id']]}")
            sim.effects.append(Effect(
                action_index=index, system=self.system, record_id=contact["id"], subject=who,
                before={"status": "active", "open_tickets": open_count},
                after={"status": "soft-deleted", "purge_after": purge_at.isoformat(timespec="seconds")},
            ))
            sim.targets.append(Target(record_id=contact["id"], contact_id=contact["id"]))
        sim.totals = {"deletions": len(sim.effects)}
        return sim

    def execute(self, effect: Effect, *, run_id: str) -> ExecResult:
        contact = self.crm.contact(effect.record_id)
        if contact is None:
            return ExecResult("failed", detail="contact no longer exists")
        snap = self.crm.snapshot(run_id=run_id, record_type="contact", record_id=effect.record_id,
                                 data={"labels": contact["labels"], "deleted_at": None})
        self.crm.soft_delete(effect.record_id, purge_after=datetime.fromisoformat(effect.after["purge_after"]))
        return ExecResult("done", snapshot_ref=snap)

    def compensate(self, effect: Effect, result: ExecResult, *, run_id: str) -> ExecResult:
        contact = self.crm.contact(effect.record_id)
        if contact is None:
            return ExecResult("failed", detail="already purged; nothing to restore")
        self.crm.undelete(effect.record_id)
        return ExecResult("rolled_back", detail="contact restored")

    def observe(self, effect: Effect) -> dict[str, Any]:
        return self.observe_many([effect])[effect.record_id]

    def observe_many(self, effects: list[Effect]) -> dict[str, dict[str, Any]]:
        people = self.crm.contacts_by_ids([e.record_id for e in effects])

        def status(cid: str) -> str:
            if cid not in people:
                return "purged"
            return "soft-deleted" if people[cid]["deleted_at"] else "active"

        return {e.record_id: {"status": status(e.record_id)} for e in effects}


def no_label_match(index: int, label: str, crm: CrmService) -> Blocker:
    """A label selector that matches nothing usually means a typo, so name the closest real label."""
    counts = crm.label_counts()
    close = difflib.get_close_matches(label, list(counts), n=1, cutoff=0.6)
    hint = f" Did you mean '{close[0]}' ({counts[close[0]]} contacts)?" if close else ""
    return Blocker(action_index=index, record_id="plan", rule="empty_selector", hard=True,
                   detail=f"action {index}: no contact has the label '{label}', so it would do nothing.{hint}",
                   fix={"selector": {"label": close[0]}} if close else {})


def _labels(value: Any, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and LABEL_RE.match(v) for v in value):
        raise SelectorError(f"{where} must be a list of lowercase labels (a-z, 0-9, '-')")
    return list(value)
