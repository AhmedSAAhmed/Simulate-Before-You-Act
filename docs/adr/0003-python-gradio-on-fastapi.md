# 0003 - One Python process: Gradio mounted on FastAPI

Date: 2026-11-14 · Status: accepted

## Context
The owner prefers simple Python, ideally with Gradio. The app also needs a webhook endpoint (Telegram) and a health check for Render, and must fit in 512 MB. The UI must match the Navy theme's look.

## Decision
FastAPI serves `/healthz` and webhooks; Gradio Blocks is mounted at `/` with `gr.mount_gradio_app`. The look comes from a custom Gradio theme plus a from-scratch stylesheet (`src/sba/ui/navy.css`) matching Navy's palette, type and rhythm. The page shell is HTML blocks; interactive parts are Gradio components.

## Alternatives considered
- Gradio alone: no clean place for signed webhooks.
- FastAPI + Jinja + HTMX + Tailwind: closer pixel control, but about 30% more UI work.
- A JavaScript front end: a second language and build step for little gain here.

## Consequences
- One process and one deploy; tests hit both the API and the UI mount through FastAPI's test client.
- Gradio's own component styling limits pixel fidelity inside interactive panels; the page shell carries the Navy look.
