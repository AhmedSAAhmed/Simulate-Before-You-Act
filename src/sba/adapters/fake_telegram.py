"""An in-memory Bot API for tests and dry runs. Nothing leaves the process."""

from __future__ import annotations

import json

import httpx

from sba.adapters.telegram import TelegramClient


class FakeTelegram:
    """Records sends and deletes; chats in `blocked` refuse the bot; `network_down` fails every call."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, int]] = []
        self.deleted: list[tuple[str, int]] = []
        self.blocked: set[str] = set()
        self.network_down = False
        self.calls: list[str] = []
        self._next = 100

    def client(self) -> TelegramClient:
        return TelegramClient("000:FAKE", transport=httpx.MockTransport(self.handler))

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
