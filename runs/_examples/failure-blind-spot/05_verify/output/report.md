# Run report: r-20261114-071840-883b

Outcome: rolled_back

## Request
Credit back everyone who was double-charged yesterday, apologize on Telegram in their language, tag them dup-charge-2026-11, and delete the spam leads from yesterday's import.

## Summary
The canary for action 2 (update_contact_attributes) found 1 unpredicted tickets opened, 1 unpredicted notices sent. The run stopped there. Everything that ran was rolled back.

## Predicted vs observed

| Item | Field | Predicted | Observed |
|---|---|---|---|
| (system) | tickets_opened | 0 | 1 |
| (system) | notices_sent | 0 | 1 |

## Invariants
- credit_within_duplicate: held
- no_charge_credited_twice: held
- wallets_match_prediction: held

## Rollback
- c_001: rolled_back. labels restored; 1 automation tickets closed; 1 notices recalled
- c_007: rolled_back. message recalled
- c_006: rolled_back. message recalled
- c_002: rolled_back. message recalled
- c_001: rolled_back. message recalled
- ch_d09: rolled_back.
- ch_d08: rolled_back.
- ch_d07: rolled_back.
- ch_d06: rolled_back.
- ch_d02: rolled_back.
- ch_d01: rolled_back.

## What the simulator missed
1 tickets opened, 1 notices sent

## New simulator rule
Read the CRM's automation rules before predicting label changes (see blind spot 'automations').
