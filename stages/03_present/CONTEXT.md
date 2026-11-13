# 03_present - one screen, one decision

One job: show the simulation so that a person can approve, tweak or reject it in under 90 seconds, and record that decision bound to what they saw.

The UI is `src/sba/ui/`. The plain-language summary at the top is written by the narrator model, which reads this file as its system prompt.

## Inputs
- Working (this run): `runs/{run-id}/02_simulate/output/simulation.json`
- Working (this run): `runs/{run-id}/02_simulate/output/check.md`
- Reference (every run): `../../_shared/risk-policy.md`

Do NOT load: the raw API responses, the planner prompt, other runs.

## Process
1. Summary first: what will change, how much money moves, who is affected, the tier, and the rollback in one line per action.
2. Then a before/after diff for every record, grouped by action; blockers are pinned at the top.
3. Tweaks (exclude a record, edit an amount or message) edit the plan and send the run back to 02_simulate. The screen shows the new hash.
4. Approve is enabled only when the 02 check passes. It writes `decision.json` with the plan hash and fingerprint shown on screen, and a 10-minute expiry.
5. Narrator rules: numbers only from `simulation.json`, no reassurance that the data doesn't support, and name the irreversible step plainly.

## Outputs
- `decision.json` -> `runs/{run-id}/03_present/output/`

## Check
A person makes the decision. `check.md` records `pass` for approve, or `fail: rejected by <approver>`.
