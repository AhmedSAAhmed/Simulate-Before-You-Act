from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from sba.adapters.fake_telegram import FakeTelegram
from sba.adapters.registry import build_adapters
from sba.crm.schema import make_engine
from sba.crm.seed import demo_plan, seed_demo
from sba.crm.service import CrmService

YOUR_CHAT = "111"
DEMO_CHAT = "999"
NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
CRITIC_NOTE = "Customers may reply asking when the credit appears; the inbox will get a burst of questions."


def plan_json() -> str:
    return json.dumps({"actions": [a.model_dump(mode="json") for a in demo_plan().actions], "notes": ""})


class FakeModels:
    """Deterministic planner and critic: the planner returns the example plan, the critic one note."""

    def __init__(self, planner_replies: list[str] | None = None, critic_fails: bool = False) -> None:
        self.planner_replies = list(planner_replies or [plan_json()])
        self.critic_fails = critic_fails
        self.calls: list[str] = []

    def __call__(self, ref, messages):
        self.calls.append(str(ref))
        if '"side_effects"' not in messages[0]["content"]:  # the critic's output format names side_effects
            return self.planner_replies.pop(0) if len(self.planner_replies) > 1 else self.planner_replies[0], 100
        if self.critic_fails:
            raise TimeoutError("critic down")
        return json.dumps({"side_effects": [{"description": CRITIC_NOTE, "likelihood": "medium"}]}), 50


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
    return build_adapters(crm, telegram=fake_telegram.client(), demo_chat_id=DEMO_CHAT)
