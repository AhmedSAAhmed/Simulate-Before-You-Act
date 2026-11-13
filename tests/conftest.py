from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from sba.adapters.registry import build_adapters
from sba.adapters.telegram import TelegramClient
from sba.crm.schema import make_engine
from sba.crm.seed import seed_demo
from sba.crm.service import CrmService

YOUR_CHAT = "111"
DEMO_CHAT = "999"
NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)


class FakeTelegram:
    """In-memory Bot API: records sends and deletes; chats in `blocked` refuse the bot."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, int]] = []
        self.deleted: list[tuple[str, int]] = []
        self.blocked: set[str] = set()
        self.network_down = False
        self.calls: list[str] = []
        self._next = 100

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        self.calls.append(method)
        if self.network_down:
            raise httpx.ConnectError("connection reset", request=request)
        body = json.loads(request.content or b"{}")
        chat = str(body.get("chat_id"))
        if chat in self.blocked:
            return httpx.Response(200, json={"ok": False, "error_code": 403, "description": "Forbidden: blocked"})
        if method == "getChat":
            return httpx.Response(200, json={"ok": True, "result": {"id": int(chat)}})
        if method == "sendMessage":
            self._next += 1
            self.sent.append((chat, body["text"], self._next))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": self._next}})
        if method == "deleteMessage":
            self.deleted.append((chat, body["message_id"]))
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(404, json={"ok": False, "description": "unknown method"})


@pytest.fixture
def crm() -> CrmService:
    service = CrmService(make_engine("sqlite://"), clock=lambda: NOW)
    seed_demo(service, your_chat_id=YOUR_CHAT)
    return service


@pytest.fixture
def fake_telegram() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def adapters(crm: CrmService, fake_telegram: FakeTelegram) -> dict:
    client = TelegramClient("123:TEST", transport=httpx.MockTransport(fake_telegram.handler))
    return build_adapters(crm, telegram=client, demo_chat_id=DEMO_CHAT)
