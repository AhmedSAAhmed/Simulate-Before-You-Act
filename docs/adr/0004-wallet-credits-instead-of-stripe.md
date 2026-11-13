# 0004 - Money moves as wallet credits in our own ledger, not through Stripe

Date: 2026-11-14 · Status: accepted · Amends [0002](0002-real-systems-telegram-stripe-neon.md)

## Context
The owner decided against a Stripe account. The challenge still needs at least one high-stakes action, and "send money" is the strongest one for the duplicate-charge story. Telegram (mass message) and contact deletion already qualify on their own.

## Decision
Refunds become **wallet credits** in a ledger table in the Neon CRM (`issue_credit`). The ledger is append-only: a credit is one row, and its reversal is a matching debit row, never an update or a delete. The action is `compensable`: a debit offsets it while the balance still covers it; once the customer has spent it, only a drafted recovery request remains. Every money movement is tier HIGH.

## Alternatives considered
- Stripe test mode: a real payment API, but one more account; declined by the owner.
- Drop money entirely: loses the strongest high-stakes category and the duplicate-charge narrative.

## Consequences
- No payment provider in the stack, and nothing extra to configure.
- The simulator reads balances, existing credits and dispute flags from the same database it writes to, so drift and "already spent" cases are easy to stage for the failure test.
- The demo must say plainly that the wallet is the app's own ledger, not a bank or card network.
