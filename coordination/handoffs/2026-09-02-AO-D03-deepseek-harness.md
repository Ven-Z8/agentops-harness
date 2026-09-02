---
schema_version: 1
task_id: AO-D03
harness: deepseek-harness
status: partial
started_at: 2026-09-02T19:40:00Z
updated_at: 2026-09-02T21:05:00Z
branch: main
base_commit: 8150ea037ec4f84d52f116abb12e9cb151f5a554
head_commit: bed6a9bf8a12a64ae6070b15fbc353d9c91d31af
verification:
  required: false
  state: passed
  commands:
    - "UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev pytest tests/test_task_spec.py tests/test_task_spec_solve.py -q → 10 passed"
    - "UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev pytest -q (deselecting 2 pre-existing WIP failures) → 750 passed, 6 skipped, twice consecutively"
    - "UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev ruff check (files in artifacts) → All checks passed"
    - "npm --prefix web test → 74 tests, 74 pass, 0 fail"
artifacts:
  - app/schemas/task_spec.py
  - app/core/task_spec_gate.py
  - app/cli.py
  - tests/test_task_spec.py
  - tests/test_task_spec_solve.py
decisions:
  - "Task-spec contract (SweTaskSpec) is the first ExperimentSpec: the flagship issue path is its execution provider (ROADMAP.md item 3)."
  - "base_commit rejects movable refs (HEAD) — non-reproducible tasks fail at spec validation."
  - "Negative-contract gate blocks (exit 3) before worker dispatch: no reproducible bug, no run; inconclusive (non-runnable test) never becomes an inferred pass."
  - "Spec mode does not fetch the gh issue — the spec file alone reproduces the run identity."
---

## Objective and scope

Phase 2 kernel entry (AO-D03 class): make the flagship issue path deterministic via a SWE-bench-style task-spec contract — pinned base_commit, FAIL_TO_PASS/PASS_TO_PASS dual assertions, negative-contract gate proving the bug at base before dispatch. Scope: schema + gate + `issue solve --task-spec` wiring. No benchmark comparison, no DeepEval, no VLM/VLA (phase-gated).

## Completed work

- `SweTaskSpec` pydantic schema with SWE-bench Verified field convention; `from_swebench_instance` parses the official dataset JSON (string-encoded test lists).
- `evaluate_negative_contract` gate: runs every fail_to_pass test at base_commit; PASS at base → blocks ("not reproducible"); error exits (2/4/5) → blocks as inconclusive. Evidence (commands, exit codes, output tails) returned for the run record.
- `issue solve --task-spec <file> --clone-url <url>`: clones at base_commit (no gh fetch in spec mode), gate runs before dispatch, exit 3 on gate failure. Task contract = spec's problem_statement.
- 10 tests: 4 schema (incl. HEAD rejection, ≥1 fail_to_pass, SWE-bench JSON parse), 4 gate (block-on-pass, pass-on-bug, block-on-error, evidence recording), 2 CLI (fail-closed blocks dispatch; happy path pins commit + composes task).
- Red→green evidence: initial run failed with ModuleNotFoundError (schema absent); each slice went green against its own tests before the next.

## Remaining work

- Positive-contract enforcement after the run: FAIL_TO_PASS must pass AND PASS_TO_PASS must still pass on the patched tree (currently `--test-commands` covers this manually).
- `environment` identity (image digest / lockfile digest) is defined but not yet enforced — hermetic Docker testbed wiring is the next slice (`app/core/workspace/docker.py` exists).
- Benchmark fan-out: same spec → multiple workers → convergence-typed comparison (`app/core/benchmark.py` ready).
- Optional: an `ExperimentSpec` formalization unifying this with the VLM/VLA contract shape.

## Verification results

All commands + results in frontmatter `verification`. Pre-existing failures excluded (not caused by, and not touched by, this work): stale codegraph digest in `test_project_control_cli` (untracked-file tree drift, known "roadmap fallback" state), and `test_discovery_validates_repository_value_identity` (uncommitted WIP in `app/project_control/github.py` from a prior session — 1 ruff E501 also lives there). Both failures reproduce with this slice stashed.

## Known risks or surprises

- Test isolation matters: earlier test iterations polluted `.agentops/issues/` with stray clones (default workspace-root) and used randomized `hash()` for clone-dir naming — both fixed (isolated `--workspace-root`, deterministic commit-derived number). Strays were removed.
- Gate semantics chosen: pytest exit codes 2/4/5 treated as inconclusive, 1/3 as honest failure. If a target repo's test harness uses different exit conventions, the gate's mapping needs a per-spec override.
- `hash()`-based Python 3 randomization is a footgun for any deterministic naming — avoided by design here.

## Exact next action

Wire the positive contract: after `run_harness` returns in spec mode, run FAIL_TO_PASS (must exit 0) and PASS_TO_PASS (must still exit 0) against the patched tree, and fold the result into `record.status` (a fix that regresses PASS_TO_PASS must fail the run). First failing test: `tests/test_task_spec_solve.py::test_solve_enforces_positive_contract_after_run` (not yet written).
