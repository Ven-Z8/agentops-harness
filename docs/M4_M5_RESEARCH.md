# AgentOps Harness — M4/M5 Research Kickoff: Authoring & Running the Codebase-Migration Capability Pack

> Audience: owner of `agentops-harness`. Purpose: a high-signal starting point for **M4** (author a codebase-migration capability pack) and **M5** (run it end-to-end, governed and shown in the Cockpit). Synthesized from per-subsystem assessments + three migration-readiness gap reports.

---

## 1. Executive summary

M1–M3 and the Cockpit are done, and the result is a genuinely solid spine: a 19-node LangGraph (`app/core/graph.py`) sequences plan → dispatch → govern → report; a deterministic, SDK-free **capability-pack loader** (`app/core/packs/loader.py`) folds a `{manifest, skills, tools, hooks}` bundle into the inner OpenHands agent's system suffix, tool allowlist, and callbacks; a deterministic **repo graph** (`app/core/repo_graph/`) extracts files/symbols/routes/risks (Spring Boot 2→3 / javax→jakarta vocabulary already present); a deterministic **governance suite** (`app/agents/`) grades report-vs-evidence honestly; and a polished read-only **Cockpit** (`app/cockpit/`) renders runs with a genuinely-live inner-loop SSE stream. 265 tests pass in ~45s.

**Thesis for M4/M5:** the *mechanism* M4 plugs into is real and tested at the seam — `select_pack` → `OPENHANDS_PACK_PATH` → `load_pack` + `assemble_agent_inputs` → live `Agent` — so **M4 (authoring) is mechanically unblocked today.** The risk is concentrated in **reachability, enforcement reality, and calibration**, all of which bite M5 specifically: packs ride only the OpenHands worker, only via the CLI, only with an explicit `--pack` flag; the inner loop has **never run against the real OpenHands SDK in this tree**; the pack's headline guardrail (hooks that "block edits outside target paths") is **observe-only and cannot block**; pack identity is **never recorded** on `RunRecord` or shown in the Cockpit; and the completeness/risk heuristics were tuned for small PRs and degrade quietly on a large multi-file diff. M5's bar is "run the migration pack end-to-end, governed and shown in the Cockpit" — the three things M5 most needs to *prove* (which pack governed, that it governed in-loop, that the migration actually finished) are exactly the current blind spots. This document is the map to closing them.

---

## 2. System map

| Subsystem | State | One-liner | M4/M5 relevance |
|---|---|---|---|
| Orchestration graph (`app/core/graph.py`, `state.py`) | partial | Linear-with-one-retry LangGraph; pack/dispatch hooks exist but only via OpenHands worker + CLI | **The spine.** `select_pack` (graph.py:331) is unguarded; pack only on openhands branch; `max_attempts=1` default never retries |
| Inner-loop workers (`app/core/workers/openhands_*`, CLI workers) | partial | Well-structured inner loop wiring 9 OpenHands components + pack bridge; tested only vs a **fake SDK** | **Runs the migration.** Real SDK never imported here (**blocker**); hooks are observers; `forbidden_paths`/`permission_tier` are prompt-only and unwired |
| Capability packs (M3) (`app/core/packs/loader.py`, `selector.py`) | **solid** | SDK-free loader folds skills→suffix, tools→allowlist, hooks→callbacks; fail-closed; 16 tests | **M4 builds directly on this.** No provenance to RunRecord; `tools_requested` lies; auto-select stubbed |
| Repo graph + impact (M2) (`app/core/repo_graph/`) | partial | Deterministic scanner + changed-subgraph; shallow per-file localization | Migration vocabulary present, but **no transitive impact**, **wrong Java route paths**, Python-only post-edit re-parse |
| Outer guards / governance (`app/agents/`) | partial | Deterministic post-hoc guards (evidence/risk/permission/product); honest epistemics | Calibrated for small PRs; **completeness grading unreliable on big diffs**; no pack-aware acceptance checks |
| Workspace / sandbox (`app/core/workspace/`) | partial | Timeout-hardened DockerWorkspace; strong extract-permitted path | **Strong sandbox is NOT the path OpenHands uses** (bind-mount + post-hoc revert); can't apply deletes/renames |
| Persistence / artifacts (`app/core/storage.py`, `run_artifacts.py`) | partial | JSONL/SQLite store + rich 17-file run folder + bundle.zip | **No pack provenance in bundle/record**; zero retention/GC; SQLite no WAL/busy_timeout |
| CLI / API / schemas / prompts (`app/cli.py`, `api.py`, `schemas/`, `prompts/`) | partial | Clean typed entrypoints; pack pipeline wired end-to-end via `edit` | Pack reachable **only via `agentops edit`**; API/MCP/WorkloadManifest can't run a pack; no scope contract |
| Intent graph / CEO layer (`app/agents/product_reviewer.py`, `schemas/goal_model.py`) | partial | `goals.yaml` → ProductGoalModel → 4-lens reviewer; cited, honest | **Advisory only — gates nothing**; LLM path ungrounded; success matching is single-token bag-of-words |
| Test suite / quality | partial | Broad, fast unit/contract suite; governance well-covered | **No e2e openhands+pack test; real SDK never imported; no with/without-pack eval** |

---

## 3. The capability-pack contract (deep dive) — what M4 builds on

A pack is a directory `packs/<name>/` with the shape `{ manifest.yaml, skills/*.md, hooks.py(optional) }`. The shipped template is `packs/example/` and the schema is `app/schemas/pack.py`.

### 3.1 Manifest (`app/schemas/pack.py::PackManifest`)

```yaml
name: codebase-migration        # required free string; also becomes the hooks module name
                                #   agentops_pack_<name>_hooks (loader.py:115) and the discover-by-name key
domain: codebase-migration      # required; LABEL ONLY — does NOT drive selection (loader.py:80 header text only)
version: 0.1.0                  # defaults to "0.1.0"; never validated
description: >-                 # folded into the system suffix
  ...
skills:                         # markdown filenames under skills/; each MUST exist or load fails
  - migration_overview.md
  - javax_to_jakarta.md
tools:                          # subset of the 6 built-ins; empty => use all defaults
  - terminal
  - file_editor
  - grep
  - glob
hooks: []                       # callable names exported by hooks.py; each MUST exist + be callable
```

An empty `tools:`/`hooks:`/`skills:` key parses to `None` and is coerced to `[]` (`PackManifest._none_to_empty`, pack.py).

### 3.2 What is ENFORCED at load (fail-closed)

- **Tool allowlist (enforced twice).** `ALLOWED_TOOL_NAMES = {terminal, file_editor, task_tracker, grep, glob, task_tool_set}` (`loader.py:26`) — no browser, no network. Checked in `_enforce_tool_allowlist` (`loader.py:64`) **and** `resolve_tool_names` (`loader.py:96`), which **raises** (does not silently drop) if a listed tool is not in the runner's fixed 6-entry `available_tools` map (`openhands_runner.py:242`). Good diagnostics for authors.
- **Skill files must exist** — each `skills/<file>` is read or load raises `PackError`.
- **Hooks must exist and be callable** — `load_hook_callables` (`loader.py:107`) imports `hooks.py` via importlib and pulls each manifest-named attribute, verifying `callable()` (`loader.py:124`).
- **Manifest must validate** against `PackManifest`.

A load failure becomes a clean **exit code 6 / `termination_reason="pack_error"`** in the runner (`openhands_runner.py:183`) — a misconfigured pack fails the run, it does not crash or run unequipped.

### 3.3 How a pack reaches the agent (the seam, end-to-end)

1. `app/cli.py:164` — `agentops edit --pack <path|name>` (openhands worker only) → `run_harness(pack=...)` (`graph.py:898`) → `state["pack"]`.
2. In `run_external_worker_node`, **only** the `worker_type == "openhands"` branch calls `select_pack(...)` (`graph.py:331`). `selector.select_pack` returns `discover_pack(explicit, ...)` when `--pack` is set, else `None` (auto-select is a deliberate stub, `selector.py:24-28`).
3. `discover_pack` (`loader.py:38`) resolves to a directory; graph passes `pack_path=str(pack_dir)` to `OpenHandsWorker.run`, which sets **`OPENHANDS_PACK_PATH`** on the subprocess env (`openhands_worker.py:202`).
4. The runner reads it (`openhands_runner.py:74`), calls `load_pack`, then `assemble_agent_inputs(pack, base_system_suffix=HARNESS_SYSTEM_SUFFIX, default_tools=...)` (`openhands_runner.py:250`) returning `(system_suffix, tool_names, hook_callables)`:
   - **skills → system suffix** — concatenated under `# Capability pack: <name> (<domain>)` then `## Skill — <name>`, appended after the harness base suffix; injected via `AgentContext(system_message_suffix=...)`.
   - **tools → allowlist** — the `Agent` is built only from `tool_names`.
   - **hooks → callbacks** — `Conversation(callbacks=[event_recorder, *pack_hooks])` (`openhands_runner.py:277`).

This whole path is SDK-free and unit-tested (`tests/test_capability_pack.py`, 16 tests; the env-passing seam and `assemble_agent_inputs` are both covered) — so **M4 can author and validate a pack with no OpenHands install.**

### 3.4 What M4 MUST know going in (authoring constraints, not bugs)

- **Hooks are observers, not interceptors.** A Conversation callback fires *after* an event; it cannot veto a tool call. "Block edits outside `src/`" is **un-authorable as a hook today** — a hook can log a violation but not prevent the edit. Hard path enforcement lives only in the post-hoc outer loop (`enforce_permissions_node`, `graph.py:395`).
- **The hook signature is implicit and unvalidated.** `load_hook_callables` checks only `callable()`; a wrong-arity hook passes load and blows up deep in the loop as a generic run error. Match `_OpenHandsEventRecorder.__call__` (single positional event arg). **There is no example `hooks.py`** — the migration pack's first hook is the first real exercise of this path.
- **Tools can only be a SUBSET of 6 built-ins.** A migration-specific codemod/AST tool cannot be registered; drive migration commands through the generic `terminal` tool and document the exact commands in a skill.
- **No enforced path-scoping field.** `PackManifest` has no `target_paths`/`forbidden_paths`/`scope`/`acceptance` field. Scope can only be expressed as prose in a skill; enforcement consults only the hardcoded global denylist in `app/core/security.py` (`.env`, `.pem`/`.key`, `auth`/`security`/`payment` folders), which is migration-blind and not pack-configurable.
- **No machine-checkable "definition of done."** No outer guard consumes the pack; correctness criteria can only be expressed as agent-runnable verification commands inside a skill (so the inner loop runs them and `EvidenceGuard`'s validation-execution check can see them) and as `success_when` tokens in `agentops.goals.yaml`.
- **Skills are flat-filename-only** (no traversal guard, subfolders untested) — keep skills as flat `*.md` referenced by bare filename.

---

## 4. Gaps that block or threaten M4/M5 (merged, de-duplicated, prioritized)

| # | Gap | Sev | Subsystem(s) | Suggested action |
|---|---|---|---|---|
| 1 | **Inner loop has never run against the real OpenHands SDK** — `import openhands` not installed; all 33 inner-loop tests use a hand-built fake SDK 1.28 surface. Any kwarg drift surfaces first at the live M5 run. | **blocker** | inner workers | `uv sync --extra openhands`; add an `importorskip`-gated smoke test that imports the real SDK so CI (with the extra) catches drift; run ONE real run before M5. |
| 2 | **No golden migration run exists** — zero persisted artifacts in the tree; Cockpit has only rendered fixtures. First assembled `pack→inner loop→events→governance→bundle` render is the demo itself. | **blocker** | persistence, cockpit, tests | Capture ONE real (or fake-SDK-backed e2e) governed migration's `.agentops/runs/<id>/` as a committed golden bundle; verify it renders in every tab + downloads. Demo safety net. |
| 3 | **ProductReviewer LLM path never sees the diff** — with a provider configured (the real M5 case), `review()` passes only `changed_files`+`diff_summary`+`goal_model`; `diff_body` is consumed *only* by the deterministic fallback. "Did the migration finish?" is graded from file *names*. Cockpit shows green on a half-migrated repo. | **blocker** | guards / CEO | Thread `diff_body`/per-file hunks into `build_product_reviewer_prompt`; OR run the deterministic check alongside the LLM path and take the weaker verdict. Test that the LLM prompt contains diff content. (`product_reviewer.py:74`) |
| 4 | **Cockpit cannot SHOW which pack governed a run** — no `pack` field on `RunRecord` (`schemas/run.py`), `WorkerLoopSummary`, or `WorkerScorecard`; pack name survives only as free text in `summary.notes`, which `web/app.js` never renders. The linchpin M5 claim is unrenderable. | **high** | persistence, cockpit, CLI | Add `pack {name, domain, version, resolved skills/tools/hooks}` to `WorkerLoopSummary` and lift onto `RunRecord` (~`graph.py:975`); render as a chip row in `tabWorker`; copy pack manifest into `bundle.zip`. Do this *before* authoring the pack so there's a render target. |
| 5 | **Product-Reviewer success-signal fidelity** — `_signal_met` (`product_reviewer.py:31`) marks a `success_when` MET if ANY single ≥5-char token appears anywhere in the haystack; no negation, no file identity, no added-vs-deleted. "all imports migrated from requests→httpx" flips MET the instant `httpx` appears once; lingering `requests` is invisible. Self-labeled low-confidence but `overall_verdict` treats `completeness=pass` as `aligned`. | **high** | guards / CEO | Give `success_when` a stronger check (per-file presence / removed-symbol assertions / count thresholds), or run agent-runnable verification commands the EvidenceGuard reads. This is the single most-watched M5 signal. |
| 6 | **Diff body tracked-only AND truncated to 20KB** — `collect_diff_body(max_chars=20000)` (`git_utils.py:107`) runs plain `git diff` (untracked new files excluded entirely), so deterministic completeness grading is effectively random past the first ~20KB and under-credits new modules. No truncation breadcrumb. | **high** | guards, persistence | Raise/stream the cap for migration runs; include untracked file contents; emit a `diff_truncated` breadcrumb into the record. |
| 7 | **RiskGuard can't see blast radius beyond 7 files & ignores Java deps** — `min(file_count*4, 25)` saturates at 7 files (`risk_guard.py:18`); blocks only at `critical` (≥80). Dependency signal matches only `pyproject.toml/uv.lock/requirements.txt` (`risk_guard.py:29`) — **not `pom.xml`/`build.gradle`**, so a Spring Boot 2→3 `pom.xml` bump never fires +20. A 700-file migration never blocks on size. | **high** | guards | Scale the volume term (or add a high-blast-radius band); extend dependency matcher to `pom.xml`/`build.gradle(.kts)`. |
| 8 | **Java/Spring route extraction wrong 3 ways + Python-only post-edit re-parse** — class-level `@RequestMapping` emitted as bogus `ANY /base`; base path not prepended to method routes; all routes attributed to `classes[0]`; `impact.py:186` skips non-`.py` changed files. EvidenceGuard then false-flags *correct* route claims on the migration's most likely target. | **high** | repo graph | Prepend class base path, skip standalone class-level `@RequestMapping`, attribute to enclosing class, extend post-edit re-parse to Java — before running a Spring migration. |
| 9 | **No transitive impact** — import edges resolve to opaque name nodes, never back to file nodes; no reverse traversal. Changed-subgraph reports only the edited file's own defs/imports/risks; consumers of an edited shared module never surface. Cockpit under-reports blast radius; targeted tests run too narrow → false-green. | **high** | repo graph | Resolve import edges to real file nodes; add a reverse-dependency walk; widen `recommended_validation` to impacted consumers. |
| 10 | **Convergence/retry is test-only; `max_attempts=1` default; 300s hard-kill; re-edits dirty tree** — converged purely on `test_results.passed`; product/risk/evidence gate nothing. API/MCP can't raise attempts. Retry re-dispatches full task on partial prior edits (`allow_dirty` forced true) with no rollback. `max_iterations` unbounded; timeout hard-kills mid-migration leaving a half-applied diff. | **high** | graph, inner workers | Set migration-sized timeout + `OPENHANDS_MAX_ITERATIONS`; rollback-to-clean (or snapshot) between attempts; make `max_attempts>1` reachable from API/MCP; document partial-diff-on-timeout contract. |
| 11 | **Strong sandbox is NOT the migration worker's path; can't apply deletes/renames** — `graph.py:329` routes `--sandbox`+openhands to a bind-mounting DockerWorkspace, bypassing `extract_permitted`. Even the strong path skips deletions and copies only the rename destination → host keeps both old+new = non-compiling tree. Multi-file/nested/rename/delete shapes have zero test coverage. | **high** | workspace | Route OpenHands through copy-in+extract_permitted OR formally accept bind-mount+post-revert as "governed"; harden `extract_permitted`/`enforce_permissions` for deletes+rename-source removal; add multi-file/rename/delete tests. |
| 12 | **Hooks observe-only + `forbidden_paths`/`permission_tier` dead-wired** — pack hooks can't veto; `forbidden_paths`/`permission_tier` fold into prompt text only and `graph.py:336` never passes them. M4's "block edits outside target paths" is unimplementable as specified. | **high** (M4 deliverable) | inner workers, CLI | Implement via SDK confirmation/security-analyzer seam OR a pre-edit deny surface; wire forbidden_paths→prompt→enforcement + a target-paths scope contract — OR explicitly scope the M5 narrative to "outer loop reverts after the fact." |
| 13 | **Pack reachable only via `agentops edit`** — `run` CLI, `CreateRunRequest` (api.py), `agentops_run` (mcp_server.py), and `WorkloadManifest` accept no `pack`/`worker_type`. M5 "shown in Cockpit" can't be *launched* from the API/Cockpit. | **high** | CLI/API | Add `pack`/`worker_type`/`max_attempts` to `CreateRunRequest`, `agentops_run`, and `WorkloadManifest` (with `extra='forbid'`); decide if the demo is CLI-launch + browser-watch or needs an in-Cockpit dispatch console. |
| 14 | **No e2e openhands+pack test; pack→runner join untested together** — every `run_harness` integration test uses a scripted shell worker; the pack-injection link is proven only in two disjoint unit halves. | **high** | tests | Add a graph-level test: `worker_type=openhands` + tmp pack against the fake SDK, asserting the pack's suffix/tools/hooks reach the agent and governance artifacts are produced. |
| 15 | **No retention / GC / rotation** — no prune/vacuum anywhere; every run accretes a full repo_graph, binary diff, worker logs, and an `openhands_state/` dir (tens of MB/run). JSONL `list` re-parses the whole file every Cockpit poll. | **high** (iteration) | persistence | Add `max_runs`/TTL prune + SQLite vacuum; bound/seek the JSONL list path. Authoring M4 = dozens of throwaway runs. |
| 16 | **No pack provenance in the bundle; diff capture silent-fail** — `export_artifact_bundle` never includes the pack; `_write_diff_patch` silently writes nothing on empty/non-git diff with no marker. A migration bundle can lack its own diff and can't name its pack. | **medium** | persistence | Copy resolved pack into the bundle; write a diff.patch marker when empty/non-git; add timestamps/durations to `trace.jsonl`. |
| 17 | **`tools_requested` lies when a pack narrows tools** — hardcoded to the full 6 (`openhands_runner.py:109`) while the agent is built from the narrowed set. Governance auditing the allowlist reads the wrong tools. | **medium** | packs | Thread resolved `tool_names` into `WorkerLoopSummary`. |
| 18 | **`select_pack` unguarded in the graph** — a typo'd `--pack` raises `PackError` out of `graph.invoke()` (`graph.py:331`) → crash, no run record, no verdict. The most common authoring mistake produces no artifacts. | **medium** | graph, packs | Wrap `select_pack` in try/except → "blocked" `ExternalEditResult` so a bad pack name yields a blocked RunRecord. |
| 19 | **Governance "live" loop is a post-hoc replay sold as live** — `run_harness` is synchronous; `trace.jsonl`+RunRecord written only at the end; SSE replays at 0.12s/event while a pulsing green "Governance loop" dot implies real-time. Reads as fake to a sharp reviewer. | **medium** | cockpit, graph | Stream outer-node lifecycle to a live trace file as nodes execute, OR honestly relabel "replay" and stop pulsing post-completion. |
| 20 | **No outer-loop pack-aware acceptance checks** — packs feed only the inner worker; guards read `changed_files`/`test_results`/`goal_model`, never the pack. M4 can shape what the worker DOES but not what governance VERIFIES. | **medium** | guards, packs | Add a `checks`/`assertions` block to the manifest the outer loop runs (contract extension); interim: agent-runnable verification commands in skills. |
| 21 | **No `agentops pack` CLI (validate/list/show); auto-select stubbed** — authoring feedback requires a full harness pass. | **medium** | CLI | Add `agentops pack validate <dir>`/`show` calling the existing loader functions — cheap, big ergonomics win for M4. |
| 22 | **Inner-loop live tail re-reads whole event log every 100ms; no size cap** — `_tail_live` (`mount.py:135`) `read_text`s the whole file per tick; O(n) at migration scale; no byte guard. Lag in the exact "watch it think" moment. | **medium** | cockpit | Track a byte offset and seek/read only the appended tail; add a max-events/bytes guard; test with a multi-thousand-line log. |
| 23 | **SQLite default settings (no WAL / busy_timeout)** — long worker writing live artifacts + Cockpit reading + final save can hit "database is locked" mid-demo. | **medium** | persistence | Enable WAL + `busy_timeout`; stop re-ensuring schema on every call. |
| 24 | **Worker-loop unhappy path renders deceptively "present" + empty** — `worker.present = bool(events or summary)` but the runner pre-touches the event file, so the panel looks present-but-empty with no error affordance; SSE `done`/`error` bound to the same handler. | **medium** | cockpit | Distinguish "produced events" from "file exists"; show an explicit no-events state; bind error to a visible banner. |
| 25 | **M2 `is_touched` decorator limitation** — `is_touched` compares the diff range to `PythonRoute.line` (the `def` line, not the `@decorator` above it; documented `impact.py:166`). A path-rename migration that edits only the decorator isn't flagged as touched. Also: APIRouter `prefix=` ignored → EvidenceGuard false-positives on prefixed routes. | **low** | repo graph | Compare against the decorator line; honor `APIRouter(prefix=...)`. Often masked because a path rename surfaces as an *added* route instead. |
| 26 | **`_EdgeIndex.outgoing` is O(N×E)** — 1500 changed files / 40k edges ≈ 4.4s, superlinear. | **low** | repo graph | Pre-group edges by `(source, type)` into a dict once. |
| 27 | **No coverage measurement; Goal.id uniqueness unvalidated; `suggested_next` permanent stub** | **low** | tests, CEO | Add pytest-cov; add a Pydantic `model_validator` for unique goal ids. |

---

## 5. Open research questions — decisions the owner must make

### For M4 (authoring the pack)
1. **Hooks: enforce or observe?** Will the migration pack's guardrails be observe-only (telemetry, accepted against today's callback seam) or must they actually BLOCK out-of-scope edits? Observe-only = pure authoring. Blocking = net-new engineering (SDK confirmation/security-analyzer seam, or wiring `forbidden_paths` into the outer enforce path). *This single decision determines whether M4 is authoring or contract work.*
2. **Path scoping: new manifest field or global denylist?** Add `target_paths`/`forbidden_paths` to `PackManifest` and thread to enforcement, or rely solely on `app/core/security.py` + post-hoc revert?
3. **Definition of done: how machine-checkable?** (a) agent-runnable verification commands embedded in skills (authorable now, EvidenceGuard sees them), (b) precise `success_when` tokens in `goals.yaml` (authorable now, weak matcher), (c) a new pack-level `checks` block the outer loop enforces (contract extension)?
4. **Custom tooling?** Is driving migration commands through the generic `terminal` tool acceptable, or does the migration need a first-class codemod/AST tool (requires extending `available_tools` + `ALLOWED_TOOL_NAMES`)?
5. **Authoring ergonomics:** is an `agentops pack validate/show` CLI in M4 scope?

### For M5 (the demo)
6. **Which repo + which migration?** (see §6). Confirm target **language** — the Java/Spring impact bugs (gaps #7–9) make accuracy materially worse for Java, the exact domain the pack targets.
7. **Real provider or keyless/mock?** The completeness signal is broken differently on each path (gap #3 LLM path vs gap #6 deterministic 20KB truncation). Pick one and fix that path before grading a real migration.
8. **Live or golden run?** Demo on a live first-ever SDK run (risk: first integration on stage) or a pre-captured golden bundle replayed through the Cockpit (de-risks, weakens the "live" claim)?
9. **Launch path:** CLI-launch + browser-watch, or invest in an in-Cockpit dispatch console (POST + async `run_harness`, net-new)?
10. **Should governance verdicts gate convergence?** Today only test-pass + critical-risk block; a migration that drifts out of scope or under-completes still "converges." Does M5 need a real gate wired into the convergence router?
11. **Timeout/iteration budget:** what is a realistic wall-clock for the intended migration? 300s + unbounded iterations will hard-kill mid-migration or run away.

---

## 6. Recommended migration-target criteria

A good first migration to demo is one that maximizes governance signal while minimizing the current blind spots:

- **Python, not Java (for the first demo).** The repo graph's transitive-impact gap (#9) affects both, but the Java route-path bugs (#8) and Java-skipped post-edit re-parse (#8) will produce *false* EvidenceGuard flags on a correct Spring migration. Java is the eventual headline domain, but fix gaps #7–9 before demoing it. A FastAPI/Python target exercises the well-tested path today. *(If Java is mandatory for the portfolio story, gaps #7–9 become must-fix M4 prerequisites.)*
- **A migration with a crisp, token-checkable success criterion** — e.g. "replace all `import requests` with `httpx`", "javax→jakarta imports", "Pydantic v1→v2". Choose one where `success_when` can be expressed precisely enough to survive the weak matcher (gap #5), ideally backed by an agent-runnable grep/count command in a skill.
- **Bounded but multi-file blast radius** — large enough to be a real demo (the governance thesis is "big diffs treated as serious"), small enough that (a) the diff stays under or near the 20KB completeness window (gap #6), (b) it finishes inside a sane timeout (gap #10), and (c) it's mostly *modifications and additions*, not deletes/renames (the sandbox can't apply those, gap #11).
- **Has a real test suite** that turns green only when the migration is actually complete — so convergence (test-only today) tracks true done-ness and `EvidenceGuard`'s test-claim check has teeth.
- **A clean git tree to start** (dirty-repo blocking protects diff attribution) and **git-tracked files** (untracked new files don't enter `diff_body`, gap #6).
- **Demonstrates the pack earning its keep** — pick a migration where the *bare* worker would plausibly miss the domain rules the pack's skills encode, so the with/without-pack eval (gap #14, an M4 deliverable) shows a real delta.

---

## 7. Proposed M4 → M5 plan (sequenced, building on the merged code)

**Phase 0 — De-risk the foundation (do first; unblocks everything else)**
1. `uv sync --extra openhands`; run ONE real OpenHands run end-to-end on a tiny repo. Add an `importorskip`-gated SDK smoke test so CI (with the extra) catches API drift vs the fakes. *(gap #1)*
2. Wrap `select_pack` (`graph.py:331`) in try/except → blocked RunRecord. *(gap #18)*
3. Add `pack {name, domain, version, resolved skills/tools/hooks}` to `WorkerLoopSummary` and lift onto `RunRecord`; fix `tools_requested` to the resolved set. *(gaps #4, #17)*

**Phase 1 — M4: author the migration pack**
4. Decide hooks observe-vs-block and the path-scoping approach (Open Questions 1–2). If observe-only: ship an example `hooks.py` documenting the callback signature; put hard scope in a skill (prose) + rely on the global denylist.
5. Write `packs/codebase-migration/`: `manifest.yaml` (`domain: codebase-migration`, `tools: [terminal, file_editor, grep, glob]`), flat skills (`migration_overview.md`, the domain playbook, an agent-runnable verification command), optional observe-only hooks.
6. Author `agentops.goals.yaml` for the target migration with precise `success_when` signals; select via `--goal`.
7. Add `agentops pack validate/show` CLI calling existing loader functions. *(gap #21)*
8. Add the graph-level openhands+pack e2e test (fake SDK) + the with/without-pack eval. *(gap #14)*

**Phase 2 — M5 enablers: make a big governed migration legible**
9. Fix the completeness signal on whichever path M5 uses: thread `diff_body` into the ProductReviewer LLM prompt (#3) and/or strengthen `_signal_met` (#5); raise/stream the diff cap + include untracked files + add a truncation breadcrumb (#6).
10. Fix RiskGuard volume scaling + add `pom.xml`/`build.gradle` to the dependency matcher (#7).
11. Set a migration-sized timeout + `OPENHANDS_MAX_ITERATIONS`; make `max_attempts>1` reachable; document partial-diff-on-timeout (#10).
12. (If Java target) Fix Java route paths + extend post-edit re-parse to Java (#8); (any target) add transitive-impact reverse walk (#9).
13. Decide and harden the sandbox story: route OpenHands through copy-in+extract_permitted OR accept bind-mount+post-revert and harden deletes/renames (#11).
14. Add `pack`/`worker_type`/`max_attempts` to `CreateRunRequest`/`agentops_run`/`WorkloadManifest` so M5 is launchable from the API/Cockpit if needed (#13).

**Phase 3 — M5: run, govern, show, capture**
15. Add minimal retention/GC + SQLite WAL/busy_timeout before the iteration loop fills disk / locks mid-demo (#15, #23).
16. Make the Cockpit show the pack (chip row in `tabWorker`, run-list summary) and copy the pack into `bundle.zip` (#4, #16). Either make the outer governance loop genuinely live or relabel it "replay" (#19). Fix the no-events affordance + SSE error banner (#24) and the live-tail seek-read (#22).
17. **Run the migration pack end-to-end** on the chosen target. Capture `.agentops/runs/<id>/` as a committed **golden bundle**; verify every Cockpit tab renders and `bundle.zip` downloads cleanly. This is both the M5 deliverable and the demo safety net (#2).

---

**Key files to start from:** `app/core/packs/loader.py` (pack contract), `app/schemas/pack.py` (manifest schema), `packs/example/` (template), `app/core/workers/openhands_runner.py:250-277` (the injection seam), `app/core/graph.py:327-348` (where packs are selected/dispatched), `app/agents/product_reviewer.py:31,74` (the completeness signal to fix), `app/agents/risk_guard.py:18,29` (blast-radius/dep caps), `app/core/repo_graph/java_parser.py` + `impact.py:186` (route/transitive accuracy), `app/cockpit/mount.py` + `web/app.js` (rendering + pack chip), `app/schemas/run.py` + `app/core/run_artifacts.py` (provenance + bundle).
