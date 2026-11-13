"""Wire one adapter per action kind from settings."""

from __future__ import annotations

from sba.adapters.base import Adapter
from sba.adapters.crm import CreditAdapter, DeleteAdapter, LabelAdapter
from sba.adapters.telegram import MessageAdapter, TelegramClient
from sba.crm.service import CrmService
from sba.domain.models import ActionKind


def build_adapters(
    crm: CrmService, *, telegram: TelegramClient | None, demo_chat_id: str | None
) -> dict[ActionKind, Adapter]:
    return {
        ActionKind.ISSUE_CREDIT: CreditAdapter(crm),
        ActionKind.SEND_MESSAGE: MessageAdapter(crm, telegram, demo_chat_id),
        ActionKind.UPDATE_CONTACT_ATTRIBUTES: LabelAdapter(crm),
        ActionKind.DELETE_CONTACTS: DeleteAdapter(crm),
    }
