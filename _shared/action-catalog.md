# Action catalog: every write the agent may plan

The planner may only use the actions listed here. Each action names its real system, what the simulator must read before predicting anything, its reversibility class and its rollback. Code lives in `src/sba/adapters/`; one adapter per system, each implementing `read`, `simulate`, `execute`, `verify` and `compensate`.

## Reversibility classes

| Class | Meaning | Gate |
|---|---|---|
| `reversible` | the prior state can be restored exactly | snapshot before write |
| `recallable` | can be withdrawn for a window, but the effect may already have been seen | hold queue + recall |
| `compensable` | can't be undone; a new action can offset it | compensation drafted, needs approval |
| `irreversible` | no undo and no automatic offset | always tier HIGH |

## Actions

| Action | System | Simulator reads | Class | Rollback / compensation |
|---|---|---|---|---|
| `issue_credit` | wallet ledger in the CRM database | charge, credits already issued for it, dispute flag, wallet balance | `compensable` | debit the same amount while the balance still covers it; otherwise draft a recovery request |
| `send_message` | Telegram Bot API | contact's chat id, language, opt-out flag, last delivery | `recallable` (48h) | 30s hold, then `deleteMessage`, then a correction message |
| `update_contact_attributes` | CRM database | current attributes, automation rules matching the new values | `reversible` | restore snapshot |
| `delete_contacts` | CRM database | contact, open tickets, linked conversations | `reversible` for 24h, then purge | undelete from snapshot before purge |

## Selectors and parameters

Plans name targets by selector, never by a list of ids the model typed. The simulator resolves selectors against live state with read-only calls; the resolved ids, and every field read, form the state fingerprint. Unknown keys are refused.

| Action | `selector` | `params` |
|---|---|---|
| `issue_credit` | `charges_created_on: "YYYY-MM-DD"`, `duplicates_only: true` | none; the amount is always what's left of the duplicate |
| `send_message` | `from_action: <earlier index>` | `templates: {en, ar}` with only `{name}` and `{amount}` placeholders |
| `update_contact_attributes` | `from_action: <index>` or `label: "<label>"` | `add_labels`, `remove_labels` |
| `delete_contacts` | `label: "<label>"` | none |

Every action also accepts the operator's tweaks: `exclude: [record ids]` and `override: {record id: reason}` (an automation rule's id is `rule:<id>`).
