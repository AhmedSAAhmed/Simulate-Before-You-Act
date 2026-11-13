"""Simulate the demo plan against the live systems and print what would happen. Writes nothing.

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
from sba.config import settings  # noqa: E402
from sba.crm.schema import make_engine  # noqa: E402
from sba.crm.seed import demo_plan  # noqa: E402
from sba.crm.service import CrmService  # noqa: E402
from sba.domain.money import fmt  # noqa: E402


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

    t = sim.totals
    cur = t.get("currency", "BHD")
    print(f"Request: {plan.request}\n")
    print(f"Tier {sim.tier.value} | plan {sim.plan_hash[:12]} | state {sim.state_fingerprint[:12]}")
    print(f"Credits {t.get('credits', 0)} totalling {fmt(t.get('credit_total_minor', 0), cur)} | "
          f"messages {t.get('messages', 0)} | label changes {t.get('label_changes', 0)} | "
          f"deletions {t.get('deletions', 0)}")
    print(f"\nBlockers ({len(sim.blockers)}): Approve stays disabled until each is resolved")
    for b in sim.blockers:
        print(f"  - [{b.rule}{', hard' if b.hard else ''}] {b.detail}")
    print(f"\nSide effects ({len(sim.side_effects)}):")
    for s in sim.side_effects:
        print(f"  - ({s.likelihood}) {s.description}")
    print(f"\nNotes ({len(sim.notes)}):")
    for n in sim.notes:
        print(f"  - {n}")
    print("\nBefore -> after:")
    for e in sim.effects:
        if e.action_index == 0:
            c = e.after["currency"]
            change = (f"wallet {fmt(e.before['wallet_balance'], c)} -> {fmt(e.after['wallet_balance'], c)} "
                      f"(+{fmt(e.after['credit'], c)})")
        elif e.action_index == 1:
            change = f"message via {e.after['route']} ({e.after['language']})"
        elif "labels" in e.after:
            change = f"labels {e.before['labels']} -> {e.after['labels']}"
        else:
            change = f"{e.before['status']} -> {e.after['status']}"
        print(f"  {e.action_index}  {e.subject:<32} {change}")
    print("\nRollback:")
    for r in sim.rollback:
        print(f"  {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
