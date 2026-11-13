"""Load (or reset) the double-charge scenario into the configured database.

Usage (from the repo root): python scripts/seed_demo.py [--sandbox demo]
Only rows in the chosen sandbox are replaced; nothing else in the database is touched.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sba.config import settings  # noqa: E402
from sba.crm.schema import make_engine  # noqa: E402
from sba.crm.seed import seed_demo  # noqa: E402
from sba.crm.service import CrmService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sandbox", default="demo")
    args = parser.parse_args()
    engine = make_engine(settings.database_url)
    summary = seed_demo(CrmService(engine, sandbox=args.sandbox),
                        your_chat_id=settings.telegram_demo_chat_id or None)
    print(f"Seeded sandbox '{summary['sandbox']}' on {engine.dialect.name}: {summary['contacts']} contacts, "
          f"{summary['duplicate_charges']} duplicate charges, your Telegram chat linked: "
          f"{summary['your_chat_linked']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
