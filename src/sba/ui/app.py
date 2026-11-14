"""The Gradio UI: page shell, the review screen, and the Telegram card."""

from __future__ import annotations

import logging
from collections.abc import Callable

import gradio as gr

from sba.config import settings
from sba.crm.seed import DEMO_REQUEST
from sba.ui import render, sections
from sba.ui.actions import View, WebActions

log = logging.getLogger(__name__)
EXAMPLE_REQUEST = DEMO_REQUEST


def build_ui(actions_factory: Callable[[], WebActions] | None = None) -> gr.Blocks:
    """`actions_factory` is called on first use, so building the page never touches the network."""

    def act() -> WebActions:
        if actions_factory is not None:
            return actions_factory()
        from sba.services import get_services

        return WebActions(get_services())

    with gr.Blocks(title="Simulate Before You Act") as demo:
        sid = gr.BrowserState(None, storage_key="sba-session", secret=settings.browser_secret)
        run_id, shown_hash, link_code = gr.State(None), gr.State(None), gr.State(None)

        gr.HTML(sections.hero(), elem_classes="sba-html")
        gr.HTML(sections.pipeline(), elem_classes="sba-html")
        gr.HTML(sections.systems(settings.systems()), elem_classes="sba-html")
        gr.HTML(sections.try_intro(), elem_classes="sba-html")

        with gr.Row(elem_classes="sba-panel"):
            with gr.Column(scale=3):
                request = gr.Textbox(label="Request", value=EXAMPLE_REQUEST, lines=3)
                blind = gr.Checkbox(label="Failure lab: hide the CRM's automation rules from the simulator",
                                    value=False)
                simulate = gr.Button("Simulate", variant="primary")
            with gr.Column(scale=2):
                tg_card = gr.HTML(render.telegram_card(None, None, False), elem_classes="sba-html")
                new_link = gr.Button("New Telegram link", size="sm", variant="secondary")

        with gr.Column(elem_classes="sba-panel"):
            notice = gr.Markdown("", elem_classes="sba-note")
            review = gr.HTML(render.empty_review(), elem_classes="sba-html")
            with gr.Row():
                leave_out = gr.Button("Leave out blocked items / apply fixes", interactive=False)
                reason = gr.Textbox(label="Reason to accept the automation", scale=2,
                                    value="Billing wants a ticket for every affected customer")
                accept = gr.Button("Accept the automation", interactive=False)
            with gr.Row():
                approver = gr.Textbox(label="Approve as", value="Reviewer", scale=1)
                drift = gr.Checkbox(label="Failure lab: a colleague credits a customer right after you approve",
                                    value=False, scale=2)
            with gr.Row():
                approve = gr.Button("Approve and run", variant="primary", interactive=False)
                reject = gr.Button("Reject", variant="secondary", interactive=False)
            result = gr.HTML("", elem_classes="sba-html")
            with gr.Row():
                roll_back = gr.Button("Roll back this run", interactive=False)
                reset = gr.Button("Reset my demo data", size="sm", variant="secondary")
        gr.HTML(sections.footer(), elem_classes="sba-html")

        view_outputs = [run_id, shown_hash, review, result, notice, approve, reject, leave_out, accept, roll_back]

        def show(view: View, keep_review: str | None = None):
            has_run = bool(view.shown_hash)
            return (view.run_id, view.shown_hash,
                    view.review_html or keep_review or render.empty_review(),
                    view.result_html, view.notice,
                    gr.Button(interactive=view.can_approve), gr.Button(interactive=has_run and not view.result_html),
                    gr.Button(interactive=view.can_leave_out), gr.Button(interactive=view.can_accept),
                    gr.Button(interactive=view.can_roll_back))

        def on_load(session_id):
            a = act()
            session = a.session(session_id)
            card, code = a.telegram(session, None)
            return session.id, card, code

        def on_tick(session_id, code):
            if not session_id or not code:
                return gr.skip(), code  # nothing pending: leave the card as it is
            a = act()
            session = a.session(session_id)
            if session.linked:  # the phone just pressed Start: swap the QR for "connected"
                card, _ = a.telegram(session, None)
                return card, None
            return gr.skip(), code

        def on_new_link(session_id):
            a = act()
            card, code = a.telegram(a.session(session_id), None)
            return card, code

        demo.load(on_load, inputs=sid, outputs=[sid, tg_card, link_code])
        gr.Timer(4).tick(on_tick, inputs=[sid, link_code], outputs=[tg_card, link_code])
        new_link.click(on_new_link, inputs=sid, outputs=[tg_card, link_code])
        simulate.click(lambda s, r, b: show(act().simulate(s, r, b)), inputs=[sid, request, blind],
                       outputs=view_outputs)
        leave_out.click(lambda s, rid, h, cur: show(act().leave_out(s, rid, h), cur),
                        inputs=[sid, run_id, shown_hash, review], outputs=view_outputs)
        accept.click(lambda s, rid, h, why, cur: show(act().accept(s, rid, h, why), cur),
                     inputs=[sid, run_id, shown_hash, reason, review], outputs=view_outputs)
        approve.click(lambda s, rid, h, who, d, cur: show(act().approve(s, rid, h, who, d), cur),
                      inputs=[sid, run_id, shown_hash, approver, drift, review], outputs=view_outputs)
        reject.click(lambda s, rid, h, who: show(act().reject(s, rid, h, who)),
                     inputs=[sid, run_id, shown_hash, approver], outputs=view_outputs)
        roll_back.click(lambda s, rid, cur: show(act().roll_back(s, rid), cur),
                        inputs=[sid, run_id, review], outputs=view_outputs)
        reset.click(lambda s: act().reset(s), inputs=sid, outputs=notice)
    return demo
