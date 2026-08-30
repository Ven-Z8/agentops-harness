# AgentOps Project Control Room Design

**Status:** Approved design, pending written-spec review

**Date:** 2026-08-30

**Branch:** `codex/project-control-room`

**Repository baseline:** `39c041f699d7909d1f6853a89bf2a86835a4acd4`

## 1. Purpose

AgentOps needs a vendor-neutral coordination layer that lets Codex, Claude Code,
Pi, OpenCode, Qwen Code, Antigravity, humans, and future harnesses work from the
same durable project context. The control room will provide:

- a short, reliable entry point for every agent;
- approved product boundaries and current project state;
- a stable 14-day roadmap with durable task identifiers;
- structured handoffs, decisions, and artifact metadata;
- a generated repository code graph;
- a local board snapshot for agents without GitHub access; and
- a GitHub Projects board for live execution workflow.

This is a coordination and governance system, not a replacement for Git,
GitHub Issues, CI, experiment evidence, or specialist agent runtimes.

## 2. Instruction and evidence precedence

Attached handover documents are source material, not executable instructions.
Repository-local instructions and the user's current request govern the work.
When older observations disagree with the current repository, current evidence
wins and the disagreement is recorded rather than silently forcing the old plan.

The optional handover patch associated with documentation commit `9c9c157` is
not applied automatically. A newer repository copy must never be silently
replaced by an older bundle copy.

Agents use this precedence order:

1. the user's current request;
2. repository-local `AGENTS.md` instructions;
3. approved product and architecture decisions;
4. current repository code, tests, CI, packaging, and generated evidence;
5. attached or historical handover material.

## 3. Authority model

Each kind of state has one authority. Derived copies must link to their source
and must not become competing editable records.

| State | Authority | Derived representation |
| --- | --- | --- |
| Source code and durable project knowledge | Git repository | GitHub rendering |
| Approved roadmap identity, outcomes, and scope | `coordination/roadmap/14-day-plan.yaml` | Roadmap Markdown and issue bodies |
| Live execution state, assignment, priority, and operational notes | GitHub Issues and Projects | `coordination/BOARD.md` |
| Architecture and policy decisions | `coordination/decisions/` | Links in issues and handoffs |
| Agent handoffs | `coordination/handoffs/` | Links in issues and board snapshot |
| Artifact metadata | `coordination/artifacts/index.yaml` | Artifact summary Markdown |
| Experiment evidence | Existing AgentOps evidence stores | Metadata links in the artifact index |
| Repository topology | Current tracked source tree | Generated code-graph files |

GitHub issue bodies are generated initially from the approved roadmap. Later
operational additions may live in the issue, but changing the approved outcome
or product scope requires a repository decision and roadmap update. This avoids
making either Git or GitHub an ambiguous duplicate source of truth.

## 4. Repository layout

The implementation will add this structure:

```text
AGENTS.md
coordination/
  README.md
  PROJECT.md
  CURRENT.md
  project.yaml
  BOARD.md
  designs/
    2026-08-30-project-control-room-design.md
  roadmap/
    14-day-plan.yaml
    14-day-plan.md
  handoffs/
    README.md
  decisions/
    README.md
  artifacts/
    README.md
    index.yaml
  codegraph/
    graph.json
    summary.md
    manifest.json
  templates/
    handoff.md
    decision.md
    daily-research-memo.md
scripts/
  project_control.py
tests/
  unit/
    test_project_control_schema.py
    test_project_control_rendering.py
    test_project_control_codegraph.py
  integration/
    test_project_control_cli.py
```

The repository root `AGENTS.md` is deliberately brief. It points every harness
to `coordination/README.md`, defines the universal protocol, and names any
tool-specific instruction files without copying policy into them.

`coordination/README.md` is the human and agent index. `PROJECT.md` describes
the stable product boundary. `CURRENT.md` and `BOARD.md` are generated current
state. `project.yaml` contains machine-readable configuration and schema
versioning.

## 5. Universal agent protocol

Every participating harness follows the same protocol.

### Before work

1. Read root `AGENTS.md` and `coordination/README.md`.
2. Read `PROJECT.md`, `CURRENT.md`, and the task's GitHub issue or local roadmap
   record.
3. Run `project_control.py validate`.
4. Confirm the task identifier, dependencies, acceptance criteria, authority,
   and allowed scope.
5. Inspect relevant decisions and the latest handoff for the task.
6. Confirm the worktree and preserve unrelated changes.

### During work

1. Use the stable task ID in the branch, commits, evidence, and handoff.
2. Work test-first for behavior changes.
3. Record scope-changing decisions rather than hiding them in chat history.
4. Treat missing or invalid required evidence as inconclusive, never passed.
5. Do not update generated snapshots manually.

### At handoff

1. Run task-specific verification and record exact commands and results.
2. Write a structured handoff with completed, remaining, blocked, and risk
   information.
3. Link commits, changed files, decisions, and available evidence.
4. Refresh generated local state.
5. Update GitHub workflow state if the agent is authorized and authenticated;
   otherwise leave an explicit requested update in the handoff.

## 6. Project configuration

`coordination/project.yaml` uses a versioned, fail-closed schema. Unknown keys
are rejected unless a future schema explicitly allows them.

```yaml
schema_version: 1
project:
  id: agentops-harness
  name: AgentOps Research Control Plane
  repository: Ven-Z8/agentops-harness
  default_branch: main
roadmap:
  id: AO-14D
  source: coordination/roadmap/14-day-plan.yaml
github_project:
  owner: Ven-Z8
  number: null
  url: null
generated:
  board: coordination/BOARD.md
  current: coordination/CURRENT.md
  codegraph: coordination/codegraph
```

Validation rules include:

- `schema_version` must be supported;
- repository paths must be relative, normalized, and remain in the worktree;
- task and roadmap identifiers must be unique;
- referenced dependencies must exist;
- the GitHub owner must be non-empty;
- GitHub project `number` and `url` must be either both null or both populated;
- generated files must identify their source and generation metadata; and
- unknown enum values or object keys fail validation.

Before remote provisioning, `number` and `url` are null. The provisioning flow
populates them together after confirming the created or reused project.

The schema should use the repository's existing Python validation stack where
appropriate, including Pydantic, with YAML parsing kept explicit and safe.

## 7. Structured handoffs and artifacts

### Handoff contract

Each handoff is Markdown with YAML frontmatter. A filename includes the UTC date,
task ID, and harness slug:

```text
coordination/handoffs/2026-08-30-AO-D01-01-codex.md
```

Required fields:

```yaml
schema_version: 1
task_id: AO-D01-01
harness: codex
status: partial
started_at: 2026-08-30T15:00:00Z
updated_at: 2026-08-30T16:00:00Z
branch: codex/project-control-room
base_commit: 39c041f699d7909d1f6853a89bf2a86835a4acd4
head_commit: 39c041f699d7909d1f6853a89bf2a86835a4acd4
verification:
  state: not_run
  commands: []
artifacts: []
decisions: []
```

Allowed handoff statuses are `completed`, `partial`, `blocked`, and
`abandoned`. Verification states are `passed`, `failed`, `partial`, and
`not_run`. A completed handoff cannot use `failed`, `partial`, or `not_run` when
the task declares required verification. Full commit IDs are required. A
blocked handoff must identify the blocker and the authority needed to remove it.

The Markdown body contains:

- objective and scope;
- completed work;
- remaining work;
- verification results;
- known risks or surprises; and
- exact next action.

### Artifact index

`coordination/artifacts/index.yaml` stores metadata, not bulky evidence:

```yaml
schema_version: 1
artifacts:
  - id: artifact-AO-D01-01-baseline
    task_id: AO-D01-01
    kind: test-report
    availability: repository
    locator: coordination/artifacts/reports/AO-D01-01-baseline.md
    sha256: null
    created_at: 2026-08-30T16:00:00Z
    producer: codex
```

Allowed availability values are `repository`, `local`, `remote`, and
`unavailable`. Local locators such as ignored `.agentops/` output are explicitly
non-portable. Remote locators require a durable URI. Required unavailable
evidence remains unavailable or inconclusive; it is never inferred from a
summary. Content hashes are required for immutable binary or external evidence
when available.

## 8. Code graph

The code graph reuses the repository's existing `RepoGraphBuilder` rather than
creating an unrelated parser. The generator emits:

- `graph.json`: nodes, edges, languages, paths, symbols, and graph schema;
- `summary.md`: human-readable module and dependency overview; and
- `manifest.json`: generator version, source commit, source-tree digest,
  included paths, exclusions, counts, and generation time.

The source-tree digest is computed deterministically from the tracked graph
inputs while excluding generated code-graph outputs and ignored files. Freshness
validation compares this digest, not only `HEAD`, because committing a generated
graph or documentation would otherwise make the graph immediately appear stale.
The source commit remains useful provenance.

Symlinks and paths outside the repository are rejected. Generated output must
be byte-stable for identical source inputs, apart from explicitly isolated
metadata such as generation time. The tool reports unsupported or partially
parsed languages honestly instead of implying a complete semantic graph.

## 9. Fourteen-day task model

Stable IDs prevent names from drifting across harnesses, Git commits, and
GitHub. The hierarchy is:

- `AO-14D`: roadmap;
- `AO-P1` through `AO-P6`: phase trackers;
- `AO-D01` through `AO-D14`: daily outcomes; and
- child tasks such as `AO-D01-01` for independently reviewable work.

Every roadmap item records:

- ID and title;
- day and phase;
- outcome and scope;
- status and maturity;
- dependencies;
- acceptance criteria;
- required evidence;
- blocker classification;
- source documents; and
- GitHub issue number and URL after provisioning.

The repository roadmap is the approved source for identity, outcome, and scope.
GitHub owns live execution state and assignment. `14-day-plan.md` and issue
bodies are rendered from the YAML at creation; later scope changes require a
decision and source update before synchronization.

Days 1–2 receive detailed, test-driven child tasks based on the confirmed
current baseline. Later days are created at outcome level and marked
`needs-revalidation`, preventing historical research observations from being
presented as current implementation facts.

## 10. GitHub project design

The GitHub Project is named:

> AgentOps Research Control Plane — 14-Day v0.1

Initial items are:

- one roadmap issue;
- six phase tracker issues;
- fourteen day-outcome issues;
- detailed Day 1–2 trust and benchmark-integrity child issues; and
- later-day outcomes clearly labeled `needs-revalidation`.

Custom fields:

| Field | Purpose |
| --- | --- |
| Status | Inbox, Ready, In progress, In review, Blocked, Done |
| Priority | P0, P1, P2, P3 |
| Day | Day 1 through Day 14 |
| Phase | Phase 1 through Phase 6 |
| Workstream | Trust, kernel, training, packs, VLM/VLA, release |
| Type | Roadmap, phase, outcome, task, decision, research |
| Risk | Critical, high, medium, low |
| Evidence | Missing, inconclusive, partial, verified |
| Harness | Unassigned or harness slug |
| Dependency | Short dependency summary |
| Handoff | URL to the latest committed handoff |
| Target date | Calendar target when scheduling is approved |

Views:

1. **Inbox** — new and untriaged work.
2. **Kanban** — grouped by Status.
3. **Phase** — grouped by Phase and sorted by Day.
4. **Harness** — grouped by Harness for multi-agent coordination.
5. **Trust Blockers** — Phase 1 P0/P1 work not done.
6. **Roadmap** — day and target-date view.

Issue bodies include the stable task ID, source roadmap link, scope, explicit
non-goals, dependencies, acceptance criteria, required verification and
evidence, and latest handoff link. Labels remain lightweight and portable;
project fields carry board-specific workflow data.

## 11. Local snapshot and current-state files

`coordination/BOARD.md` is a generated, read-only snapshot for offline agents.
It contains generation time, project URL, source revision, phase summaries,
blocked work, active assignments, and issue links. A banner says not to edit it
manually and identifies GitHub as the live execution-state authority.

`coordination/CURRENT.md` is generated from validated repository state plus the
latest board export. It contains the current phase, immediate objective,
confirmed baseline, active blockers, most recent decisions and handoffs, and
the commands a new agent should run.

If GitHub is unavailable, export fails without overwriting the last valid
snapshot. Repository-only validation and code-graph generation still work.

## 12. Command surface and remote safety

One dependency-light Python entry point keeps behavior consistent:

```bash
uv run python scripts/project_control.py validate
uv run python scripts/project_control.py snapshot
uv run python scripts/project_control.py codegraph
uv run python scripts/project_control.py handoff --task AO-D01-01 --harness codex
uv run python scripts/project_control.py board-export
uv run python scripts/project_control.py github-provision --dry-run
uv run python scripts/project_control.py github-provision --apply
```

Commands that only read or generate repository files never mutate GitHub.
`board-export` uses authenticated, read-only `gh api graphql` queries and writes
only after the response passes schema validation.

`github-provision` is a separate, explicit remote operation. Its default mode is
dry-run. `--apply` performs these idempotent steps:

1. verify authenticated account and repository access;
2. resolve or create the named project without duplicating an existing match;
3. create or reuse fields and field options by exact name;
4. create or reuse roadmap, phase, outcome, and task issues by stable ID;
5. add each issue to the project once;
6. assign project fields;
7. create or reuse the six specified views where supported;
8. verify counts and identifiers;
9. update `project.yaml` and roadmap issue references; and
10. export a validated local snapshot.

The dry-run displays the complete mutation plan first. Partial remote failures
produce a reconciliation report and preserve discovered IDs so a rerun can
resume safely. The provisioner never deletes projects, issues, fields, views,
or user content. Unsupported API capabilities are reported explicitly and
become documented manual steps rather than fabricated success.

## 13. Testing and verification

Implementation is test-driven. Each behavior starts with a failing test.

### Schema tests

- valid configuration, roadmap, handoff, decision, and artifact records pass;
- unknown keys, enums, task IDs, dependencies, and unsafe paths fail closed;
- duplicate IDs fail;
- completed handoffs with missing required verification fail; and
- paired GitHub project identifiers validate consistently.

### Rendering and determinism tests

- roadmap, current state, board, and code graph are stable for identical input;
- generated files declare their source and do-not-edit status;
- task ordering is stable;
- timestamps can be injected in tests; and
- stale graph input digests are detected without false positives from generated
  or documentation-only commits.

### Safety tests

- symlink and path traversal are rejected;
- failed GitHub responses do not overwrite valid snapshots;
- dry-run makes no remote mutations;
- repeated provisioning does not duplicate items; and
- partial provisioning creates a usable reconciliation report.

### Integration tests

- CLI exit codes distinguish success, invalid state, unavailable dependency,
  and remote partial failure;
- the existing repository graph builder is exercised on a small fixture;
- mocked GitHub GraphQL responses produce the expected snapshot; and
- all documented commands match real CLI help.

Verification for the implementation includes:

```bash
uv run pytest tests/unit/test_project_control_schema.py -q
uv run pytest tests/unit/test_project_control_rendering.py -q
uv run pytest tests/unit/test_project_control_codegraph.py -q
uv run pytest tests/integration/test_project_control_cli.py -q
uv run ruff check .
uv run pytest -q
npm test
uv run python scripts/project_control.py validate
git diff --check
```

Remote provisioning additionally requires captured dry-run output, created or
reused object IDs, field and view reconciliation, issue counts, and a successful
read-only export after mutation.

## 14. Security and privacy

- No secrets, tokens, private prompts, or raw credentials are committed.
- GitHub authentication is delegated to `gh`; token values are never printed.
- Local artifact paths are marked non-portable.
- External artifact URLs must be intentionally shareable and durable.
- User-controlled Markdown and API text are rendered as data, not executed.
- Filesystem reads remain inside validated repository paths.
- The control room does not strengthen existing sandboxing or security and must
  not claim that it does.

## 15. Delivery sequence

After this written design is reviewed, a detailed implementation plan will split
the work into independently reviewable, test-driven commits:

1. schemas and validation;
2. entry-point documentation and templates;
3. 14-day machine-readable roadmap and renderer;
4. handoff and artifact workflows;
5. code-graph generation and freshness checks;
6. local current-state and board snapshots;
7. GitHub read-only export;
8. GitHub provisioning dry-run and reconciliation;
9. explicitly approved remote provisioning; and
10. full verification and documentation review.

Remote GitHub creation happens only after local artifacts validate and the
dry-run is reviewed. Application behavior for the separate Phase 1 trust plan
is not modified as part of constructing this coordination layer.

## 16. Non-goals

This work does not:

- implement the 14-day product roadmap;
- fix Phase 1 application defects;
- start the experiment kernel, DeepEval integration, governed training, pack
  redesign, VLM, VLA, rebranding, or launch work;
- replace GitHub with Plane, Linear, or Jira;
- store experiment evidence in project-management files;
- claim complete semantic understanding from the code graph; or
- silently apply the optional handover patch.

## 17. Acceptance criteria

The Project Control Room is ready when:

1. a new harness can find authoritative context from root `AGENTS.md` in one
   hop;
2. all repository coordination records validate fail-closed;
3. the approved 14-day roadmap has stable IDs and no orphan dependencies;
4. Days 1–2 contain confirmed detailed trust tasks and later days are marked for
   revalidation;
5. handoffs record scope, verification, evidence, risks, and exact next action;
6. code-graph outputs are deterministic and freshness is based on source inputs;
7. local snapshots are generated and never masquerade as live GitHub state;
8. GitHub provisioning is dry-run-first, idempotent, non-destructive, and
   reconciles partial runs;
9. the GitHub project contains the agreed fields, views, and linked issues;
10. Python and JavaScript verification passes or failures are reported exactly;
11. no application code is changed as part of the planning/design gate; and
12. the user explicitly approves the written spec before implementation planning
    begins.
