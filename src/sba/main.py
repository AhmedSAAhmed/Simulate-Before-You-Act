"""ASGI entry point: FastAPI for health and webhooks, Gradio mounted at `/`."""

from __future__ import annotations

import gradio as gr
from fastapi import FastAPI

from sba import __version__
from sba.ui.app import build_ui
from sba.ui.theme import CSS, THEME

app = FastAPI(title="Simulate Before You Act", version=__version__, docs_url=None, redoc_url=None)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


app = gr.mount_gradio_app(app, build_ui(), path="/", theme=THEME, css=CSS)
