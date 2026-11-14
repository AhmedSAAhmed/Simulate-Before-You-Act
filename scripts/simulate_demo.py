"""Simulate the example plan against the live systems and print what would happen. Writes nothing.

Usage (from the repo root): python scripts/simulate_demo.py [--resolved] [--blind automations]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sba.adapters.registry import build_adapters  # noqa: E402
from sba.adapters.telegram import TelegramClient  # noqa: E402
from sba.agents.simulator import simulate  # noqa: E402
from sba.cli_format import describe_simulation  # noqa: E402
from sba.config import settings  # noqa: E402
from sba.crm.schema import make_engine  # noqa: E402
from sba.crm.seed import demo_plan  # noqa: E402
from sba.crm.service import CrmService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sandbox", default="demo")
    parser.add_argument("--resolved", action="store_true", help="apply the operator's tweaks")
    parser.add_argument("--blind", action="append", default=[], help="a blind spot, e.g. automations")
    args = parser.parse_args()

    crm = CrmService(make_engine(settings.database_url), sandbox=args.sandbox)
    telegram = TelegramClient(settings.telegram_bot_token) if settings.telegram_bot_token else None
    adapters = build_adapters(crm, telegram=telegram, demo_chat_id=settings.telegram_demo_chat_id or None)
    plan = demo_plan(resolved=args.resolved)
    sim = simulate(plan, adapters, blind_spots=args.blind)
    print(f"Request: {plan.request}\n")
    print(describe_simulation(plan, sim))
    return 0


if __name__ == "__main__":
    sys.exit(main())
