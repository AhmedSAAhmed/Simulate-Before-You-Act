"""Deterministic demo data: yesterday's double-charge incident.

Amounts are in fils (BHD has 3 decimals). The hand-computed results this seed must
produce are in `tests/test_simulator_scenario.py`; change both together.

| Contact | Duplicate | Amount | Situation the simulator must catch |
|---|---|---|---|
| c_001 Demo Reviewer (en, your Telegram) | ch_d01 | 12.500 | clean; wallet 2.000 |
| c_002 Sara (ar) | ch_d02 | 8.750 | clean |
| c_003 Youssef (en) | ch_d03 | 23.000 | already fully credited by a person: left out automatically |
| c_004 Nadia (ar) | ch_d04 | 15.000 | partly credited (5.000): blocker |
| c_005 Omar (ar) | ch_d05 | 6.250 | disputed with the bank: blocker |
| c_006 Layla (en) | ch_d06 | 30.000 | clean; wallet 0.500 after a spend |
| c_007 Fatima (ar) | ch_d07 | 9.900 | clean; wallet 0.500 |
| c_008 Khalid (en) | ch_d08 | 11.000 | opted out of messages: message blocker |
| c_009 Mariam (ar) | ch_d09 | 4.500 | no Telegram chat: message blocker; wallet 0.750 |
| c_010 Hassan (en) | none | | not affected |

Plus four imported spam leads labeled `spam-import-2026-11` (c_103 has an open ticket),
and one automation rule: any added label containing "charge" opens a billing ticket and
sends the customer a notice.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import delete, insert

from sba.crm.schema import (
    SANDBOXED_TABLES,
    automation_rules,
    charges,
    contacts,
    init_db,
)
from sba.crm.service import CrmService
from sba.domain.models import Action, ActionKind, ActionPlan

INCIDENT_DAY = date(2026, 11, 13)
CURRENCY = "BHD"
SPAM_LABEL = "spam-import-2026-11"
INCIDENT_LABEL = "dup-charge-2026-11"

DEMO_REQUEST = (
    "Credit back everyone who was double-charged yesterday, apologize on Telegram in their language, "
    f"tag them {INCIDENT_LABEL}, and delete the spam leads from yesterday's import."
)
APOLOGY = {
    "en": "Hi {name}, we charged you twice by mistake yesterday. We've credited {amount} back to your "
          "wallet, and there's nothing you need to do. Sorry for the trouble. The Support Team",
    "ar": "مرحباً {name}، خُصم المبلغ منك مرتين بالخطأ أمس. أعدنا {amount} إلى محفظتك، ولا يلزمك أي إجراء. "
          "نعتذر عن الإزعاج. فريق الدعم",
}
# The tweaks an operator makes to clear every blocker in the seeded scenario.
DEMO_RESOLUTIONS: tuple[dict[str, object], ...] = (
    {"exclude": ["ch_d05"], "override": {"ch_d04": "Reem's 5.000 was a partial fix; credit the rest"}},
    {"exclude": ["c_008", "c_009"]},
    {"override": {"rule:r_billing": "Billing wants a ticket for every affected customer"}},
    {"exclude": ["c_103"]},
)


def demo_plan(run_id: str = "demo", *, resolved: bool = False) -> ActionPlan:
    """The plan the planner should produce for DEMO_REQUEST; `resolved` applies DEMO_RESOLUTIONS."""
    extra = DEMO_RESOLUTIONS if resolved else ({},) * 4
    actions = (
        Action(kind=ActionKind.ISSUE_CREDIT,
               selector={"charges_created_on": INCIDENT_DAY.isoformat(), "duplicates_only": True},
               params={**extra[0]}, reason="Return each duplicate charge to the customer's wallet"),
        Action(kind=ActionKind.SEND_MESSAGE, selector={"from_action": 0},
               params={"templates": dict(APOLOGY), **extra[1]}, reason="Apologize in the customer's language"),
        Action(kind=ActionKind.UPDATE_CONTACT_ATTRIBUTES, selector={"from_action": 0},
               params={"add_labels": [INCIDENT_LABEL], **extra[2]}, reason="Tag the affected customers"),
        Action(kind=ActionKind.DELETE_CONTACTS, selector={"label": SPAM_LABEL},
               params={**extra[3]}, reason="Remove the spam leads from the import"),
    )
    return ActionPlan(run_id=run_id, request=DEMO_REQUEST, actions=actions)

# id, name, language, telegram ("demo", "you" or None), opted_out
_CONTACTS: tuple[tuple[str, str, str, str | None, bool], ...] = (
    ("c_001", "Demo Reviewer", "en", "you", False),
    ("c_002", "Sara Al-Mansouri", "ar", "demo", False),
    ("c_003", "Youssef Rami", "en", "demo", False),
    ("c_004", "Nadia Habib", "ar", "demo", False),
    ("c_005", "Omar Khalil", "ar", "demo", False),
    ("c_006", "Layla Hassan", "en", "demo", False),
    ("c_007", "Fatima Al-Zahra", "ar", "demo", False),
    ("c_008", "Khalid Nasser", "en", "demo", True),
    ("c_009", "Mariam Saleh", "ar", None, False),
    ("c_010", "Hassan Ali", "en", "demo", False),
)
_SPAM = ("c_101", "c_102", "c_103", "c_104")

# duplicate charge id -> (contact, amount in fils, disputed)
_DUPLICATES: dict[str, tuple[str, int, bool]] = {
    "ch_d01": ("c_001", 12_500, False),
    "ch_d02": ("c_002", 8_750, False),
    "ch_d03": ("c_003", 23_000, False),
    "ch_d04": ("c_004", 15_000, False),
    "ch_d05": ("c_005", 6_250, True),
    "ch_d06": ("c_006", 30_000, False),
    "ch_d07": ("c_007", 9_900, False),
    "ch_d08": ("c_008", 11_000, False),
    "ch_d09": ("c_009", 4_500, False),
}

# contact -> list of (kind, amount, charge, actor) applied before the run
_LEDGER: tuple[tuple[str, str, int, str | None, str], ...] = (
    ("c_001", "opening", 2_000, None, "seed"),
    ("c_006", "opening", 1_500, None, "seed"),
    ("c_006", "spend", -1_000, None, "seed"),
    ("c_007", "opening", 500, None, "seed"),
    ("c_009", "opening", 750, None, "seed"),
    ("c_003", "credit", 23_000, "ch_d03", "human:reem"),
    ("c_004", "credit", 5_000, "ch_d04", "human:reem"),
)


def seed_demo(service: CrmService, *, your_chat_id: str | None) -> dict[str, Any]:
    """Wipe this sandbox and load the scenario. `your_chat_id` is the reviewer's Telegram chat."""
    init_db(service.engine)
    now = service.clock()
    sb = service.sandbox
    with service.engine.begin() as conn:
        for table in SANDBOXED_TABLES:
            conn.execute(delete(table).where(table.c.sandbox == sb))
        for cid, name, lang, tg, opted_out in _CONTACTS:
            chat = (your_chat_id or "demo") if tg == "you" else tg
            conn.execute(insert(contacts).values(
                sandbox=sb, id=cid, name=name, language=lang, telegram_chat_id=chat, opted_out=opted_out,
                labels=[], custom_attributes={}, updated_at=now,
            ))
        for n, cid in enumerate(_SPAM, start=1):
            conn.execute(insert(contacts).values(
                sandbox=sb, id=cid, name=f"Imported lead {n}", language="en", telegram_chat_id=None,
                opted_out=False, labels=[SPAM_LABEL], custom_attributes={"source": "csv-import"}, updated_at=now,
            ))
        for dup_id, (cid, amount, disputed) in _DUPLICATES.items():
            original = dup_id.replace("_d", "_o")
            order = f"ORD-{8800 + int(dup_id[-2:])}"
            for charge_id, dup_of, dis in ((original, None, False), (dup_id, original, disputed)):
                conn.execute(insert(charges).values(
                    sandbox=sb, id=charge_id, contact_id=cid, amount_minor=amount, currency=CURRENCY,
                    created_on=INCIDENT_DAY, order_ref=order, duplicate_of=dup_of, disputed=dis,
                ))
        conn.execute(insert(charges).values(
            sandbox=sb, id="ch_o10", contact_id="c_010", amount_minor=7_000, currency=CURRENCY,
            created_on=INCIDENT_DAY, order_ref="ORD-8810", duplicate_of=None, disputed=False,
        ))
        conn.execute(insert(automation_rules).values(
            sandbox=sb, id="r_billing", name="Billing follow-up", trigger="label_added", match_text="charge",
            action="open_ticket_and_notify",
            notice_en="We've opened a billing case about your recent charge. Our team will contact you "
            "within 2 working days.",
            notice_ar="فتحنا طلب متابعة بخصوص عملية الدفع الأخيرة، وسيتواصل معك فريقنا خلال يومي عمل.",
            enabled=True,
        ))
    for cid, kind, amount, charge_id, actor in _LEDGER:
        service.add_ledger_entry(
            contact_id=cid, amount_minor=amount, currency=CURRENCY, kind=kind, actor=actor, charge_id=charge_id
        )
    service.open_ticket("c_103", "Asked about delivery times", source="human")
    return {
        "sandbox": sb,
        "contacts": len(_CONTACTS) + len(_SPAM),
        "duplicate_charges": len(_DUPLICATES),
        "your_chat_linked": bool(your_chat_id),
    }
