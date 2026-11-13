# 0001 - An approval binds to a plan hash and a state fingerprint

Date: 2026-11-14 · Status: accepted

## Context
The challenge disqualifies an "are you sure?" dialog dressed up as simulation. A plain approve button approves an intent, not a specific set of effects. Between approval and execution, the plan can be edited or the world can change (a human refunds a customer by hand), and the approved preview no longer describes what would run.

## Decision
A decision records `plan_hash` (sha256 of the canonical actions) and `state_fingerprint` (sha256 of every `(system, id, field, value)` the simulator read), plus a 10-minute expiry. The executor recomputes both before any write. A mismatch stops the affected items and sends only them back to simulation. Adapted from ECC's `operator-approval-loop` (epoch-keyed decisions; claim, dispatch, complete or unknown).

## Alternatives considered
- Approve the intent and trust the executor: fails the moment state drifts.
- Lock the records during review: not possible across Stripe and Telegram, and it blocks the business.

## Consequences
- Every tweak produces a new hash and a fresh simulation, so the screen always shows what will run.
- Drift is a first-class, visible outcome, which also gives the failure-test deliverable a concrete safety net.
- Simulators must record every field they read, or the fingerprint misses drift.
