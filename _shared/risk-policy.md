# Risk policy: what needs approval, what blocks, what is never allowed

Enforced in code (`src/sba/domain/policy.py`). The LLM can't change any value here; a plan that exceeds a limit fails the 01_intent check.

## Hard limits (fail the plan)

| Limit | Value |
|---|---|
| credit per customer | ≤ the duplicate charge amount |
| credit total per plan | ≤ 5,000.00 in the account currency |
| message recipients per plan | ≤ 500 |
| contacts deleted per plan | ≤ 50 |
| approval lifetime | 10 minutes |

## Tiers

| Tier | When | Execution |
|---|---|---|
| LOW | every action `reversible`, ≤ 10 records | approve, then run |
| MEDIUM | any `recallable` action, or > 10 records | approve, then canary first |
| HIGH | any money movement, any `irreversible` action, > 50 recipients, or any deletion | approve, canary first, halt on the first divergence |

## Blockers (Approve stays disabled until each is resolved in the plan)

| Blocker | Resolve by |
|---|---|
| the charge is partly credited already | exclude it, or include it with a reason (only the remainder is credited) |
| the charge is disputed with the bank (a credit would pay twice) | exclude it, or include it with a reason |
| a contact to delete has an open ticket | exclude it, or include it with a reason |
| a new label matches an automation rule (the side effect is shown) | accept the rule with a reason, or change the labels |
| the recipient opted out, has no Telegram chat, or the bot can't reach the chat | **hard**: exclude only |
| Telegram couldn't be reached to check a chat | **hard**: simulate again |
| a plan-level limit above, or credits in more than one currency | **hard**: exclude items until under the limit |

A charge already **fully** credited isn't a blocker: it's left out automatically, and the notes say why.

Resolving a blocker edits the plan (`params.exclude`, or `params.override` with a written reason), which changes its hash and re-runs 02_simulate.

## Canary and circuit breaker

- Canary: the first 5% of items (at least 1) run, then 05_verify compares observed with predicted effects.
- Any effect class that wasn't predicted, or any money difference above zero, halts the rest of the plan and starts rollback of reversible steps.
- An outcome that can't be confirmed is marked `unknown`. It's never retried automatically.
