# Task 5 Snapshot Integrity Report

## Fix Round 2

- Commit: `4039cc0ea249f7f321f1699aa19e3cda900baebd`
- Scope recorded by the commit: retain an empty live export as authoritative,
  normalize rendered title whitespace, preserve graph provenance alongside a
  freshness result, validate decision and handoff records, and clean a first
  temporary snapshot if the second preparation fails.
- Committed snapshot SHA-256 values at that revision:
  - `coordination/CURRENT.md`:
    `741aece1acb13c37d68e6e7e385ae8aa6969a145642c6286c913a313dcf88ff4`
  - `coordination/BOARD.md`:
    `ae1da2b8136f5148d1feac3f2642ed6309f7cc6acdd6f544919665797aa582d0`
- The repository does not contain preserved command output for that historical
  commit. Fix Round 3 reran the complete Task 5 verification suite below.

## Fix Round 3

- Snapshot rendering now rejects invalid single-line identifiers and unsafe
  link targets for every BoardExport URL and identifier field. Display text is
  normalized to one line and escaped for Markdown tables and lists.
- The regression probes `project_url`, `task_id`, `phase_id`, `harness`,
  `issue_url`, and `handoff`; it also verifies hostile title, dependency, and
  blocker text cannot forge headings, table cells, or links.
- The two-destination writer has a regression for second-temporary-file
  preparation failure: it leaves both destination files unchanged and removes
  the first temporary file.
- `CURRENT.md` renders graph provenance and a separately evaluated freshness
  state. A missing graph uses `Graph provenance unavailable; freshness
  inconclusive.` exactly once.
- All file-wide `# ruff: noqa: E501` suppressions in `app/project_control`
  and the snapshot test were removed and their lines were wrapped.

### Verification

- Decision test filename determined with `rg --files tests | rg decision`:
  no standalone filename exists; decision behavior is covered by
  `tests/unit/test_project_control_handoffs.py`.
- `uv run pytest tests/unit/test_project_control_snapshots.py
  tests/unit/test_project_control_rendering.py
  tests/unit/test_project_control_schema.py
  tests/unit/test_project_control_handoffs.py -q`: `79 passed in 0.37s`.
- `uv run ruff check app/project_control
  tests/unit/test_project_control_snapshots.py`: `All checks passed!`.
- `uv run ruff check --ignore-noqa app/project_control
  tests/unit/test_project_control_snapshots.py`: `All checks passed!`.

### Deterministic fixed-clock snapshots

Both runs used `2026-08-30T18:00:00Z` and produced identical SHA-256 values:

- `coordination/CURRENT.md`:
  `a0239fbf84f44c4fa02506aeb48c18b2020f7ac133a32670e6a41224c407bcb6`
- `coordination/BOARD.md`:
  `e7cd6d8b869c530ce458d56966ee4fbffaee17e3a131fb7055f942d72666df57`

The committed snapshot-byte comparison is recorded after the scoped commit.
