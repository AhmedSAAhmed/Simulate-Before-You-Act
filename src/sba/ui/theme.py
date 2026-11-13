"""Gradio theme matching the Navy-style tokens in navy.css (light only)."""

from __future__ import annotations

from pathlib import Path

import gradio as gr

CSS = (Path(__file__).with_name("navy.css")).read_text(encoding="utf-8")

PAPER, CARD, SURFACE, LINE = "#f8f7f4", "#ffffff", "#eceae6", "#e4e1db"
INK, MUTED, NAVY = "#1a1815", "#77746f", "#03051a"
FONT = ["Switzer", "Helvetica Neue", "Helvetica", "Arial", "sans-serif"]


def _same_in_dark(**values: str) -> dict[str, str]:
    """Set each variable and its `_dark` twin, so OS dark mode can't flip the palette."""
    out = dict(values)
    out.update({f"{k}_dark": v for k, v in values.items()})
    return out


THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.blue,
    neutral_hue=gr.themes.colors.stone,
    radius_size=gr.themes.sizes.radius_sm,
    font=FONT,
).set(
    **_same_in_dark(
        body_background_fill=PAPER,
        body_text_color=INK,
        body_text_color_subdued=MUTED,
        background_fill_primary=CARD,
        background_fill_secondary=PAPER,
        block_background_fill=CARD,
        block_border_color=LINE,
        border_color_primary=LINE,
        input_background_fill=CARD,
        input_border_color=LINE,
        button_primary_background_fill=NAVY,
        button_primary_background_fill_hover=INK,
        button_primary_text_color="#ffffff",
        button_secondary_background_fill=SURFACE,
        button_secondary_text_color=INK,
    )
)
