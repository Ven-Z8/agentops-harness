# Current Project State

> Generated from validated repository state; do not edit manually.

- Generated at: 2026-08-30T18:00:00Z

## Current phase

- Unassigned (live board)

## Immediate objective

- AO-D01-01: Capture reproducible baseline

## Confirmed baseline

- Baseline commit: `39c041f699d7909d1f6853a89bf2a86835a4acd4`
- Snapshot input revision: `e20e5f27a569df029ee587632c48bccdee67851d`
- Generated snapshot outputs are excluded; unavailable means validated inputs are dirty or provenance could not be resolved.

## Active blockers

- None recorded.

## Latest decisions and handoffs

- None recorded.

## Code graph freshness

- Graph input provenance: `f0ed27f229e6485ab95d6ee43a18adacd0e43250`; freshness is inconclusive until validated against the current source tree before relying on it.
- Fresh: the manifest source-tree digest matches tracked inputs.

## Onboarding commands

```bash
git status --short
uv run python scripts/project_control.py validate
uv run python scripts/project_control.py snapshot
```
