# Run report: r-20261114-072318-717b

Outcome: drift

## Request
Credit back everyone who was double-charged yesterday, apologize on Telegram in their language, tag them dup-charge-2026-11, and delete the spam leads from yesterday's import.

## Summary
The data changed after approval (4 difference(s)). Nothing was written. Review the new simulation and approve it again.

## Predicted vs observed

| Item | Field | Predicted | Observed |
|---|---|---|---|
| ch_d01 | effect | {'action_index': 0, 'system': 'crm.wallet', 'record_id': 'ch... | None |
| c_001 | effect | {'action_index': 1, 'system': 'telegram', 'record_id': 'c_00... | None |
| c_001 | effect | {'action_index': 2, 'system': 'crm.contacts', 'record_id': '... | None |
| ch_d01 | blocker | None | Demo Reviewer (c_001): a person already credited BHD 2.500 o... |

## Invariants
- none checked (nothing ran)

## Rollback
- not needed

## What the simulator missed
nothing

## New simulator rule
none
