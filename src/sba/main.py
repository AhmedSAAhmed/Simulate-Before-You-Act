"""ASGI entry point: FastAPI for health and the Telegram webhook, Gradio mounted at `/`."""

from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager

import gradio as gr
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from sba import __version__
from sba.ui.app import build_ui
from sba.ui.theme import CSS, THEME

log = logging.getLogger(__name__)
WEBHOOK_PATH = "/telegram/webhook"


def on_startup() -> None:
    """Purge expired visitors, and point Telegram at this server when it has a public URL (Render)."""
    from sba.services import get_services

    services = get_services()
    removed = services.sessions.purge_expired()
    if removed:
        log.info("purged %d expired demo sessions", removed)
    if services.public_url and services.telegram:
        services.telegram.set_webhook(services.public_url + WEBHOOK_PATH, services.webhook_secret)
        log.info("telegram webhook set for @%s", services.bot_username)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.environ.get("SBA_SKIP_STARTUP") != "1":
        try:
            on_startup()
        except Exception:  # noqa: BLE001 - the web demo should still come up if Telegram is down
            log.exception("startup tasks failed; the web demo still runs")
    yield


app = FastAPI(title="Simulate Before You Act", version=__version__, docs_url=None, redoc_url=None,
              lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    background: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    from sba.bot import Bot
    from sba.services import get_services

    services = get_services()
    given = x_telegram_bot_api_secret_token or ""
    if not services.webhook_secret or not hmac.compare_digest(given, services.webhook_secret):
        raise HTTPException(status_code=403, detail="bad secret")
    update = await request.json()
    background.add_task(Bot(services).handle, update)  # answer Telegram at once; work in the background
    return {"ok": True}


app = gr.mount_gradio_app(app, build_ui(), path="/", theme=THEME, css=CSS)
