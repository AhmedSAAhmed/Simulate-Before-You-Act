"""An in-memory Bot API for tests and dry runs. Nothing leaves the process."""

from __future__ import annotations

import json
from typing import Any

import httpx

from sba.adapters.telegram import TelegramClient


class FakeTelegram:
    """Records sends, edits and deletes.

    `blocked` chats refuse the bot, `network_down` fails every call, and `rate_limit_next`
    answers the next N sends with a 429 "retry after 1".
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, int]] = []
        self.markups: dict[int, dict | None] = {}
        self.deleted: list[tuple[str, int]] = []
        self.answered: list[str] = []
        self.blocked: set[str] = set()
        self.network_down = False
        self.connect_errors_next = 0
        self.rate_limit_next = 0
        self.calls: list[str] = []
        self.slept: list[float] = []
        self.webhook: dict[str, Any] | None = None
        self._next = 100

    def client(self) -> TelegramClient:
        return TelegramClient("000:FAKE", transport=httpx.MockTransport(self.handler), sleep=self.slept.append)

    def texts_to(self, chat_id: str) -> list[str]:
        return [text for chat, text, _ in self.sent if chat == str(chat_id)]

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        self.calls.append(method)
        if self.network_down:
            raise httpx.ConnectError("connection reset", request=request)
        if self.connect_errors_next:
            self.connect_errors_next -= 1
            raise httpx.ConnectError("connection reset", request=request)
        body = json.loads(request.content or b"{}")
        chat = str(body.get("chat_id"))
        if chat in self.blocked:
            return _err(403, "Forbidden: bot was blocked by the user")
        if method == "getMe":
            return _ok({"id": 1, "username": "FakeSbaBot"})
        if method == "getChat":
            return _ok({"id": int(chat)})
        if method == "sendMessage":
            if self.rate_limit_next:
                self.rate_limit_next -= 1
                return httpx.Response(200, json={"ok": False, "error_code": 429, "description": "Too Many Requests",
                                                 "parameters": {"retry_after": 1}})
            self._next += 1
            self.sent.append((chat, body["text"], self._next))
            self.markups[self._next] = body.get("reply_markup")
            return _ok({"message_id": self._next})
        if method == "editMessageReplyMarkup":
            self.markups[int(body["message_id"])] = body.get("reply_markup")
            return _ok(True)
        if method == "answerCallbackQuery":
            self.answered.append(body["callback_query_id"])
            return _ok(True)
        if method == "deleteMessage":
            self.deleted.append((chat, body["message_id"]))
            return _ok(True)
        if method == "setWebhook":
            self.webhook = body
            return _ok(True)
        if method in ("deleteWebhook", "getUpdates"):
            return _ok(True if method == "deleteWebhook" else [])
        return _err(404, "unknown method")


def _ok(result: Any) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


def _err(code: int, description: str) -> httpx.Response:
    return httpx.Response(200, json={"ok": False, "error_code": code, "description": description})
