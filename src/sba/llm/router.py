"""Route JSON-returning completions across providers, with fallback and a daily token budget.

Every provider speaks the OpenAI chat API, so one client covers all three. Models only ever
return plans, critiques and prose: no number in a simulation comes from here.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sba.config import Settings, clean_value

log = logging.getLogger(__name__)

BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openrouter": "https://openrouter.ai/api/v1",
}
DEFAULT_CHAINS = {
    # Each Groq model has its own rate limit, so the smaller one is a fast second try.
    "planner": "groq:openai/gpt-oss-120b,groq:openai/gpt-oss-20b,gemini:gemini-3.5-flash",
    # flash-lite answers in about a second; the critic lists risks, it doesn't need deep reasoning.
    "critic": "gemini:gemini-3.5-flash-lite,openrouter:nvidia/nemotron-3-ultra-550b-a55b:free",
}
DEFAULT_DAILY_TOKENS = 300_000


class LLMError(RuntimeError):
    """No configured model could answer."""


class BudgetExceeded(LLMError):
    """Today's token budget is spent; the demo stops calling models until tomorrow (UTC)."""


@dataclass(frozen=True)
class ModelRef:
    provider: str
    model: str

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class LLMResult:
    data: dict[str, Any]
    model: ModelRef
    tokens: int


# (model, messages) -> (raw text, tokens used). Swappable in tests.
Transport = Callable[[ModelRef, list[dict[str, str]]], tuple[str, int]]


def parse_chain(spec: str) -> tuple[ModelRef, ...]:
    refs = []
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        provider, _, model = part.partition(":")
        if provider not in BASE_URLS or not model:
            raise ValueError(f"bad model ref {part!r}; use provider:model with provider in {sorted(BASE_URLS)}")
        refs.append(ModelRef(provider, model))
    return tuple(refs)


@dataclass
class UsageMeter:
    daily_limit: int
    _day: date = field(default_factory=lambda: datetime.now(UTC).date())
    _used: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def check(self) -> None:
        with self._lock:
            self._roll()
            if self._used >= self.daily_limit:
                raise BudgetExceeded(f"daily model budget of {self.daily_limit:,} tokens is used up")

    def add(self, tokens: int) -> None:
        with self._lock:
            self._roll()
            self._used += max(0, tokens)

    @property
    def used(self) -> int:
        return self._used

    def _roll(self) -> None:
        today = datetime.now(UTC).date()
        if today != self._day:
            self._day, self._used = today, 0


class LLMRouter:
    def __init__(
        self,
        keys: dict[str, str],
        *,
        chains: dict[str, tuple[ModelRef, ...]],
        meter: UsageMeter,
        transport: Transport | None = None,
    ) -> None:
        self._keys = {p: k for p, k in keys.items() if k}
        self._chains = chains
        self.meter = meter
        self._transport = transport or self._openai_transport

    @classmethod
    def from_settings(cls, settings: Settings, *, transport: Transport | None = None) -> LLMRouter:
        keys = {"groq": settings.groq_api_key, "gemini": settings.gemini_api_key,
                "openrouter": settings.openrouter_api_key}
        chains = {role: parse_chain(clean_value(os.environ.get(f"{role.upper()}_MODELS", "")) or default)
                  for role, default in DEFAULT_CHAINS.items()}
        limit = int(clean_value(os.environ.get("LLM_DAILY_TOKENS", "")) or DEFAULT_DAILY_TOKENS)
        return cls(keys, chains=chains, meter=UsageMeter(limit), transport=transport)

    def available(self, role: str) -> bool:
        return any(ref.provider in self._keys for ref in self._chains.get(role, ()))

    def complete_json(
        self, role: str, *, system: str, user: str, avoid_provider: str | None = None
    ) -> LLMResult:
        """Ask the first working model in the role's chain for a JSON object."""
        self.meter.check()
        tried: list[str] = []
        for ref in self._chains.get(role, ()):
            if ref.provider not in self._keys or ref.provider == avoid_provider:
                continue
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            try:
                raw, tokens = self._transport(ref, messages)
            except Exception as err:  # noqa: BLE001 - any provider failure moves on to the next model
                log.warning("model %s failed: %s", ref, type(err).__name__)
                tried.append(f"{ref} ({type(err).__name__})")
                continue
            self.meter.add(tokens)
            try:
                return LLMResult(_json_object(raw), ref, tokens)
            except ValueError:
                tried.append(f"{ref} (not JSON)")
        raise LLMError(f"no model answered for {role}: " + ("; ".join(tried) or "no provider key configured"))

    def _openai_transport(self, ref: ModelRef, messages: list[dict[str, str]]) -> tuple[str, int]:
        from openai import OpenAI

        # No SDK retries: on a 429 the SDK would sleep (16s on Groq's free tier) before trying the same
        # model again. Falling through to the next model in the chain is faster.
        client = OpenAI(base_url=BASE_URLS[ref.provider], api_key=self._keys[ref.provider], timeout=45,
                        max_retries=0)
        resp = client.chat.completions.create(
            model=ref.model, messages=messages, temperature=0.2, response_format={"type": "json_object"}
        )
        text = resp.choices[0].message.content or ""
        tokens = resp.usage.total_tokens if resp.usage else 0
        return text, tokens


def _json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("reply is not a JSON object")
    return value
