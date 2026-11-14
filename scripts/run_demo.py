"""One full run from the terminal: intent -> simulate -> (tweak) -> approve -> execute -> verify.

Without --approve it stops after the simulation and writes nothing to any system.

  python scripts/run_demo.py                                  # plan with a model, simulate, stop
  python scripts/run_demo.py --resolve --accept-rules "..."   # leave out blocked items, accept the automation
  python scripts/run_demo.py --resolve --accept-rules "..." --approve "Ahmed"   # ...and run it for real
  add --chaos drift   to change the data after approval (the run must refuse)
  add --chaos blind   to hide the automation from the simulator (the canary must catch it)
  add --fake-telegram to keep every message in memory instead of sending it
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sba.adapters.fake_telegram import FakeTelegram  # noqa: E402
from sba.adapters.registry import build_adapters  # noqa: E402
from sba.adapters.telegram import TelegramClient  # noqa: E402
from sba.cli_format import describe_execution, describe_simulation  # noqa: E402
from sba.config import ROOT, settings  # noqa: E402
from sba.crm.schema import make_engine  # noqa: E402
from sba.crm.seed import CURRENCY, DEMO_REQUEST, seed_demo  # noqa: E402
from sba.crm.service import CrmService  # noqa: E402
from sba.llm.router import LLMRouter  # noqa: E402
from sba.pipeline import Pipeline, StageFailed, resolve_blockers  # noqa: E402
from sba.store.runs import RunStore  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Run the simulate-before-you-act pipeline once.")
    p.add_argument("--request", default=DEMO_REQUEST)
    p.add_argument("--example-plan", action="store_true", help="skip the planner model")
    p.add_argument("--no-critic", action="store_true")
    p.add_argument("--resolve", action="store_true", help="leave out every blocked item, then simulate again")
    p.add_argument("--accept-rules", metavar="REASON", help="accept automation side effects, with a reason")
    p.add_argument("--approve", metavar="NAME", help="approve and execute as NAME")
    p.add_argument("--chaos", choices=("drift", "blind"))
    p.add_argument("--fake-telegram", action="store_true")
    p.add_argument("--reseed", action="store_true", help="reset the demo data first")
    p.add_argument("--sandbox", default="demo")
    a = p.parse_args()

    engine = make_engine(settings.database_url)
    crm = CrmService(engine, sandbox=a.sandbox)
    fake = FakeTelegram() if a.fake_telegram else None
    telegram = fake.client() if fake else (TelegramClient(settings.telegram_bot_token)
                                           if settings.telegram_bot_token else None)
    demo_chat = "999" if fake else (settings.telegram_demo_chat_id or None)
    if a.reseed:
        seed_demo(crm, your_chat_id="111" if fake else (settings.telegram_demo_chat_id or None))
    pipe = Pipeline(crm, build_adapters(crm, telegram=telegram, demo_chat_id=demo_chat),
                    RunStore(ROOT / "runs", engine), LLMRouter.from_settings(settings))
    blind = ("automations",) if a.chaos == "blind" else ()

    try:
        plan = pipe.plan(a.request, use_example=a.example_plan)
    except StageFailed as err:
        print(f"01_intent failed: {err.why}")
        return 1
    print(f"Run {plan.run_id} | planner: {pipe.planner_model[plan.run_id]}")
    for i, action in enumerate(plan.actions):
        print(f"  {i}. {action.kind.value} {action.selector} {sorted(action.params)}")
    sim = pipe.simulate(plan, blind_spots=blind, use_critic=not a.no_critic)
    print("\n== 02 simulate ==\n" + describe_simulation(plan, sim, effects=False))

    if sim.blockers and a.resolve:
        plan = resolve_blockers(plan, sim, accept_rules_reason=a.accept_rules)
        sim = pipe.simulate(plan, blind_spots=blind, use_critic=not a.no_critic)
        print("\n== 02 simulate, after the tweaks ==\n" + describe_simulation(plan, sim))
    if sim.blockers:
        print(f"\nStopped: {len(sim.blockers)} blocker(s) left. Nothing was written. Run folder: runs/{plan.run_id}")
        return 1
    if not a.approve:
        print(f"\nNot approved (no --approve). Nothing was written. Run folder: runs/{plan.run_id}")
        return 0

    decision = pipe.decide(plan, sim, approver=a.approve, verdict="approve")
    print(f"\n== 03 approved by {decision.approver}, expires {decision.expires_at:%H:%M:%S} UTC ==")

    def human_credits_one_customer() -> None:
        first = next(e for e in sim.effects if e.action_index == 0)
        crm.add_ledger_entry(contact_id=first.after["contact_id"], amount_minor=2_500, currency=CURRENCY,
                             kind="credit", actor="human:reem", charge_id=first.record_id)
        print(f"   (chaos: a person credited {first.subject} BHD 2.500 after the approval)")

    result = pipe.execute(plan, sim, decision, blind_spots=blind,
                          before_writes=human_credits_one_customer if a.chaos == "drift" else None)
    print("\n== 04 execute + 05 verify ==\n" + describe_execution(result))
    if fake:
        print(f"   (fake Telegram: {len(fake.sent)} sent, {len(fake.deleted)} recalled; nothing left the machine)")
    print(f"\nRun folder: runs/{plan.run_id}  checks: {pipe.store.status(plan.run_id)}")
    return 0 if result.verification.outcome == "match" else 1


if __name__ == "__main__":
    sys.exit(main())
