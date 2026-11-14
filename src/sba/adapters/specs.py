"""The allowed shape of each action. One source for the 01_intent check and the adapters."""

from __future__ import annotations

from dataclasses import dataclass

from sba.domain.models import Action, ActionKind

CONTROLS = frozenset({"exclude", "override"})


@dataclass(frozen=True)
class ActionSpec:
    selector_allowed: frozenset[str]
    selector_required: frozenset[str]
    params_allowed: frozenset[str]
    params_required: frozenset[str] = frozenset()


SPECS: dict[ActionKind, ActionSpec] = {
    ActionKind.ISSUE_CREDIT: ActionSpec(
        frozenset({"charges_created_on", "duplicates_only"}), frozenset({"charges_created_on", "duplicates_only"}),
        CONTROLS,
    ),
    ActionKind.SEND_MESSAGE: ActionSpec(
        frozenset({"from_action"}), frozenset({"from_action"}), CONTROLS | {"templates"}, frozenset({"templates"}),
    ),
    ActionKind.UPDATE_CONTACT_ATTRIBUTES: ActionSpec(
        frozenset({"from_action", "label"}), frozenset(), CONTROLS | {"add_labels", "remove_labels"},
    ),
    ActionKind.DELETE_CONTACTS: ActionSpec(frozenset({"label"}), frozenset({"label"}), CONTROLS),
}


def static_errors(action: Action, index: int) -> list[str]:
    """Shape problems visible without reading any system."""
    spec = SPECS[action.kind]
    errors = []
    for where, given, allowed, required in (
        ("selector", action.selector, spec.selector_allowed, spec.selector_required),
        ("params", action.params, spec.params_allowed, spec.params_required),
    ):
        if unknown := sorted(set(given) - allowed):
            errors.append(f"action {index} ({action.kind}): unknown {where} keys {unknown}")
        if missing := sorted(required - set(given)):
            errors.append(f"action {index} ({action.kind}): missing {where} keys {missing}")
    source = action.selector.get("from_action")
    if source is not None and (not isinstance(source, int) or isinstance(source, bool) or not 0 <= source < index):
        errors.append(f"action {index} ({action.kind}): from_action must name an earlier action")
    return errors
