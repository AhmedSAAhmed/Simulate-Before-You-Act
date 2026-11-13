# Run report: {run-id}

Outcome: {match | halted | rolled_back}

## Request
{the operator's words}

## Predicted vs observed

| Effect | Predicted | Observed | Δ |
|---|---|---|---|
| {effect class} | {n / amount} | {n / amount} | {difference} |

## Invariants
- {invariant}: {held | broken: why}

## Rollback
- {action}: {restored | recalled | compensation drafted | not needed}

## What the simulator missed
{the side effect that wasn't predicted, or "nothing"}

## New simulator rule
{the rule or eval this gap adds, or "none"}
