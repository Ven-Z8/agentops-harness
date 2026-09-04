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

- ~~Positive-contract enforcement after the run~~ — **DONE** (db9869e, 2026-09-04): `evaluate_positive_contract` in `app/core/task_spec_gate.py`; `issue solve --task-spec` folds the verdict into `record.status` (exit 4 on violation, corrected record re-saved); JSONL storage got last-write-wins revision semantics so the corrected verdict is the one read back.
- ~~`environment` identity enforcement~~ — **DONE** (69e2550, 2026-09-04): `app/core/environment_guard.py` fail-closed verification of pinned image digests against the docker testbed; `issue solve` blocks before clone/dispatch (exit 5) and gained `--workspace local|docker`. Follow-up: enforce lockfile/python pins inside the container (image identity is enforced today; the others are disclosed as declared-but-unverified).
- ~~Benchmark fan-out~~ — **core DONE** (d6d6b73, 2026-09-04): `app/core/benchmark_fanout.py` — one spec × many workers → convergence-typed comparison with per-arm profiles + agreement metric; dispatch injected (hermetic tests). Follow-up: production `run_arm` wiring (extract the spec-solve pipeline from the CLI so the fan-out can drive real arms).
- Optional: an `ExperimentSpec` formalization unifying this with the VLM/VLA contract shape.

## Verification results

All commands + results in frontmatter `verification`. Pre-existing failures excluded (not caused by, and not touched by, this work): stale codegraph digest in `test_project_control_cli` (untracked-file tree drift, known "roadmap fallback" state), and `test_discovery_validates_repository_value_identity` (uncommitted WIP in `app/project_control/github.py` from a prior session — 1 ruff E501 also lives there). Both failures reproduce with this slice stashed.

2026-09-04 update: both pre-existing failures above are resolved on current main; CI is fully green (the recurring red-push root cause was a tracked `.DS_Store` in the digest inputs — fixed in 3bc3762).

## Known risks or surprises

- Test isolation matters: earlier test iterations polluted `.agentops/issues/` with stray clones (default workspace-root) and used randomized `hash()` for clone-dir naming — both fixed (isolated `--workspace-root`, deterministic commit-derived number). Strays were removed.
- Gate semantics chosen: pytest exit codes 2/4/5 treated as inconclusive, 1/3 as honest failure. If a target repo's test harness uses different exit conventions, the gate's mapping needs a per-spec override.
- `hash()`-based Python 3 randomization is a footgun for any deterministic naming — avoided by design here.

## Exact next action

Done as written: `tests/test_task_spec_solve.py::test_solve_enforces_positive_contract_after_run` exists and passes (db9869e). The kernel's next open actions: (1) production `run_arm` wiring for the fan-out (extract spec-solve from the CLI into a reusable pipeline), (2) in-container lockfile/python identity enforcement, (3) console live-dispatch slice (`POST /runs/spec/dispatch` + SSE progress) per the 2026-09-04 console critique.
