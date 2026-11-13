"""The Gradio UI. Phase 0: the page shell, pipeline and live system status."""

from __future__ import annotations

import gradio as gr

from sba.config import settings
from sba.ui import sections

EXAMPLE_REQUEST = (
    "Credit back everyone who was double-charged yesterday, apologize on Telegram in their language, "
    "and tag them dup-charge-2026-11."
)


def _not_ready(request: str) -> str:
    if not request.strip():
        return "Write a request first."
    return "The simulation engine arrives in Phase 1. Nothing was sent to any system."


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Simulate Before You Act") as demo:
        gr.HTML(sections.hero(), elem_classes="sba-html")
        gr.HTML(sections.pipeline(), elem_classes="sba-html")
        gr.HTML(sections.systems(settings.systems()), elem_classes="sba-html")
        gr.HTML(sections.try_intro(), elem_classes="sba-html")
        with gr.Column(elem_classes="sba-panel"):
            request = gr.Textbox(label="Request", value=EXAMPLE_REQUEST, lines=3)
            simulate = gr.Button("Simulate", variant="primary")
            note = gr.Markdown("Simulation shows effects, side effects and rollback before anything runs.",
                               elem_classes="sba-note")
        simulate.click(_not_ready, inputs=request, outputs=note)
        gr.HTML(sections.footer(), elem_classes="sba-html")
    return demo
