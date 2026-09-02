# Current Project State

> Generated from validated repository state; do not edit manually.

- Generated at: 2026-08-30T18:00:00Z

## Current phase

- AO-P1: Trust and Benchmark Integrity (roadmap fallback)

## Immediate objective

- AO-D01: Day 1 produces confirmed, fail-closed status and boundary work with reproducible evidence. (roadmap fallback)

## Confirmed baseline

- Baseline commit: `39c041f699d7909d1f6853a89bf2a86835a4acd4`
- Snapshot input revision: `da7c5b8bef5e2ba0774c94c66615e73f915699ac`
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

## Verification evidence

- artifact-AO-D01-01-task-9-verification: verified (SHA-256: `2ff7601c69386527c51cd568ebe27625d2193573e3632a48e704ebb540036042`)
- uv run pytest tests/unit/test\_project\_control\_schema.py -q: passed — 122 passed in 0.11s
- uv run pytest tests/unit/test\_project\_control\_rendering.py -q: passed — 14 passed in 0.48s
- uv run pytest tests/unit/test\_project\_control\_handoffs.py tests/unit/test\_project\_control\_artifacts.py -q: passed — 20 passed in 0.13s
- uv run pytest tests/unit/test\_project\_control\_codegraph.py -q: passed — 14 passed in 1.32s
- uv run pytest tests/unit/test\_project\_control\_snapshots.py -q: passed — 52 passed
- uv run pytest tests/unit/test\_project\_control\_github.py tests/unit/test\_project\_control\_provisioning.py -q: passed — 70 passed in 0.09s
- uv run pytest tests/integration/test\_project\_control\_cli.py -q: passed — 23 passed in 5.84s
- uv run ruff check .: passed — All checks passed!
- uv run python scripts/project\_control.py validate: passed — Control room valid.
- uv run pytest -q: failed (exit 1) — 674 passed, 6 skipped, 2 failed in 81.50s
- npm --prefix web test: passed — 74 tests passed
- git diff --check: passed — no output recorded

## Latest decisions and handoffs

- None recorded.

## Code graph freshness

- Graph input provenance: `95978f5e2e3448adae2f52256a4750e4086f067d`; freshness is inconclusive until validated against the current source tree before relying on it.
- Fresh: the manifest source-tree digest matches tracked inputs.

## Onboarding commands

```bash
git status --short
uv run python scripts/project_control.py validate
uv run python scripts/project_control.py snapshot
```
