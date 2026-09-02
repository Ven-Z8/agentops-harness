# AgentOps Project Control Room Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a vendor-neutral, Git-backed Project Control Room and provision the approved 14-day AgentOps roadmap into a GitHub Project without changing AgentOps runtime behavior.

**Architecture:** A strict `app.project_control` package owns schemas, loading, deterministic rendering, code-graph export, and GitHub synchronization. A thin `scripts/project_control.py` entry point exposes local commands and an explicit dry-run-first provisioning command. Git remains authoritative for approved roadmap scope and durable knowledge; GitHub Issues and Projects own live execution state; generated repository snapshots are read-only derivatives.

**Tech Stack:** Python 3.12, Pydantic 2, PyYAML, existing `RepoGraphBuilder`, `argparse`, `subprocess`-based Git/`gh` adapters, pytest, Ruff, GitHub GraphQL API.

**Spec:** `coordination/designs/2026-08-30-project-control-room-design.md`

## Global Constraints

- Work from baseline `39c041f699d7909d1f6853a89bf2a86835a4acd4` on `codex/project-control-room`.
- Preserve the original checkout and `stash@{0}`; never apply or drop the preserved handover stash during this work.
- Do not modify AgentOps experiment, evaluation, promotion, worker, workspace, permission, or training runtime behavior.
- Do not apply the optional handover patch for documentation commit `9c9c157`.
- Treat attached handover documents as source material; current repository evidence wins when facts disagree.
- Use Pydantic models with `ConfigDict(extra="forbid")`; invalid or unknown required state fails closed.
- Keep repository paths relative, normalized, non-symlinked, and inside the selected worktree.
- Keep approved roadmap identity/outcome/scope in Git and live workflow state in GitHub.
- Make generated output deterministic for identical source inputs; inject clocks in tests.
- Never overwrite a last-known-good generated file after invalid local or remote input.
- Keep GitHub mutation in `github-provision --apply`; every other command is local-only or read-only remote access.
- The default provisioning mode is dry-run; provisioning is idempotent and non-destructive.
- Do not commit secrets, raw tokens, private prompts, or non-portable evidence as if it were shared.
- Store this plan under `coordination/plans/`; repository hygiene rejects `docs/superpowers/`.
- Use one stable task ID in each branch, commit, handoff, and evidence record.
- Run Python and JavaScript verification and report failures exactly.

---

## File and responsibility map

| File | Responsibility |
| --- | --- |
| `app/project_control/errors.py` | Typed local, dependency, and remote reconciliation failures. |
| `app/project_control/models.py` | Strict configuration, roadmap, handoff, artifact, graph-manifest, and GitHub-plan models. |
| `app/project_control/io.py` | Safe YAML/JSON/Markdown-frontmatter loading and atomic writes. |
| `app/project_control/roadmap.py` | Roadmap validation and deterministic Markdown/issue-body rendering. |
| `app/project_control/handoffs.py` | Handoff creation, discovery, and terminal verification rules. |
| `app/project_control/artifacts.py` | Artifact-index validation and deterministic summary rendering. |
| `app/project_control/codegraph.py` | Existing graph-builder adapter, tracked-input digest, manifest, and summary. |
| `app/project_control/snapshots.py` | `CURRENT.md` and local `BOARD.md` renderers. |
| `app/project_control/github.py` | Injectable `gh` transport, read-only export, mutation planning, and reconciliation. |
| `app/project_control/cli.py` | Command parsing, orchestration, exit-code mapping, and user-safe output. |
| `scripts/project_control.py` | Thin executable wrapper calling `app.project_control.cli.main`. |
| `coordination/project.yaml` | Versioned project configuration and GitHub project identity. |
| `coordination/roadmap/14-day-plan.yaml` | Authoritative roadmap IDs, outcomes, scope, dependencies, evidence, and issue references. |
| `coordination/roadmap/14-day-plan.md` | Generated human-readable roadmap. |
| `coordination/PROJECT.md` | Stable product boundary. |
| `coordination/CURRENT.md` | Generated immediate state and next actions. |
| `coordination/BOARD.md` | Generated read-only GitHub workflow snapshot. |
| `coordination/handoffs/` | Structured agent-to-agent transfer records. |
| `coordination/decisions/` | Durable architecture and policy decisions. |
| `coordination/artifacts/` | Portable metadata index and summaries, not bulky evidence. |
| `coordination/codegraph/` | Generated graph JSON, summary, and freshness manifest. |
| `AGENTS.md` | One-hop universal entry point for every coding harness. |

## Stable 14-day roadmap inventory

The roadmap task records created in Task 2 use these exact IDs and titles.
Detailed Days 1–2 children are current-baseline work; Days 3–14 are outcome-level
records with `maturity: needs-revalidation`.

| ID | Title | Phase | Blocking classification |
| --- | --- | --- | --- |
| `AO-14D` | AgentOps 14-Day Research Control Plane | roadmap | release-blocking |
| `AO-P1` | Trust and Benchmark Integrity | Phase 1 | release-blocking |
| `AO-P2` | Experiment Kernel and DeepEval | Phase 2 | deferred until Phase 1 gate |
| `AO-P3` | Governed Training | Phase 3 | deferred until Phase 2 gate |
| `AO-P4` | Swappable Loops and Skills | Phase 4 | deferred until kernel contracts |
| `AO-P5` | VLM and VLA Reference Paths | Phase 5 | deferred until kernel contracts |
| `AO-P6` | Open-Source Release | Phase 6 | deferred until preceding gates |
| `AO-D01` | Truthful terminal states and strict boundaries | Phase 1 | Phase 1 blocker |
| `AO-D01-01` | Capture reproducible baseline and isolate ambient configuration | Phase 1 | Phase 1 blocker |
| `AO-D01-02` | Separate execution, evaluation, and promotion status | Phase 1 | Phase 1 blocker |
| `AO-D01-03` | Reject unknown provider, worker, workspace, policy, and pack kinds | Phase 1 | Phase 1 blocker |
| `AO-D01-04` | Fail closed on missing evidence and failed required commands | Phase 1 | Phase 1 blocker |
| `AO-D02` | Permission, sandbox, grounding, CI, and release integrity | Phase 1 | Phase 1 blocker |
| `AO-D02-01` | Normalize allow, ask, and deny semantics | Phase 1 | Phase 1 blocker |
| `AO-D02-02` | Make sandbox and security claims match enforcement | Phase 1 | Phase 1 blocker |
| `AO-D02-03` | Provide equal grounding packets to equivalent workers | Phase 1 | Phase 1 blocker |
| `AO-D02-04` | Run Python and JavaScript suites in CI | Phase 1 | Phase 1 blocker |
| `AO-D02-05` | Add OSI license and reconcile documentation and package drift | Phase 1 | Phase 1 blocker |
| `AO-D03` | Define experiment identity and immutable run records | Phase 2 | needs revalidation |
| `AO-D04` | Add a DeepEval provider adapter without leaking provider schema | Phase 2 | needs revalidation |
| `AO-D05` | Run split-safe coding benchmark comparison and promotion | Phase 2 | needs revalidation |
| `AO-D06` | Define governed training provider and budget contracts | Phase 3 | needs revalidation |
| `AO-D07` | Execute one tiny reproducible governed training run | Phase 3 | needs revalidation |
| `AO-D08` | Compare training evidence and make a promotion decision | Phase 3 | needs revalidation |
| `AO-D09` | Validate and record a swappable inner-loop capability pack | Phase 4 | needs revalidation |
| `AO-D10` | Validate and record a swappable outer-loop strategy pack | Phase 4 | needs revalidation |
| `AO-D11` | Complete one small reproducible VLM workflow | Phase 5 | needs revalidation |
| `AO-D12` | Verify the VLA provider and simulator seam | Phase 5 | needs revalidation |
| `AO-D13` | Close license, packaging, documentation, and release gates | Phase 6 | needs revalidation |
| `AO-D14` | Reproduce v0.1 end to end and publish honest limitations | Phase 6 | needs revalidation |

Every detailed Day 1–2 record also carries `likely_files`, `test_first`,
`terminal_semantics`, `compatibility`, `verification_commands`, `risks`, and
`rollback`. Use these exact starting points:

| ID | Likely files/modules | First failing test |
| --- | --- | --- |
| `AO-D01-01` | `app/core/config.py`, `app/core/workers/openhands_config.py`, provider/config tests | `tests/test_openhands_config.py::test_parent_dotenv_does_not_change_provider_config` |
| `AO-D01-02` | `app/schemas/run.py`, `app/core/graph.py`, `app/core/storage.py`, `app/core/benchmark.py`, `app/core/memory.py` | `tests/test_langgraph_workflow.py::test_required_test_failure_cannot_complete_or_converge` |
| `AO-D01-03` | `app/core/config.py`, `app/core/llm.py`, `app/cli.py`, `app/core/graph.py`, `app/core/workspace/`, `app/core/packs/` | `tests/test_boundary_kind_validation.py::test_unknown_boundary_kinds_fail_before_execution` |
| `AO-D01-04` | `app/core/workload.py`, `app/agents/evidence_guard.py`, `app/core/graph.py`, `app/schemas/evidence.py`, `app/schemas/workload.py` | `tests/test_workload.py::test_failed_required_command_cannot_pass` |
| `AO-D02-01` | `app/schemas/permission.py`, `app/agents/permission_gate.py`, `app/core/security.py`, `app/core/graph.py` | `tests/test_permission_gate.py::test_ask_requires_approval_and_is_not_completed` |
| `AO-D02-02` | `app/cli.py`, `app/core/workspace/local.py`, `app/core/workspace/docker.py`, `app/core/security.py`, `README.md`, sandbox tests | `tests/test_sandbox_worker_type_guard.py::test_full_isolation_claim_requires_enforced_container_boundary` |
| `AO-D02-03` | `app/core/graph.py`, `app/core/handoff.py`, `app/prompts/workers.py`, `app/core/workers/` | `tests/test_worker_grounding.py::test_equivalent_workers_receive_equal_grounding_packet` |
| `AO-D02-04` | `.github/workflows/ci.yml`, `web/package.json`, Python and web test suites | `tests/test_release_hygiene.py::test_ci_runs_python_and_javascript_suites` |
| `AO-D02-05` | `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `pyproject.toml`, `README.md`, package/release docs | `tests/test_release_hygiene.py::test_release_metadata_has_osi_license_and_consistent_identity` |

For these records, terminal semantics must explicitly say when work is failed,
blocked, or inconclusive and must prohibit inferred completion. Compatibility
must name persisted-schema, CLI, configuration, or documentation migration
effects. Verification commands must include the focused test, the affected
suite, Ruff, and any JavaScript/package checks. Risks must name false-success
and backward-compatibility hazards; rollback must revert only the task slice and
preserve truthful persisted evidence.

---

### Task 1: Strict control-room schemas and safe I/O

**Files:**
- Create: `app/project_control/__init__.py`
- Create: `app/project_control/errors.py`
- Create: `app/project_control/models.py`
- Create: `app/project_control/io.py`
- Create: `tests/conftest.py`
- Create: `tests/helpers_project_control.py`
- Create: `tests/unit/test_project_control_schema.py`

**Interfaces:**
- Consumes: Pydantic 2, PyYAML, `pathlib.Path`.
- Produces: `ProjectConfig`, `Roadmap`, `RoadmapItem`, `HandoffHeader`, `DecisionHeader`, `ArtifactIndex`, `GraphManifest`, `BoardItem`, `BoardExport`, `ControlRoomState`, `load_yaml(path, model_type, root)`, `load_frontmatter(path, model_type, root)`, and `atomic_write(path, content)`.

- [ ] **Step 1: Write failing strictness and path-safety tests**

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.project_control.io import load_yaml
from app.project_control.models import ProjectConfig, Roadmap
from tests.helpers_project_control import valid_project_config, valid_roadmap_item


def test_project_config_rejects_unknown_keys(tmp_path: Path) -> None:
    payload = valid_project_config()
    payload["unknown"] = True
    path = tmp_path / "project.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_yaml(path, ProjectConfig, root=tmp_path)


def test_roadmap_rejects_duplicate_ids() -> None:
    first = valid_roadmap_item("AO-D01")
    second = valid_roadmap_item("AO-D01")
    payload = {"schema_version": 1, "roadmap_id": "AO-14D", "items": [first, second]}
    with pytest.raises(ValidationError, match="duplicate"):
        Roadmap.model_validate(payload)


def test_roadmap_rejects_missing_dependency() -> None:
    item = valid_roadmap_item("AO-D01")
    item["dependencies"] = ["AO-X"]
    payload = {"schema_version": 1, "roadmap_id": "AO-14D", "items": [item]}
    with pytest.raises(ValidationError):
        Roadmap.model_validate(payload)


def test_load_yaml_rejects_symlink_input(tmp_path: Path) -> None:
    target = tmp_path / "target.yaml"
    target.write_text("schema_version: 1\n", encoding="utf-8")
    link = tmp_path / "linked.yaml"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="without symlink"):
        load_yaml(link, ProjectConfig, root=tmp_path)
```

- [ ] **Step 2: Run the focused tests and confirm the import failure**

Run: `uv run pytest tests/unit/test_project_control_schema.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'app.project_control'`.

- [ ] **Step 3: Implement strict models, cross-record validation, and atomic writes**

Use one shared strict base and exact enums:

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectStatus(StrEnum):
    PLANNED = "planned"
    READY = "ready"
    IN_PROGRESS = "in-progress"
    BLOCKED = "blocked"
    DONE = "done"


class EvidenceState(StrEnum):
    MISSING = "missing"
    INCONCLUSIVE = "inconclusive"
    PARTIAL = "partial"
    VERIFIED = "verified"


class VerificationState(StrEnum):
    NOT_RUN = "not_run"
    PARTIAL = "partial"
    FAILED = "failed"
    PASSED = "passed"
```

Define `ProjectConfig` with required `project`, `roadmap`, `github_project`, and
`generated` objects. Require `github_project.owner`; enforce `number` and `url`
as a pair with `@model_validator(mode="after")`. Define `Roadmap` so its model
validator rejects duplicate IDs, a missing `roadmap_id`, self-dependencies,
unknown dependencies, and dependency cycles. Define `DecisionHeader` with a
stable decision ID, status (`proposed`, `accepted`, `superseded`, `rejected`),
date, owners, task IDs, and optional superseding decision ID.

Implement safe resolution and replacement:

```python
T = TypeVar("T", bound=BaseModel)


def resolve_inside(path: Path, root: Path) -> Path:
    root_resolved = root.resolve(strict=True)
    if path.is_symlink():
        raise ValueError(f"Path must resolve inside repository without symlink: {path}")
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(root_resolved):
        raise ValueError(f"Path must remain inside repository: {path}")
    return resolved


def load_yaml(path: Path, model_type: type[T], *, root: Path) -> T:
    resolved = resolve_inside(path, root)
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected YAML mapping: {path}")
    return model_type.model_validate(payload)


def atomic_write(path: Path, content: str, *, root: Path) -> None:
    resolved = resolve_inside(path, root)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=resolved.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(resolved)
```

`load_frontmatter` requires the file to begin with `---`, finds the next exact
`---` line, parses only that slice with `yaml.safe_load`, requires a mapping,
and validates it with the requested model. A missing closing delimiter or an
empty/non-mapping header raises `InvalidControlRoom` with the file path.

`tests/helpers_project_control.py` provides complete valid dictionaries through
`valid_project_config()`, `valid_roadmap_item(task_id)`,
`seed_control_room(root)`, and `make_control_room_state()`. `tests/conftest.py`
provides `repo_root` as `Path(__file__).resolve().parents[1]` and
`control_room_state` from `make_control_room_state()` so later test snippets use
the same valid baseline rather than passing for unrelated missing fields.

- [ ] **Step 4: Add terminal-semantics tests and make them pass**

Add tests proving that a completed handoff with required verification rejects
`not_run`, `partial`, or `failed`; a blocked handoff requires `blocker` and
`required_authority`; a required unavailable artifact cannot claim verified
evidence; and full 40-character commit IDs are required.

Run: `uv run pytest tests/unit/test_project_control_schema.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the schema slice**

```bash
git add app/project_control tests/conftest.py tests/helpers_project_control.py tests/unit/test_project_control_schema.py
git commit -m "feat(control-room): add strict coordination schemas"
```

---

### Task 2: Authoritative 14-day roadmap and deterministic renderer

**Files:**
- Create: `app/project_control/roadmap.py`
- Create: `coordination/project.yaml`
- Create: `coordination/roadmap/14-day-plan.yaml`
- Create: `coordination/roadmap/14-day-plan.md`
- Create: `tests/unit/test_project_control_rendering.py`
- Modify: `app/project_control/models.py`

**Interfaces:**
- Consumes: `Roadmap`, `RoadmapItem`, `load_yaml`, stable inventory in this plan.
- Produces: `load_roadmap(root) -> Roadmap`, `render_roadmap(roadmap) -> str`, and `render_issue_body(item, roadmap) -> str`.

- [ ] **Step 1: Write failing roadmap completeness and rendering tests**

```python
EXPECTED_IDS = {
    "AO-14D", "AO-P1", "AO-P2", "AO-P3", "AO-P4", "AO-P5", "AO-P6",
    "AO-D01", "AO-D01-01", "AO-D01-02", "AO-D01-03", "AO-D01-04",
    "AO-D02", "AO-D02-01", "AO-D02-02", "AO-D02-03", "AO-D02-04", "AO-D02-05",
    "AO-D03", "AO-D04", "AO-D05", "AO-D06", "AO-D07", "AO-D08",
    "AO-D09", "AO-D10", "AO-D11", "AO-D12", "AO-D13", "AO-D14",
}


def test_committed_roadmap_has_complete_stable_inventory(repo_root: Path) -> None:
    roadmap = load_roadmap(repo_root)
    assert {item.id for item in roadmap.items} == EXPECTED_IDS
    assert all(item.maturity == "confirmed" for item in roadmap.items if item.day in {1, 2})
    assert all(item.maturity == "needs-revalidation" for item in roadmap.items if item.day and item.day >= 3)


def test_roadmap_render_is_deterministic(repo_root: Path) -> None:
    roadmap = load_roadmap(repo_root)
    first = render_roadmap(roadmap)
    second = render_roadmap(roadmap)
    assert first == second
    assert "Generated from `coordination/roadmap/14-day-plan.yaml`" in first
    assert "AO-D01-02" in first
```

- [ ] **Step 2: Run tests and confirm missing roadmap failures**

Run: `uv run pytest tests/unit/test_project_control_rendering.py -q`

Expected: FAIL because `app.project_control.roadmap` and roadmap YAML do not exist.

- [ ] **Step 3: Create exact project configuration and roadmap records**

Use the configuration from the approved design. Each roadmap YAML record has
this shape:

```yaml
- id: AO-D01-02
  title: Separate execution, evaluation, and promotion status
  kind: task
  day: 1
  phase_id: AO-P1
  parent_id: AO-D01
  status: planned
  maturity: confirmed
  priority: P0
  risk: critical
  blocker: phase
  outcome: A failed required execution or evaluation can never produce a completed or promoted run.
  scope:
    - Define independent execution, evaluation, and promotion terminal states.
    - Derive overall status from required stages without inferring success.
  non_goals:
    - Add DeepEval integration.
    - Redesign the experiment kernel.
  dependencies:
    - AO-D01-01
  acceptance_criteria:
    - Required test failure produces a non-successful run terminal state.
    - Promotion is impossible when execution or evaluation is failed or inconclusive.
  required_evidence:
    - Focused red-green test output.
    - Persisted run record showing independent statuses.
  likely_files:
    - app/schemas/run.py
    - app/core/graph.py
    - app/core/storage.py
    - app/core/benchmark.py
    - app/core/memory.py
  test_first: tests/test_langgraph_workflow.py::test_required_test_failure_cannot_complete_or_converge
  terminal_semantics: Failed or inconclusive required execution or evaluation prevents completion and promotion.
  compatibility: Additive persisted-run schema change with an explicit reader migration for existing records.
  verification_commands:
    - uv run pytest tests/test_langgraph_workflow.py::test_required_test_failure_cannot_complete_or_converge -q
    - uv run pytest tests/test_langgraph_workflow.py tests/test_benchmark.py tests/test_memory.py -q
    - uv run ruff check .
  risks:
    - Existing completed records may lack stage statuses and must not be reinterpreted silently.
  rollback: Revert the schema/derivation slice while retaining migrated records and recorded failing evidence.
  source_documents:
    - coordination/designs/2026-08-30-project-control-room-design.md
  github:
    issue_number: null
    issue_url: null
```

Create all IDs from the inventory table. Give every item concrete outcome,
scope, non-goals, dependencies, acceptance criteria, and required evidence.
Phase dependencies are `AO-P2 -> AO-P1`, `AO-P3 -> AO-P2`, `AO-P4 -> AO-P2`,
`AO-P5 -> AO-P2`, and `AO-P6 -> AO-P3, AO-P4, AO-P5`. Day dependencies form a
day-by-day chain; detailed children depend only on earlier children when the
implementation dependency is real. Days 3–14 must not assert that historical
defects still exist.

- [ ] **Step 4: Implement stable rendering and generate the committed Markdown**

```python
def render_roadmap(roadmap: Roadmap) -> str:
    lines = [
        "# AgentOps 14-Day Roadmap",
        "",
        "> Generated from `coordination/roadmap/14-day-plan.yaml`; do not edit manually.",
        "",
    ]
    for item in sorted(roadmap.items, key=roadmap_sort_key):
        lines.extend(render_item(item))
    return "\n".join(lines).rstrip() + "\n"


def roadmap_sort_key(item: RoadmapItem) -> tuple[int, int, str]:
    kind_order = {"roadmap": 0, "phase": 1, "outcome": 2, "task": 3}
    return (item.day or 0, kind_order[item.kind], item.id)


def render_issue_body(item: RoadmapItem, roadmap: Roadmap) -> str:
    return "\n".join([
        f"Task ID: {item.id}",
        "",
        "Source: `coordination/roadmap/14-day-plan.yaml`",
        "",
        "## Outcome",
        item.outcome,
        "",
        render_bullets("Scope", item.scope),
        render_bullets("Non-goals", item.non_goals),
        render_bullets("Dependencies", item.dependencies),
        render_bullets("Acceptance criteria", item.acceptance_criteria),
        render_bullets("Required evidence", item.required_evidence),
        render_bullets("Verification commands", item.verification_commands),
    ]).rstrip() + "\n"
```

Generate `14-day-plan.md`, rerun the renderer, and assert that a second run has
no diff.

Run: `uv run pytest tests/unit/test_project_control_schema.py tests/unit/test_project_control_rendering.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the roadmap slice**

```bash
git add app/project_control coordination/project.yaml coordination/roadmap tests/unit/test_project_control_rendering.py
git commit -m "feat(control-room): add authoritative 14-day roadmap"
```

---

### Task 3: Structured handoffs, decisions, and artifact metadata

**Files:**
- Create: `app/project_control/handoffs.py`
- Create: `app/project_control/artifacts.py`
- Create: `coordination/handoffs/README.md`
- Create: `coordination/decisions/README.md`
- Create: `coordination/artifacts/README.md`
- Create: `coordination/artifacts/index.yaml`
- Create: `coordination/templates/handoff.md`
- Create: `coordination/templates/decision.md`
- Create: `coordination/templates/daily-research-memo.md`
- Create: `tests/unit/test_project_control_handoffs.py`
- Create: `tests/unit/test_project_control_artifacts.py`

**Interfaces:**
- Consumes: `Roadmap`, `HandoffHeader`, `ArtifactIndex`, safe loaders and atomic writes.
- Produces: `create_handoff(root, task_id, harness, now, branch, base_commit, head_commit) -> Path`, `latest_handoffs(root) -> dict[str, Path]`, `load_artifact_index(root) -> ArtifactIndex`, and `render_artifact_summary(index) -> str`.

- [ ] **Step 1: Write failing handoff and artifact lifecycle tests**

```python
def test_create_handoff_uses_stable_name_and_required_sections(tmp_path: Path) -> None:
    seed_control_room(tmp_path)
    path = create_handoff(
        tmp_path,
        task_id="AO-D01-01",
        harness="codex",
        now=datetime(2026, 8, 30, 16, tzinfo=UTC),
        branch="codex/AO-D01-01-baseline",
        base_commit="1" * 40,
        head_commit="2" * 40,
    )
    assert path.name == "2026-08-30-AO-D01-01-codex.md"
    text = path.read_text(encoding="utf-8")
    assert "status: partial" in text
    assert "## Exact next action" in text


def test_required_unavailable_artifact_is_not_verified() -> None:
    with pytest.raises(ValidationError):
        ArtifactRecord.model_validate({
            "id": "artifact-AO-D01-01-baseline",
            "task_id": "AO-D01-01",
            "kind": "test-report",
            "availability": "unavailable",
            "locator": None,
            "required": True,
            "evidence_state": "verified",
            "created_at": "2026-08-30T16:00:00Z",
            "producer": "codex",
        })
```

- [ ] **Step 2: Run focused tests and confirm missing-module failures**

Run: `uv run pytest tests/unit/test_project_control_handoffs.py tests/unit/test_project_control_artifacts.py -q`

Expected: FAIL because lifecycle modules do not exist.

- [ ] **Step 3: Implement deterministic handoff creation and artifact summaries**

`create_handoff` validates the task ID against the roadmap, validates the
harness slug with `^[a-z0-9][a-z0-9-]{0,31}$`, refuses to overwrite an existing
handoff, and writes YAML frontmatter plus the six required body sections. The
frontmatter uses `status: partial`, `verification.state: not_run`, and empty
artifact/decision lists initially.

```python
def latest_handoffs(root: Path) -> dict[str, Path]:
    latest: dict[str, Path] = {}
    for path in sorted((root / "coordination/handoffs").glob("*.md")):
        header = load_frontmatter(path, HandoffHeader, root=root)
        previous = latest.get(header.task_id)
        if previous is None or path.name > previous.name:
            latest[header.task_id] = path
    return latest
```

Artifact rendering sorts by `(task_id, created_at, id)`, labels local locators
as non-portable, and renders unavailable required evidence as inconclusive.

- [ ] **Step 4: Add templates and verify terminal-state rules**

Create templates with exact headings. Handoff: `Objective and scope`,
`Completed work`, `Remaining work`, `Verification results`, `Known risks or
surprises`, and `Exact next action`. Decision: `Context`, `Decision`,
`Alternatives considered`, `Consequences`, `Evidence`, and `Revisit criteria`.
Daily memo: `Research question`, `Primary sources`, `Findings`,
`Counter-evidence and failed attempts`, `Decision`, `Implementation slice`,
`Evidence produced`, and `Next-day plan`. Template comments state required
frontmatter fields but contain no executable harness commands.

Add tests for duplicate artifact IDs, unknown task IDs, missing remote URI,
missing hash for immutable external evidence, invalid completed handoffs,
invalid decision status/supersession, all exact template headings, and
deterministic latest-handoff selection.

Run: `uv run pytest tests/unit/test_project_control_handoffs.py tests/unit/test_project_control_artifacts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the handoff/artifact slice**

```bash
git add app/project_control coordination/handoffs coordination/decisions coordination/artifacts coordination/templates tests/unit/test_project_control_handoffs.py tests/unit/test_project_control_artifacts.py
git commit -m "feat(control-room): add handoff and artifact contracts"
```

---

### Task 4: Deterministic repository code graph and freshness manifest

**Files:**
- Create: `app/project_control/codegraph.py`
- Create: `coordination/codegraph/graph.json`
- Create: `coordination/codegraph/summary.md`
- Create: `coordination/codegraph/manifest.json`
- Create: `tests/unit/test_project_control_codegraph.py`

**Interfaces:**
- Consumes: `RepoGraphBuilder.build(Path) -> RepoGraph`, Git tracked-file list, safe atomic writes.
- Produces: `tracked_graph_inputs(root) -> list[Path]`, `source_tree_digest(root, paths) -> str`, `build_export_graph(root, paths) -> RepoGraph`, `build_codegraph(root, now) -> GraphManifest`, and `validate_codegraph_freshness(root) -> None`.

- [ ] **Step 1: Write failing JavaScript coverage, digest, and traversal tests**

```python
def test_control_room_graph_marks_typescript_as_file_only(tmp_path: Path) -> None:
    (tmp_path / "web").mkdir()
    (tmp_path / "web/app.tsx").write_text("export const App = () => <main />;\n", encoding="utf-8")
    graph = build_export_graph(tmp_path, [Path("web/app.tsx")])
    assert "typescript" in graph.summary.languages
    assert any(node.path == "web/app.tsx" and node.language == "typescript" for node in graph.nodes)
    assert not any(node.type in {"function", "class", "method"} for node in graph.nodes)


def test_source_digest_ignores_generated_graph_files(repo_root: Path) -> None:
    paths = tracked_graph_inputs(repo_root)
    assert not any(path.as_posix().startswith("coordination/codegraph/") for path in paths)
    first = source_tree_digest(repo_root, paths)
    (repo_root / "coordination/codegraph/summary.md").write_text("changed\n", encoding="utf-8")
    assert source_tree_digest(repo_root, tracked_graph_inputs(repo_root)) == first


def test_control_room_graph_rejects_symlink_input(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("SECRET = 'not graph input'\n", encoding="utf-8")
    (tmp_path / "linked.py").symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        build_export_graph(tmp_path, [Path("linked.py")])
```

- [ ] **Step 2: Run tests and confirm the missing adapter behavior**

Run: `uv run pytest tests/unit/test_project_control_codegraph.py -q`

Expected: FAIL because the control-room graph adapter does not exist.

- [ ] **Step 3: Build an isolated tracked-file input tree and annotate file-only languages**

Reject any symlink input before reading it. Copy only validated tracked inputs
into a temporary directory, preserving relative paths, and run the existing
`RepoGraphBuilder` against that isolated tree. Normalize `repo_path` to `.` in
the exported model. On the deep-copied export only, annotate JavaScript and
TypeScript file nodes and test-file types; do not modify the runtime graph
builder and do not claim symbol-level parsing for these languages.

```python
def file_only_language(relative_path: str) -> str | None:
    suffix = Path(relative_path).suffix.lower()
    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        return "javascript"
    if suffix in {".ts", ".tsx", ".mts", ".cts"}:
        return "typescript"
    return None


def build_export_graph(root: Path, paths: list[Path]) -> RepoGraph:
    reject_symlink_inputs(root, paths)
    with TemporaryDirectory(prefix="agentops-codegraph-") as directory:
        isolated = Path(directory)
        copy_tracked_inputs(root, isolated, paths)
        graph = RepoGraphBuilder().build(isolated).model_copy(deep=True)
    graph.repo_path = "."
    annotate_file_only_languages(graph)
    return graph
```

- [ ] **Step 4: Implement deterministic export, digest, summary, and freshness validation**

Use `git ls-files -z` for tracked inputs. Exclude `coordination/codegraph/`,
`.git/`, ignored build/cache/vendor paths, and non-files. Hash each UTF-8 path,
a NUL delimiter, raw file bytes, and a second NUL delimiter in sorted path
order. Serialize the graph with sorted keys and two-space indentation.

```python
def source_tree_digest(root: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(paths, key=lambda value: value.as_posix()):
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update((root / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
```

The manifest records schema version, generator version, source commit, source
tree digest, included paths, exclusions, counts, generated time, and explicit
language coverage (`semantic`, `file-only`, `unsupported`). Freshness compares
the recomputed digest, not `HEAD`.

Run: `uv run pytest tests/test_repo_graph_builder.py tests/unit/test_project_control_codegraph.py -q`

Expected: PASS.

- [ ] **Step 5: Generate and commit code-graph outputs**

Before Task 6 adds the CLI, generate twice with the same injected time and
confirm the second invocation changes no tracked content:

```bash
uv run python -c 'from datetime import UTC, datetime; from pathlib import Path; from app.project_control.codegraph import build_codegraph; build_codegraph(Path.cwd(), datetime(2026, 8, 30, 18, 0, tzinfo=UTC))'
uv run python -c 'from datetime import UTC, datetime; from pathlib import Path; from app.project_control.codegraph import build_codegraph; build_codegraph(Path.cwd(), datetime(2026, 8, 30, 18, 0, tzinfo=UTC))'
```

After Task 6, the normal command is
`uv run python scripts/project_control.py codegraph`.

```bash
git add app/project_control/codegraph.py coordination/codegraph tests/unit/test_project_control_codegraph.py
git commit -m "feat(control-room): add deterministic repository code graph"
```

---

### Task 5: Generated current-state and offline board snapshots

**Files:**
- Create: `app/project_control/snapshots.py`
- Create: `coordination/CURRENT.md`
- Create: `coordination/BOARD.md`
- Create: `tests/unit/test_project_control_snapshots.py`
- Modify: `app/project_control/models.py`

**Interfaces:**
- Consumes: validated project/roadmap, artifact index, latest handoffs, optional `BoardExport`, injected UTC clock.
- Produces: `render_current(state, now) -> str`, `render_board(export, now) -> str`, `write_snapshots(root, board_export, now) -> None`, and `write_initial_snapshots(root, now) -> None`.

- [ ] **Step 1: Write failing deterministic and no-overwrite snapshot tests**

```python
def test_board_snapshot_declares_live_authority() -> None:
    export = BoardExport(project_url="https://github.com/users/Ven-Z8/projects/1", items=[])
    rendered = render_board(export, datetime(2026, 8, 30, 17, tzinfo=UTC))
    assert "Generated snapshot; do not edit manually" in rendered
    assert "GitHub Issues and Projects are authoritative for live execution state" in rendered


def test_invalid_export_does_not_replace_last_good_board(tmp_path: Path) -> None:
    board = tmp_path / "coordination/BOARD.md"
    board.parent.mkdir(parents=True)
    board.write_text("last good\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        write_snapshots(tmp_path, {"invalid": True}, datetime(2026, 8, 30, tzinfo=UTC))
    assert board.read_text(encoding="utf-8") == "last good\n"
```

- [ ] **Step 2: Run focused tests and confirm missing renderer failures**

Run: `uv run pytest tests/unit/test_project_control_snapshots.py -q`

Expected: FAIL because the snapshot module does not exist.

- [ ] **Step 3: Implement snapshot state assembly and rendering**

Sort active work by `(status_order, priority_order, day, id)`. `CURRENT.md`
must show current phase, immediate objective, baseline commit, active blockers,
latest decisions and handoffs, stale-codegraph status, and exact onboarding
commands. `BOARD.md` must show source revision, project URL, generation time,
phase summaries, blocked work, harness assignments, issue links, and handoff
links.

```python
STATUS_ORDER = {"blocked": 0, "in-progress": 1, "ready": 2, "planned": 3, "done": 4}
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def board_sort_key(item: BoardItem) -> tuple[int, int, int, str]:
    return (
        STATUS_ORDER[item.status],
        PRIORITY_ORDER[item.priority],
        item.day or 0,
        item.task_id,
    )
```

- [ ] **Step 4: Generate repository-only initial snapshots and verify stability**

The pre-provisioning `BOARD.md` says `GitHub project: not provisioned` and lists
roadmap items with their repository status. A second generation with the same
inputs and clock must be byte-identical.

Generate the committed initial files with:

```bash
uv run python -c 'from datetime import UTC, datetime; from pathlib import Path; from app.project_control.snapshots import write_initial_snapshots; write_initial_snapshots(Path.cwd(), datetime(2026, 8, 30, 18, 0, tzinfo=UTC))'
```

Run: `uv run pytest tests/unit/test_project_control_snapshots.py tests/unit/test_project_control_rendering.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the snapshot slice**

```bash
git add app/project_control/snapshots.py app/project_control/models.py coordination/CURRENT.md coordination/BOARD.md tests/unit/test_project_control_snapshots.py
git commit -m "feat(control-room): add generated project snapshots"
```

---

### Task 6: Local command-line workflow and universal agent entry point

**Files:**
- Create: `app/project_control/cli.py`
- Create: `scripts/project_control.py`
- Create: `AGENTS.md`
- Create: `coordination/README.md`
- Create: `coordination/PROJECT.md`
- Create: `tests/integration/test_project_control_cli.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: all local project-control services from Tasks 1–5.
- Produces: `main(argv: Sequence[str] | None = None) -> int` and commands `validate`, `snapshot`, `codegraph`, and `handoff`.

- [ ] **Step 1: Write failing CLI contract and one-hop onboarding tests**

```python
def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/project_control.py", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_validate_command_succeeds_on_committed_control_room() -> None:
    result = run_cli("validate")
    assert result.returncode == 0, result.stderr
    assert "control room valid" in result.stdout.lower()


def test_root_agents_file_links_control_room_in_one_hop() -> None:
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "coordination/README.md" in text
    assert "project_control.py validate" in text
```

- [ ] **Step 2: Run CLI tests and confirm missing-entry-point failures**

Run: `uv run pytest tests/integration/test_project_control_cli.py -q`

Expected: FAIL because the CLI and `AGENTS.md` do not exist.

- [ ] **Step 3: Implement exact local commands and exit semantics**

Use exit code `0` for success, `2` for invalid repository state or usage, `3`
for an unavailable required external dependency, and `4` for partial remote
reconciliation. Print errors to stderr without stack traces for expected
failures.

```python
def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except InvalidControlRoom as exc:
        print(f"control room invalid: {exc}", file=sys.stderr)
        return 2
    except DependencyUnavailable as exc:
        print(f"dependency unavailable: {exc}", file=sys.stderr)
        return 3
    except RemotePartialFailure as exc:
        print(f"remote reconciliation incomplete: {exc}", file=sys.stderr)
        return 4
```

`validate` loads every configured record, checks generated roadmap content and
graph digest, and reports each invalid path. `snapshot` writes repository-only
or last-export-backed snapshots. `codegraph` regenerates graph outputs.
`handoff --task ID --harness SLUG` captures branch and full commits from Git.

- [ ] **Step 4: Add universal documentation without tool-specific policy copies**

Root `AGENTS.md` contains the precedence order, six-step before-work protocol,
five-step during-work protocol, five-step handoff protocol, and the exact
validation command. `coordination/README.md` links the project boundary,
current state, roadmap, board, decisions, handoffs, artifacts, code graph,
templates, design, and plan. `PROJECT.md` reproduces the approved product
boundary and explicitly states VLM/VLA limitations. The root README adds one
short “Project Control Room” link section.

Run: `uv run pytest tests/integration/test_project_control_cli.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the local workflow slice**

```bash
git add AGENTS.md README.md app/project_control/cli.py scripts/project_control.py coordination/README.md coordination/PROJECT.md tests/integration/test_project_control_cli.py
git commit -m "feat(control-room): add universal agent workflow"
```

---

### Task 7: Read-only GitHub export

**Files:**
- Create: `app/project_control/github.py`
- Create: `tests/unit/test_project_control_github.py`
- Modify: `app/project_control/cli.py`
- Modify: `app/project_control/models.py`
- Modify: `tests/integration/test_project_control_cli.py`

**Interfaces:**
- Consumes: `GitHubProjectConfig`, injectable `GhTransport.graphql(query: str, variables: dict[str, object]) -> dict[str, object]`, validated GraphQL response.
- Produces: `GitHubClient.export_project(owner, number) -> BoardExport` and CLI command `board-export`.

- [ ] **Step 1: Write failing transport, schema, and safe-write tests**

```python
class FakeTransport:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def graphql(self, query: str, variables: dict[str, object]) -> dict[str, object]:
        self.calls.append((query, variables))
        return next(self.responses)


PROJECT_RESPONSE = {
    "data": {
        "user": {
            "projectV2": {
                "id": "PVT_1",
                "title": "AgentOps Research Control Plane — 14-Day v0.1",
                "url": "https://github.com/users/Ven-Z8/projects/1",
                "fields": {"nodes": []},
                "items": {
                    "nodes": [{
                        "id": "PVTI_1",
                        "content": {
                            "number": 1,
                            "title": "Capture reproducible baseline",
                            "url": "https://github.com/Ven-Z8/agentops-harness/issues/1",
                            "body": "Task ID: AO-D01-01\n",
                        },
                        "fieldValues": {"nodes": []},
                    }],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                },
            }
        }
    }
}
PROJECT_RESPONSE_WITHOUT_TASK_ID = copy.deepcopy(PROJECT_RESPONSE)
PROJECT_RESPONSE_WITHOUT_TASK_ID["data"]["user"]["projectV2"]["items"]["nodes"][0]["content"]["body"] = ""


def test_export_is_read_only_and_maps_task_ids() -> None:
    transport = FakeTransport([PROJECT_RESPONSE])
    export = GitHubClient(transport).export_project("Ven-Z8", 1)
    assert export.items[0].task_id == "AO-D01-01"
    assert all("mutation" not in query.lower() for query, _ in transport.calls)


def test_export_rejects_missing_task_id() -> None:
    transport = FakeTransport([PROJECT_RESPONSE_WITHOUT_TASK_ID])
    with pytest.raises(InvalidControlRoom, match="stable task ID"):
        GitHubClient(transport).export_project("Ven-Z8", 1)
```

- [ ] **Step 2: Run focused tests and confirm missing GitHub client failure**

Run: `uv run pytest tests/unit/test_project_control_github.py -q`

Expected: FAIL because `GitHubClient` does not exist.

- [ ] **Step 3: Implement authenticated read-only GraphQL export**

`SubprocessGhTransport.graphql` runs `gh api graphql --input -`, sends query/variables
as JSON on stdin, captures stdout/stderr, never prints environment variables,
and raises `DependencyUnavailable` for missing/unauthenticated `gh`. The query
fetches project ID/title/URL, field definitions/options, and paginated items
with issue number/title/URL/body plus field values. Extract task IDs only from
an exact `Task ID: AO-...` issue-body line.

```python
TASK_ID_LINE = re.compile(r"(?m)^Task ID: (AO-(?:14D|P[1-6]|D\d{2}(?:-\d{2})?))$")


def extract_task_id(body: str) -> str:
    match = TASK_ID_LINE.search(body)
    if match is None:
        raise InvalidControlRoom("GitHub issue is missing a stable task ID")
    return match.group(1)
```

- [ ] **Step 4: Add `board-export` with validated atomic replacement**

The command refuses to run while project number/URL are null. It exports all
pages, validates unique task IDs and expected fields, writes `BOARD.md` and
`CURRENT.md` only after full validation, and leaves previous files untouched on
transport, pagination, or schema failure.

Run: `uv run pytest tests/unit/test_project_control_github.py tests/integration/test_project_control_cli.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the export slice**

```bash
git add app/project_control tests/unit/test_project_control_github.py tests/integration/test_project_control_cli.py
git commit -m "feat(control-room): add read-only GitHub board export"
```

---

### Task 8: Idempotent GitHub provisioning planner and reconciliation

**Files:**
- Modify: `app/project_control/github.py`
- Modify: `app/project_control/cli.py`
- Modify: `app/project_control/models.py`
- Create: `tests/unit/test_project_control_provisioning.py`
- Modify: `tests/integration/test_project_control_cli.py`

**Interfaces:**
- Consumes: roadmap, existing remote project snapshot, `GhTransport`.
- Produces: `GitHubClient.discover_state(owner, repository, project_name) -> RemoteGitHubState`, `GitHubProvisioner.plan(state: ControlRoomState, remote: RemoteGitHubState) -> ProvisioningPlan`, `GitHubProvisioner.apply(plan: ProvisioningPlan) -> ReconciliationReport`, and CLI `github-provision --dry-run|--apply`.

- [ ] **Step 1: Write failing dry-run, idempotency, and partial-failure tests**

```python
def remote_state_for_roadmap(roadmap: Roadmap) -> RemoteGitHubState:
    return RemoteGitHubState(
        owner="Ven-Z8",
        repository="Ven-Z8/agentops-harness",
        project=RemoteProject(
            id="PVT_1",
            number=1,
            name="AgentOps Research Control Plane — 14-Day v0.1",
            url="https://github.com/users/Ven-Z8/projects/1",
        ),
        issues=[
            RemoteIssue(task_id=item.id, node_id=f"I_{item.id}", number=index, url=f"https://github.com/Ven-Z8/agentops-harness/issues/{index}")
            for index, item in enumerate(roadmap.items, start=1)
        ],
    )


class FailingMutationTransport(FakeTransport):
    def __init__(self, fail_after: int) -> None:
        super().__init__([])
        self.fail_after = fail_after

    def graphql(self, query: str, variables: dict[str, object]) -> dict[str, object]:
        self.calls.append((query, variables))
        if len(self.calls) > self.fail_after:
            raise RuntimeError("injected mutation failure")
        return {"data": {"node": {"id": f"NODE_{len(self.calls)}"}}}


def test_dry_run_performs_no_mutations(control_room_state: ControlRoomState) -> None:
    transport = FakeTransport([])
    remote = RemoteGitHubState(owner="Ven-Z8", repository="Ven-Z8/agentops-harness")
    plan = GitHubProvisioner(transport).plan(control_room_state, remote)
    assert plan.project.stable_key == "AgentOps Research Control Plane — 14-Day v0.1"
    assert len(plan.issue_actions) == len(control_room_state.roadmap.items)
    assert transport.calls == []


def test_existing_stable_ids_are_reused_without_duplicates(control_room_state: ControlRoomState) -> None:
    transport = FakeTransport([])
    remote = remote_state_for_roadmap(control_room_state.roadmap)
    plan = GitHubProvisioner(transport).plan(control_room_state, remote)
    assert plan.project.action == "reuse"
    assert all(action.action == "reuse" for action in plan.issue_actions)


def test_partial_apply_returns_reconciliation_report(control_room_state: ControlRoomState) -> None:
    transport = FailingMutationTransport(fail_after=3)
    remote = RemoteGitHubState(owner="Ven-Z8", repository="Ven-Z8/agentops-harness")
    plan = GitHubProvisioner(transport).plan(control_room_state, remote)
    report = GitHubProvisioner(transport).apply(plan)
    assert report.state == "partial"
    assert report.completed_object_ids
    assert report.remaining_actions
```

- [ ] **Step 2: Run provisioning tests and confirm missing-plan failures**

Run: `uv run pytest tests/unit/test_project_control_provisioning.py -q`

Expected: FAIL because provisioning models and services do not exist.

- [ ] **Step 3: Implement exact desired-state planning**

Desired project fields and options are exactly those in the approved design:
Status, Priority, Day, Phase, Workstream, Roadmap kind, Risk, Evidence, Harness,
Dependency, Handoff, and Target date. Desired views are Inbox, Kanban, Phase,
Harness, Trust Blockers, and Roadmap. Issue bodies come from
`render_issue_body`; issue lookup uses stable task IDs, not mutable titles.

```python
@dataclass(frozen=True)
class ProvisionAction:
    resource: Literal["project", "field", "view", "issue", "item", "field-value"]
    stable_key: str
    action: Literal["create", "reuse", "update"]
    remote_id: str | None
    payload: dict[str, object]
```

Sort actions by resource dependency and stable key. The plan is printable JSON
and Markdown. Dry-run performs account/repository/project discovery queries but
zero GraphQL mutations or `gh issue create/edit` calls.

- [ ] **Step 4: Implement resumable non-destructive apply**

Apply creates or reuses the project, fields/options, issues, project items,
field values, and supported views. After every successful mutation, retain its
node ID in the in-memory reconciliation report. On failure, stop dependent
actions, write a local report under `coordination/artifacts/reports/`, return
exit code 4, and preserve enough stable keys/IDs for a rerun. Never delete a
remote resource. Never rewrite unrelated issue-body content.

If view creation is unsupported by the authenticated GraphQL schema, record the
six exact manual view instructions and mark only the view portion partial; do
not report full success.

Run: `uv run pytest tests/unit/test_project_control_provisioning.py tests/unit/test_project_control_github.py tests/integration/test_project_control_cli.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the provisioning engine without remote mutation**

```bash
git add app/project_control tests/unit/test_project_control_provisioning.py tests/integration/test_project_control_cli.py
git commit -m "feat(control-room): add safe GitHub provisioning engine"
```

---

### Task 9: CI coverage, public hygiene, and complete local verification

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/public-hygiene.yml`
- Modify: `tests/integration/test_project_control_cli.py`
- Modify: `coordination/CURRENT.md`

**Interfaces:**
- Consumes: completed local CLI and generated coordination files.
- Produces: CI enforcement for Python, JavaScript, generated-file freshness, and control-room validity.

- [ ] **Step 1: Write failing workflow assertions**

```python
def test_ci_runs_python_javascript_and_control_room_validation(repo_root: Path) -> None:
    workflow = (repo_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "uv run --extra dev pytest -q" in workflow
    assert "npm test" in workflow
    assert "scripts/project_control.py validate" in workflow


def test_public_hygiene_allows_control_room_but_rejects_private_process_paths(repo_root: Path) -> None:
    workflow = (repo_root / ".github/workflows/public-hygiene.yml").read_text(encoding="utf-8")
    assert "docs/superpowers/" in workflow
    assert "Private tool-process docs must stay local" in workflow
    assert "coordination/" not in workflow.split("grep -E", maxsplit=1)[1].split("|| true", maxsplit=1)[0]
```

- [ ] **Step 2: Run the assertions and confirm JavaScript/validation coverage is absent**

Run: `uv run pytest tests/integration/test_project_control_cli.py::test_ci_runs_python_javascript_and_control_room_validation -q`

Expected: FAIL because current CI does not run the JavaScript suite or control-room validation.

- [ ] **Step 3: Add explicit Python, JavaScript, and control-room CI steps**

Add Node setup and execute the existing web package in its directory:

```yaml
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - run: uv sync --extra dev
      - run: uv run --extra dev ruff check .
      - run: uv run --extra dev pytest -q
      - run: npm test
        working-directory: web
      - run: uv run python scripts/project_control.py validate
```

The current `web/package.json` has no dependencies and runs Node's built-in test
runner, so CI must not invent a lockfile or dependency-install step.

In `public-hygiene.yml`, retain the existing rejected paths but change the
error text to `Private tool-process docs must stay local` and the success text
to `OK: no private tool-process docs tracked.` This distinguishes shared,
reviewed `coordination/` governance from private tool-process notes.

- [ ] **Step 4: Run the complete local verification matrix**

```bash
uv run pytest tests/unit/test_project_control_schema.py -q
uv run pytest tests/unit/test_project_control_rendering.py -q
uv run pytest tests/unit/test_project_control_handoffs.py tests/unit/test_project_control_artifacts.py -q
uv run pytest tests/unit/test_project_control_codegraph.py -q
uv run pytest tests/unit/test_project_control_snapshots.py -q
uv run pytest tests/unit/test_project_control_github.py tests/unit/test_project_control_provisioning.py -q
uv run pytest tests/integration/test_project_control_cli.py -q
uv run ruff check .
uv run pytest -q
npm --prefix web test
uv run python scripts/project_control.py validate
git diff --check
```

Record exact pass/fail counts in `CURRENT.md`. Environmental failures remain
failures or explicitly classified unavailable checks; they are never converted
to pass.

- [ ] **Step 5: Commit CI and verified generated state**

```bash
git add .github/workflows coordination/CURRENT.md tests/integration/test_project_control_cli.py
git commit -m "ci: validate project control room and web tests"
```

---

### Task 10: Dry-run review, explicit remote provisioning, and final reconciliation

**Files:**
- Modify after successful provisioning: `coordination/project.yaml`
- Modify after successful provisioning: `coordination/roadmap/14-day-plan.yaml`
- Regenerate after successful provisioning: `coordination/roadmap/14-day-plan.md`
- Regenerate after successful provisioning: `coordination/BOARD.md`
- Regenerate after successful provisioning: `coordination/CURRENT.md`
- Create: `coordination/artifacts/reports/AO-14D-github-provisioning.md`
- Create: `coordination/handoffs/2026-08-30-AO-14D-codex.md`

**Interfaces:**
- Consumes: authenticated `gh`, validated local control room, provisioning engine.
- Produces: one GitHub Project, linked issues/items/fields/views, reconciled local IDs, evidence report, and handoff.

- [ ] **Step 1: Confirm authentication and produce a mutation-free dry-run**

Run:

```bash
gh auth status
uv run python scripts/project_control.py validate
uv run python scripts/project_control.py github-provision --dry-run
```

Expected: authentication identifies the intended GitHub account; validation
passes; dry-run lists exact create/reuse/update actions and reports zero
mutations. Save the dry-run output as the first section of the provisioning
report with secrets excluded.

- [ ] **Step 2: Review the dry-run gate before remote mutation**

Verify the owner is `Ven-Z8`, repository is `Ven-Z8/agentops-harness`, project
name is exact, every stable roadmap ID appears exactly once, all twelve fields
are present, all six views are planned, later days carry
`needs-revalidation`, and no delete action exists. Present this report to the
user and obtain approval for `--apply` if the current execution session does
not already have approval for this exact reviewed mutation set.

- [ ] **Step 3: Apply the reviewed plan and reconcile remote state**

Run: `uv run python scripts/project_control.py github-provision --apply`

Expected: exit 0 only when all supported resources are created/reused and
verified. Exit 4 means partial; stop, preserve the reconciliation report, and
rerun only after diagnosing the exact remaining actions. Do not manually create
duplicates to bypass reconciliation.

- [ ] **Step 4: Export, validate, and capture evidence**

```bash
uv run python scripts/project_control.py board-export
uv run python scripts/project_control.py validate
uv run python scripts/project_control.py github-provision --dry-run
git diff --check
```

Expected: export succeeds, local validation passes, the second dry-run contains
only reuse/no-op results, and the report records project URL/number, issue and
item counts, field/view status, source commit, commands, exit codes, and any
manual view limitation.

- [ ] **Step 5: Write the final handoff and commit reconciled metadata**

Create an `AO-14D` handoff with `status: completed` only if required local and
remote verification passed. Otherwise use `partial` or `blocked` and identify
the exact next action and authority.

```bash
git add coordination/project.yaml coordination/roadmap coordination/BOARD.md coordination/CURRENT.md coordination/artifacts/reports coordination/handoffs
git commit -m "chore(control-room): reconcile GitHub project metadata"
```

Final verification:

```bash
uv run ruff check .
uv run pytest -q
npm --prefix web test
uv run python scripts/project_control.py validate
git status --short --branch
```

Report exact outputs, the GitHub Project URL, commit IDs, any unsupported view
automation, and any remaining non-Phase-1 roadmap item still awaiting current
revision revalidation.

---

## Review checkpoints

1. **After Task 2:** Confirm roadmap wording and dependency structure before it
   becomes the source for issue creation.
2. **After Task 4:** Review graph coverage and file-only JavaScript/TypeScript
   limitation before committing generated graph claims.
3. **After Task 8:** Review provisioning tests and the no-delete guarantee.
4. **After Task 9:** Require all local verification evidence before remote work.
5. **During Task 10:** Review the concrete dry-run before `--apply` and treat a
   partial result as partial.

## Rollback strategy

- Local implementation is split into one independently revertible commit per
  task; revert the smallest failing slice rather than resetting the branch.
- Generated files can be regenerated from their authorities after reverting a
  renderer.
- The provisioning engine never deletes remote objects. If a partially created
  project cannot be reconciled safely, pause with a partial report and request a
  user decision about retaining or manually archiving remote objects.
- Never erase the preserved pre-alignment stash or the original clean checkout.
- Do not roll back by changing evidence states, verification results, or
  terminal statuses to look successful.
