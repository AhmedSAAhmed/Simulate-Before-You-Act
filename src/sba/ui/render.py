"""HTML for the review screen: one screen, one decision (stages/03_present/CONTEXT.md)."""

from __future__ import annotations

from html import escape

import segno

from sba.agents.executor import ExecutionResult
from sba.domain.models import ActionKind, ActionPlan, Effect, JournalEntry, Simulation
from sba.domain.money import count_phrase, fmt

KIND_TITLE = {
    ActionKind.ISSUE_CREDIT: "Wallet credits",
    ActionKind.SEND_MESSAGE: "Messages",
    ActionKind.UPDATE_CONTACT_ATTRIBUTES: "Tag changes",
    ActionKind.DELETE_CONTACTS: "Contact deletions",
}


def empty_review() -> str:
    return ('<div class="sba-review sba-muted">Run a simulation to see what would change, who is affected, '
            "and how to undo it. Nothing is written until you approve.</div>")


def review(plan: ActionPlan, sim: Simulation, *, model: str, critic: str | None, blind: bool) -> str:
    t, cur = sim.totals, sim.totals.get("currency", "BHD")
    chips = "".join(f'<span class="sba-chip"><b>{v}</b> {escape(k)}</span>' for k, v in (
        ("credits", t.get("credits", 0)), (fmt(t.get("credit_total_minor", 0), cur), ""),
        ("messages", t.get("messages", 0)), ("tag changes", t.get("label_changes", 0)),
        ("deletions", t.get("deletions", 0)), ("affected", len(sim.impacted))))
    parts = [
        '<div class="sba-review">',
        f'<div class="sba-review-head"><span class="sba-tier sba-tier-{sim.tier.value.lower()}">'
        f"{sim.tier.value} risk</span><span class='sba-request'>“{escape(plan.request)}”</span></div>",
        f'<div class="sba-chips">{chips}</div>',
    ]
    if blind:
        parts.append('<div class="sba-box sba-lab">Failure lab: in this run the simulator can’t see the CRM’s '
                     "automation rules, so it will under-predict. Watch the canary catch it.</div>")
    if sim.blockers:
        items = "".join(f"<li><span class='sba-rule'>{escape(b.rule)}</span>"
                        f"{' <span class=sba-hard>leave out only</span>' if b.hard else ''} {escape(b.detail)}</li>"
                        for b in sim.blockers)
        parts.append(f'<div class="sba-box sba-block"><h4>{len(sim.blockers)} blocker(s): Approve stays off '
                     f"until each is resolved</h4><ul>{items}</ul></div>")
    else:
        parts.append('<div class="sba-box sba-clear">No blockers. Approving releases exactly this plan '
                     f"(<code>{sim.plan_hash[:12]}</code>) against this state "
                     f"(<code>{sim.state_fingerprint[:12]}</code>), for 10 minutes.</div>")
    if sim.side_effects:
        items = "".join(f"<li><span class='sba-src'>{escape(s.source)} · {escape(s.likelihood)}</span> "
                        f"{escape(s.description)}</li>" for s in sim.side_effects)
        parts.append(f'<div class="sba-box sba-side"><h4>Side effects</h4><ul>{items}</ul></div>')
    for index, action in enumerate(plan.actions):
        rows = [e for e in sim.effects if e.action_index == index]
        parts.append(_action_table(index, action.kind, rows))
    if sim.notes:
        parts.append('<details class="sba-notes"><summary>Left out or included, and why '
                     f"({len(sim.notes)})</summary><ul>"
                     + "".join(f"<li>{escape(n)}</li>" for n in sim.notes) + "</ul></details>")
    parts.append('<div class="sba-box"><h4>How to undo</h4><ul>'
                 + "".join(f"<li>{escape(r.split(': ', 1)[-1])}</li>" for r in sim.rollback) + "</ul></div>")
    parts.append(f'<div class="sba-foot">Planner: {escape(model)} · Critic: {escape(critic or "not used")}</div>')
    parts.append("</div>")
    return "".join(parts)


def _action_table(index: int, kind: ActionKind, rows: list[Effect]) -> str:
    head = f'<h4 class="sba-act">{index + 1}. {KIND_TITLE[kind]} <span>({len(rows)})</span></h4>'
    if not rows:
        return head + '<p class="sba-muted">Nothing would change here.</p>'
    body = "".join(f"<tr><td>{escape(e.subject)}</td>{_cells(kind, e)}</tr>" for e in rows)
    return (f'{head}<table class="sba-diff"><thead><tr><th>Who</th><th>Before</th><th>After</th></tr></thead>'
            f"<tbody>{body}</tbody></table>")


def _cells(kind: ActionKind, e: Effect) -> str:
    if kind is ActionKind.ISSUE_CREDIT:
        c = e.after["currency"]
        return (f"<td class='sba-old'>{fmt(e.before['wallet_balance'], c)}</td>"
                f"<td class='sba-new'>{fmt(e.after['wallet_balance'], c)} <b>+{fmt(e.after['credit'], c)}</b></td>")
    if kind is ActionKind.SEND_MESSAGE:
        lang = e.after["language"]
        return (f"<td class='sba-old'>no message</td><td><div class='sba-route'>{escape(e.after['route'])} · {lang}"
                f"</div><div class='sba-msg' dir='{'rtl' if lang == 'ar' else 'ltr'}' lang='{lang}'>"
                f"{escape(e.after['text'])}</div></td>")
    if kind is ActionKind.UPDATE_CONTACT_ATTRIBUTES:
        old, new = set(e.before["labels"]), set(e.after["labels"])
        tags = "".join(f"<span class='sba-tag-add'>+{escape(t)}</span>" for t in sorted(new - old))
        tags += "".join(f"<span class='sba-tag-del'>−{escape(t)}</span>" for t in sorted(old - new))
        return f"<td class='sba-old'>{escape(', '.join(sorted(old)) or 'no tags')}</td><td>{tags}</td>"
    return (f"<td class='sba-old'>active</td><td class='sba-new'>soft-deleted, purged "
            f"{escape(e.after['purge_after'][:16].replace('T', ' '))} UTC</td>")


def result(res: ExecutionResult) -> str:
    v, j = res.verification, res.journal
    writes = sum(1 for e in j.entries if e.phase in ("canary", "batch") and e.status == "done")
    tone = {"match": "ok", "drift": "warn", "rolled_back": "warn", "halted": "bad", "refused": "bad"}[v.outcome]
    title = {"match": f"Done: {writes} writes ran and matched the prediction",
             "drift": "The data changed after approval: nothing was written",
             "rolled_back": "Stopped by the safety net, and rolled back",
             "halted": "Stopped: some items need a person",
             "refused": "Not run"}[v.outcome]
    parts = [f'<div class="sba-result sba-result-{tone}"><h4>{escape(title)}</h4><p>{escape(v.summary)}</p>']
    if v.unpredicted:
        parts.append("<p><b>What the simulator missed:</b> " + ", ".join(
            escape(count_phrase(n, k)) for k, n in v.unpredicted.items()) + "</p>")
    if v.invariants:
        parts.append("<ul class='sba-checks'>" + "".join(
            f"<li>{'✔' if c.held else '✘'} {escape(c.name.replace('_', ' '))}</li>" for c in v.invariants) + "</ul>")
    if v.diffs:
        parts.append("<details><summary>Differences (" + str(len(v.diffs)) + ")</summary><ul>" + "".join(
            f"<li>{escape(d.record_id)}: {escape(d.field)}</li>" for d in v.diffs) + "</ul></details>")
    if v.rollback:
        parts.append(_undo_list(list(v.rollback)))
    parts.append(f"<div class='sba-foot'>Run {escape(j.run_id)} · journal: {len(j.entries)} entries</div></div>")
    return "".join(parts)


def rolled_back(entries: list[JournalEntry]) -> str:
    ok = sum(1 for e in entries if e.status == "rolled_back")
    return (f'<div class="sba-result sba-result-warn"><h4>Rolled back: {ok} of {len(entries)} writes undone</h4>'
            + _undo_list(entries) + "</div>")


def _undo_list(entries: list[JournalEntry]) -> str:
    return ("<details><summary>Undo log (" + str(len(entries)) + ")</summary><ul>" + "".join(
        f"<li>{escape(e.item_id)}: {escape(e.status)} {escape(e.detail)}</li>" for e in entries) + "</ul></details>")


def telegram_card(link: str | None, linked_name: str | None, linked: bool) -> str:
    if linked:
        who = escape(linked_name or "your Telegram")
        return ('<div class="sba-tg sba-tg-on"><p class="sba-eyebrow">/// On your phone</p>'
                f"<h4>Connected as {who}</h4><p>Messages from your runs go to your Telegram chat, and only there. "
                "You can also run and approve from the chat.</p></div>")
    if not link:
        return ('<div class="sba-tg"><p class="sba-eyebrow">/// On your phone</p><h4>Telegram isn’t configured on '
                "this server</h4><p>Messages are held and shown here instead.</p></div>")
    qr = segno.make(link, error="m").svg_inline(scale=3, dark="#1a1815", light="#ffffff", border=2)
    return ('<div class="sba-tg"><p class="sba-eyebrow">/// Try it on your phone</p>'
            "<h4>See the real messages arrive</h4>"
            f'<div class="sba-qr">{qr}</div>'
            f'<a class="sba-btn-tg" href="{escape(link)}" target="_blank" rel="noopener">Open in Telegram</a>'
            "<p>Scan or tap, then press Start. Your phone becomes this demo’s inbox: the agent can only message "
            "you. Until then, messages are held and shown here.</p></div>")
