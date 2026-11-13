from sba.domain.hashing import plan_hash, state_fingerprint
from sba.domain.models import Action, ActionKind, ActionPlan


def _plan(amount: int, request: str = "refund doubles") -> ActionPlan:
    return ActionPlan(
        run_id="r1",
        request=request,
        actions=(
            Action(
                kind=ActionKind.REFUND_CHARGE,
                selector={"duplicate": True, "date": "2026-11-13"},
                params={"max_amount": amount},
            ),
        ),
    )


def test_plan_hash_ignores_request_wording() -> None:
    assert plan_hash(_plan(100, "a")) == plan_hash(_plan(100, "b"))


def test_plan_hash_changes_when_params_change() -> None:
    assert plan_hash(_plan(100)) != plan_hash(_plan(101))


def test_plan_hash_ignores_dict_key_order() -> None:
    a = Action(kind=ActionKind.SEND_MESSAGE, selector={"x": 1, "y": 2})
    b = Action(kind=ActionKind.SEND_MESSAGE, selector={"y": 2, "x": 1})
    pa = ActionPlan(run_id="r", request="", actions=(a,))
    pb = ActionPlan(run_id="r", request="", actions=(b,))
    assert plan_hash(pa) == plan_hash(pb)


def test_fingerprint_is_order_independent_but_value_sensitive() -> None:
    reads = [("stripe", "ch_1", "amount_refunded", 0), ("crm", "c_1", "tags", ["vip"])]
    assert state_fingerprint(reads) == state_fingerprint(list(reversed(reads)))
    drifted = [("stripe", "ch_1", "amount_refunded", 500), reads[1]]
    assert state_fingerprint(reads) != state_fingerprint(drifted)
