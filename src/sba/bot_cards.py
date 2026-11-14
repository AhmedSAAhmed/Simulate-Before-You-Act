"""Telegram messages for the bot: HTML text plus inline buttons.

Every button that acts on a plan carries the run id and the first 8 characters of the plan
hash it was drawn for. A button from an older card is refused (ADR 0001, in the chat).
"""

from __future__ import annotations

from html import escape

from sba.agents.executor import ExecutionResult
from sba.domain.models import ActionKind, ActionPlan, JournalEntry, Simulation
from sba.domain.money import fmt

LIMIT = 3_900  # under Telegram's 4,096, with room for the footer

SHORT_UNDO = {
    ActionKind.ISSUE_CREDIT: "credits: a matching debit, while the wallet still holds them",
    ActionKind.SEND_MESSAGE: "messages: recalled within 48 hours",
    ActionKind.UPDATE_CONTACT_ATTRIBUTES: "tags: restored from a snapshot",
    ActionKind.DELETE_CONTACTS: "deletions: undone any time in the next 24 hours",
}

WELCOME = (
    "👋 <b>Simulate Before You Act</b>, a DOO-style ops agent that rehearses every change before it makes it.\n\n"
    "You have your own copy of a small CRM: yesterday 9 customers were charged twice. You're customer "
    "#1, and this chat is the demo inbox, so the agent's messages land here (and nowhere else).\n\n"
    "Send a request in your own words, or tap the example. I'll show what would change, who is "
    "affected and how to undo it. Nothing runs until you approve.\n\n"
    "<i>Commands: /demo example · /reset fresh data · /forget delete your data · /help</i>\n"
    "<i>Privacy: I keep your chat id and first name, and delete everything after 7 days.</i>"
)
HELP = (
    "Try: <i>Credit back everyone who was double-charged yesterday, apologize in their language, tag them "
    "dup-charge-2026-11, and delete the spam leads from yesterday's import.</i>\n\n"
    "The agent can only issue wallet credits, send messages, change tags and soft-delete contacts, "
    "inside your own demo copy.\n\n/demo example · /reset fresh data · /forget delete your data"
)
EXAMPLE_BUTTON = {"inline_keyboard": [[{"text": "▶️ Try the example request", "callback_data": "ex"}]]}


def can_leave_out(sim: Simulation) -> bool:
    """True when 'leave out & apply fixes' would change something: a blocked item, or a suggested fix."""
    return any((b.record_id != "plan" and not b.record_id.startswith("rule:")) or (b.record_id == "plan" and b.fix)
               for b in sim.blockers)


def _data(op: str, sim: Simulation, run_id: str) -> str:
    return f"{op}:{run_id}:{sim.plan_hash[:8]}"


def simulation_card(
    plan: ActionPlan, sim: Simulation, *, model: str, web_url: str | None = None, blind: bool = False
) -> tuple[str, dict]:
    t, cur = sim.totals, sim.totals.get("currency", "BHD")
    lines = [f"🧪 <b>Simulation</b> · <b>{sim.tier.value}</b> risk",
             f"<i>“{escape(plan.request[:180])}”</i>", ""]
    if blind:
        lines += ["🙈 <i>Failure lab: in this run the simulator can't see the CRM's automation rules.</i>", ""]
    lines += ["<b>What would change</b>",
              f"• {t.get('credits', 0)} wallet credits, {fmt(t.get('credit_total_minor', 0), cur)} in total",
              f"• {t.get('messages', 0)} messages · {t.get('label_changes', 0)} tag changes · "
              f"{t.get('deletions', 0)} soft-deletions",
              f"• {len(sim.impacted)} people or records affected"]
    held = sum(1 for e in sim.effects if e.after.get("route", "").startswith("held"))
    if held:
        lines.append(f"• {held} messages are held: link Telegram in the web demo to send them")
    if sim.blockers:
        lines += ["", f"⛔ <b>{len(sim.blockers)} blocker(s)</b>: Approve stays off until each is resolved"]
        lines += [f"• <b>{escape(b.rule)}</b>{' (leave out only)' if b.hard else ''}: {escape(b.detail)}"
                  for b in sim.blockers[:8]]
    if sim.side_effects:
        lines += ["", "⚠️ <b>Side effects</b>"]
        lines += [f"• <i>{s.source}</i>: {escape(s.description)}" for s in sim.side_effects[:5]]
    kinds = {a.kind for a in plan.actions}
    lines += ["", "↩️ <b>How to undo</b>"] + [f"• {SHORT_UNDO[k]}" for k in ActionKind if k in kinds]
    lines += ["", f"<code>plan {sim.plan_hash[:8]} · state {sim.state_fingerprint[:8]}</code>",
              f"<i>Planner: {escape(model)}</i>"]

    rows: list[list[dict]] = []
    if sim.blockers:
        if can_leave_out(sim):
            rows.append([{"text": "Leave out blocked items & apply fixes",
                          "callback_data": _data("x", sim, plan.run_id)}])
        if any(b.record_id.startswith("rule:") for b in sim.blockers):
            rows.append([{"text": "Accept the automation", "callback_data": _data("y", sim, plan.run_id)}])
        if any(b.record_id == "plan" and not b.fix for b in sim.blockers):
            lines.append("\n✏️ <i>A blocker needs a different request: rephrase it and send it again.</i>")
    else:
        rows.append([{"text": "✅ Approve and run", "callback_data": _data("a", sim, plan.run_id)}])
        lab = [{"text": "🧪 Drift after approval", "callback_data": _data("fd", sim, plan.run_id)}]
        if not blind:
            lab.append({"text": "🧪 Hide automations", "callback_data": _data("fb", sim, plan.run_id)})
        rows.append(lab)
    rows.append([{"text": "Reject", "callback_data": _data("n", sim, plan.run_id)}])
    if web_url:
        rows.append([{"text": "Open the web demo (full diff)", "url": web_url}])
    return _fit("\n".join(lines)), {"inline_keyboard": rows}


def result_card(result: ExecutionResult, plan: ActionPlan) -> tuple[str, dict | None]:
    v, j = result.verification, result.journal
    writes = sum(1 for e in j.entries if e.phase in ("canary", "batch") and e.status == "done")
    if v.outcome == "match":
        checks = " · ".join(("✔ " if c.held else "✘ ") + c.name.replace("_", " ") for c in v.invariants)
        text = (f"✅ <b>Done.</b> {writes} writes ran and matched the prediction.\n"
                f"Canary first, then the rest. {escape(checks)}\n\n"
                "Tap below to take it all back and watch the messages disappear.")
        return text, {"inline_keyboard": [[{"text": "↩️ Roll back everything",
                                            "callback_data": f"u:{plan.run_id}"}]]}
    if v.outcome == "drift":
        return (f"⚠️ <b>The data changed after you approved.</b> Nothing was written.\n"
                f"{len(v.diffs)} difference(s) found. Here's the new simulation; approve it again if it "
                "still looks right."), None
    if v.outcome in ("rolled_back", "halted"):
        extra = ", ".join(f"{n} unpredicted {k.replace('_', ' ')}" for k, n in v.unpredicted.items())
        undone = sum(1 for u in v.rollback if u.status == "rolled_back")
        text = (f"🛑 <b>Stopped by the safety net.</b> {escape(v.summary)}\n\n"
                + (f"What the simulator missed: {escape(extra)}.\n" if extra else "")
                + f"Undone: {undone} of {len(v.rollback)} writes"
                + (" (the messages above were recalled)." if any("recalled" in u.detail for u in v.rollback)
                   else "."))
        return _fit(text), None
    return f"⛔ <b>Not run.</b> {escape(v.summary)}", None


def rollback_card(entries: list[JournalEntry]) -> str:
    ok = [e for e in entries if e.status == "rolled_back"]
    rest = [e for e in entries if e.status != "rolled_back"]
    text = f"↩️ <b>Rolled back.</b> {len(ok)} of {len(entries)} writes undone; recalled messages are gone above."
    if rest:
        text += "\n\nNeeds a person:\n" + "\n".join(f"• {escape(e.item_id)}: {escape(e.detail)}" for e in rest)
    return _fit(text)


def _fit(text: str) -> str:
    return text if len(text) <= LIMIT else text[:LIMIT - 1] + "…"
