---
id: {scenario-id}
kind: {happy-path | blocker | drift | unmodeled-side-effect}
---

# Scenario: {short name}

## Seed
{what `scripts/seed_demo.py` creates: contacts, charges, wallets, automations}

## Request
{the operator's words}

## Expected simulation
- Effects: {counts and totals}
- Blockers: {list or none}
- Tier: {LOW | MEDIUM | HIGH}

## Injected fault
{what changes between approval and execution, or "none"}

## Expected outcome
{match | halted at canary | rolled back}, and why
