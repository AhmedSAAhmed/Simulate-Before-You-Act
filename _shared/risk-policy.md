# Risk policy: what needs approval, what blocks, what is never allowed

Enforced in code (`src/sba/domain/policy.py`). The LLM can't change any value here; a plan that exceeds a limit fails the 01_intent check.

## Hard limits (fail the plan)

| Limit | Value |
|---|---|
| refund per customer | ≤ the duplicate charge amount |
| refund total per plan | ≤ 5,000.00 in the account currency |
| message recipients per plan | ≤ 500 |
| contacts deleted per plan | ≤ 50 |
| approval lifetime | 10 minutes |

## Tiers

| Tier | When | Execution |
|---|---|---|
| LOW | every action `reversible`, ≤ 10 records | approve, then run |
| MEDIUM | any `recallable` action, or > 10 records | approve, then canary first |
| HIGH | any `irreversible` money movement, > 50 recipients, or any deletion | approve, canary first, halt on the first divergence |

## Blockers (Approve stays disabled until each is resolved in the plan)

- the charge is already fully or partly refunded
- the charge has an open dispute (refund would pay twice)
- the recipient opted out or has no Telegram chat
- a contact to delete has an open ticket
- a new attribute value matches an automation rule (the side effect must be shown and accepted)

Resolving a blocker means excluding the item or including it with a written reason. Both edit the plan, which changes its hash and re-runs 02_simulate.

## Canary and circuit breaker

- Canary: the first 5% of items (at least 1) run, then 05_verify compares observed with predicted effects.
- Any effect class that wasn't predicted, or any money difference above zero, halts the rest of the plan and starts rollback of reversible steps.
- An outcome that can't be confirmed is marked `unknown`. It's never retried automatically.
