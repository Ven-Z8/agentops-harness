# Current Project State

> Generated from validated repository state; do not edit manually.

- Generated at: 2026-08-30T18:00:00Z

## Current phase

- AO-P1: Trust and Benchmark Integrity (roadmap fallback)

## Immediate objective

- AO-D01: Day 1 produces confirmed, fail-closed status and boundary work with reproducible evidence. (roadmap fallback)

## Confirmed baseline

- Baseline commit: `39c041f699d7909d1f6853a89bf2a86835a4acd4`
- Snapshot input revision: `c0cea0439a75e0ee509ccd78e4f04a2c50780820`
- Generated snapshot outputs are excluded; unavailable means validated inputs are dirty or provenance could not be resolved.

## Active blockers

- AO-14D: release-blocking
- AO-P1: release-blocking
- AO-P6: deferred until preceding gates
- AO-D01: phase
- AO-D01-01: phase
- AO-D01-02: phase
- AO-D01-03: phase
- AO-D01-04: phase
- AO-D02: phase
- AO-D02-01: phase
- AO-D02-02: phase
- AO-D02-03: phase
- AO-D02-04: phase
- AO-D02-05: phase
- AO-D13: deferred until preceding gates
- AO-D14: deferred until preceding gates
- AO-P2: deferred until Phase 1 gate
- AO-P3: deferred until Phase 2 gate
- AO-D03: deferred until Phase 1 gate
- AO-D04: deferred until Phase 1 gate
- AO-D05: deferred until Phase 1 gate
- AO-D06: deferred until Phase 2 gate
- AO-D07: deferred until Phase 2 gate
- AO-D08: deferred until Phase 2 gate
- AO-P4: deferred until kernel contracts
- AO-P5: deferred until kernel contracts
- AO-D09: deferred until kernel contracts
- AO-D10: deferred until kernel contracts
- AO-D11: deferred until kernel contracts
- AO-D12: deferred until kernel contracts

## Latest decisions and handoffs

- None recorded.

## Code graph freshness

- Graph input provenance: `ba264c3daa3775727318cf6e21beddb9319addf4`; freshness is inconclusive until validated against the current source tree before relying on it.
- Fresh: the manifest source-tree digest matches tracked inputs.

## Onboarding commands

```bash
git status --short
uv run python scripts/project_control.py validate
uv run python scripts/project_control.py snapshot
```
