from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sba.adapters.fake_telegram import FakeTelegram
from sba.adapters.registry import build_adapters
from sba.crm.schema import make_engine
from sba.crm.seed import seed_demo
from sba.crm.service import CrmService

YOUR_CHAT = "111"
DEMO_CHAT = "999"
NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)


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
