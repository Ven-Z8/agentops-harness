# AgentOps Harness — First Principles

*A from-scratch reconstruction of the whole system: what it is, where every prompt
lives, and exactly how the outer layer hands a task to the inner loop. Written to be
read before planning the COBOL migration demo.*

---

## 1. The irreducible idea

Strip everything away and the project rests on five primitives:

1. **A model answers once. An agent loops.** A coding agent reads → edits → runs →
   folds feedback back in → repeats (50–200×) until the task converges. **A harness
   is everything around that loop that makes it finish.**
2. **Harnesses nest.** `You → AgentOps (outer) → Worker (inner) → Model`. AgentOps owns
   the two outer layers; the model is rented inside exactly one box.
3. **Each layer is grounded by a deterministic graph, not by the model.**
   The worker is grounded by the **repo graph** (structure of the code); the CEO is
   grounded by the **intent graph** (`agentops.goals.yaml`). *That grounding — not the
   model — is the moat.*
4. **The outer layer never runs the edit loop.** It **equips** the loop (hands it a
   contract + tools + domain pack) and **governs** what comes back. It does not edit
   files and does not iterate a model.
5. **Dispatch is a contract down; feedback is ground truth up.** The outer layer sends
   the inner loop a task + plan + constraints + pack. It reads back the **git diff,
   test results, and an event trajectory** — never the model's self-report.

Everything below is mechanism in service of those five.

---

## 2. The two-LLM, two-prompt model (the part people miss)

There are **two completely separate LLM call-sites**, and conflating them is the #1
source of confusion:

| | **Outer LLM** (the governor's brain) | **Inner LLM** (the worker's engine) |
|---|---|---|
| Who | `app/core/llm.py` → `LLMClient` | The worker's own model (OpenHands `LLM`, or the `claude`/`codex` CLI's model) |
| Default | `mock` (no paid call) | Required only when you actually run a worker |
| Calls | 1 call per agent, **single-shot** | The **50–200× iterative loop** |
| Job | Plan, review, write report, product-review | Read, edit, run, retry until the task is done |
| Swappable? | provider config (`openrouter`/`openai`) | **worker-type** (`claude`/`codex`/`opencode`/`openhands`/ any CLI) |

The outer LLM **thinks about** the work. The inner LLM **does** the work. AgentOps owns
the first and *governs* the second without being it.

---

## 3. Every prompt in the system

There are exactly **four outer LLM prompts** and **one worker-packet prompt**. Most of
the pipeline has **no LLM at all** — that is the point.

### 3a. Outer LLM prompts (single-shot, each with a deterministic fallback)

| # | Prompt builder | Agent | Produces | Fallback if model misbehaves |
|---|---|---|---|---|
| 1 | `app/prompts/planner.py` → `build_planner_prompt` | `Planner` | `ImplementationPlan` (the plan-as-contract) | deterministic local plan (`provider_fallback:create_plan`) |
| 2 | `app/prompts/reviewer.py` → `build_reviewer_prompt` | `Reviewer` | code-review of the diff | deterministic review |
| 3 | `app/prompts/pr_writer.py` → `build_pr_writer_prompt` | `PRWriter` | the final report markdown | deterministic report (regenerated if Quality Guard rejects it) |
| 4 | `app/prompts/product_reviewer.py` → `build_product_reviewer_prompt` | `ProductReviewer` | CEO-altitude verdict, cited to `agentops.goals.yaml` | `not_evaluated` (never bluffs) |

Key properties, visible in `graph.py`:
- Every one is wrapped `try: <llm> except: <deterministic>` — a bad/absent provider
  **degrades, never crashes** (e.g. `create_plan_node`, `review_diff_node`,
  `write_report_node`, `build_product_review_node`).
- The Product Reviewer prompt has hard grounding rules baked in: *"Every finding must
  cite a source_of_truth field… Never invent goals… Use `not_evaluated` when intent is
  absent."* The diff is capped at 16k chars so a big migration can't blow the window.

### 3b. The deterministic spine (NO LLM — this is the moat)

These run with zero model calls, every time, in mock mode:

`RepoScanner` · `RepoGraphBuilder` · `ExperienceMemory` (recall) · pre-dispatch gate ·
`enforce_permissions` (revert-on-deny) · `ChangedSubgraphBuilder` · `TestRunner` ·
`RiskGuard` · `PermissionGate` · `ReportQualityGuard` · `EvidenceGuard` ·
`VerificationStack` · `ConflictAuditor` · benchmark.

If you remember one thing: **~14 of the ~20 pipeline stages are deterministic.** The LLM
is a tenant, not the foundation.

### 3c. The worker-packet prompt — the bridge to the inner loop

`app/prompts/workers.py` → `build_worker_prompt` is **not** an LLM call. It is a
deterministic **template** that renders the contract the inner loop receives. Its
sections (verbatim structure):

- **Task** — what to do
- **Plan as Contract** — the planner's steps, files-to-edit, acceptance criteria, risk
  notes ("Follow this plan unless repo inspection proves it wrong")
- **Repo Context** — language/framework/test-framework/entrypoints (from the repo graph)
- **Likely Impacted Files** — from the plan
- **Constraints / Forbidden Actions / Forbidden Paths** — minimal diff, no secrets, no
  test-weakening, sensitive paths off-limits
- **Permission Tier · Verification Obligations · Definition of Done**
- **Reporting Rules** — *"Do not claim tests passed unless you actually ran them… Do not
  claim routes were added unless they exist in the diff."*

This packet is the literal handshake: the outer layer's plan, constraints, and intent,
serialized into text the inner loop consumes.

---

## 4. How the outer layer gives the task to the inner layer

This happens in **one node** of the graph: `run_external_worker_node` (`graph.py`).
Everything before it (scan → recall → plan → prepare workspace → pre-dispatch gate) is
preparation; everything after (collect diff → enforce → test → converge → review …) is
governance. The dispatch itself has **three shapes** depending on `--worker-type`:

### Path A — CLI workers (`claude` / `codex` / `opencode`)
```
build_worker_prompt(task, plan, repo_profile, ...)   # the packet, as text
   → claude --bare -p "<packet>" --allowedTools Read,Edit,Write,Bash,Glob,Grep
   → subprocess runs IN repo_path; the CLI's own model is the inner loop
```
The packet goes in as a command-line prompt; the worker's model loops on its own.

### Path B — OpenHands worker (the always-on, real-SDK inner loop)
This is the richest seam and the one that matters for the migration. In
`OpenHandsWorker.run` (`app/core/workers/openhands_worker.py`):

```
prompt = build_worker_prompt(task, plan, repo_profile, tests_to_run, ...)
subprocess: python -m app.core.workers.openhands_runner <repo_path>
   • TASK         → passed on STDIN
   • PACK         → env OPENHANDS_PACK_PATH      (selected by the outer loop)
   • EVENTS LOG   → env OPENHANDS_EVENTS_PATH    (the trajectory the outer reads back)
   • PERSISTENCE  → env OPENHANDS_PERSISTENCE_DIR
   • WORKSPACE    → env OPENHANDS_WORKSPACE      (local | docker)
```

Then inside `openhands_runner.py` (`build_agent` + `main`), the inner agent is assembled
from three injected things — **this is the outer→inner contract made concrete**:

```
assemble_agent_inputs(pack, base_system_suffix=HARNESS_SYSTEM_SUFFIX, default_tools=…)
   ├─ system_message_suffix = HARNESS_SYSTEM_SUFFIX  +  pack.skills/*.md
   ├─ tools                 = pack.tools  (restricted to a terminal/file-only allowlist)
   └─ callbacks             = [event_recorder, *pack.hooks]
Agent(llm=<inner LLM>, tools=…, condenser=LLMSummarizingCondenser, agent_context=…)
conversation.set_security_analyzer(LLMSecurityAnalyzer())   # pre-action risk gate
conversation.send_message(TASK)     # ← the task enters the inner loop here
conversation.run()                  # ← the real prompt→model→tool→observe loop
```

So the outer loop "programs" the inner loop through **three knobs**:
1. **The task** (stdin) — what to do.
2. **The system suffix** (`HARNESS_SYSTEM_SUFFIX` + pack skills) — *how* to behave +
   domain competence. `HARNESS_SYSTEM_SUFFIX` is the constant constraints bridge: "make
   the smallest controlled change… do not edit secrets/auth/payment… add a focused test,
   then run it… if blocked, summarize."
3. **The pack** (`OPENHANDS_PACK_PATH`) — per-repo/task competence: skills extend the
   system suffix, tools restrict the allowlist, hooks become loop callbacks. **Same
   harness, swap the pack, new competence.**

### Path C — arbitrary `--worker-command`
`ExternalWorkerRunner` substitutes `{task}` / `{repo_path}` into any command template.
This is how **Omniagent / Pi / any future agent become workers** — if it has a CLI or
API, it slots in here with no harness change.

---

## 5. The feedback path — why the outer layer can't be lied to

After dispatch, the worker has edited files. The outer layer **ignores what the worker
says it did** and reconstructs the truth from disk:

```
collect_diff      → git diff / changed files (ground truth #1)
enforce_permissions → git-revert any sensitive-path edit the worker made (enforcement!)
run_tests         → actually run the validation commands (ground truth #2)
check_convergence → passed? → proceed.  failed (retriable)? → loop back to worker
build_changed_subgraph → re-parse the POST-edit code (catches worker-added routes)
review / risk / permission / report / quality / evidence / product / verify / conflict
```

Three feedback channels flow **up** from the inner loop:
- **The git diff** — what actually changed (the only thing the worker can't fake).
- **`openhands_events.jsonl`** — the `prompt→tool→observation` trajectory, streamed via
  the `event_recorder` callback. The Cockpit renders this; the harness can read it.
- **The worker summary JSON** (`OPENHANDS_WORKER_SUMMARY_JSON=…` on stdout) — status,
  duration, tools requested, termination reason.

The **Evidence Guard** then flags any report claim the diff/tests/graph don't support,
and degrades the run instead of shipping a bluff. *No claim survives without grounding.*

---

## 6. The whole flow on one screen

```
                        OUTER LOOP (AgentOps — governs, never edits)
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ scan_repo ─ recall ─ PLAN* ─ prepare_ws ─ pre_dispatch_gate              │
  │                                   │ (block if plan hits secrets/auth)    │
  │                                   ▼                                       │
  │                          run_external_worker ───────────┐                │
  │                                   │  task(stdin)         │  CONTRACT DOWN │
  │                                   │  HARNESS_SYSTEM_SUFFIX                │
  │                                   │  pack(env) skills/tools/hooks         │
  │                                   ▼                      ▼                │
  │         ╔═══════════ INNER LOOP (worker — OpenHands SDK / CLI) ════════╗  │
  │         ║  send_message(task) → run():  prompt→model→tool→observe ×N   ║  │
  │         ║  edits files · runs tests inline · streams events.jsonl      ║  │
  │         ╚════════════════════════════════════════════════════════════╝  │
  │                                   │  diff · events · summary  GROUND UP   │
  │                                   ▼                                       │
  │  collect_diff ─ enforce(revert) ─ run_tests ─ converge? ──retry──┐       │
  │                                   │ proceed                       │       │
  │                                   ▼                               └──────►│
  │  changed_subgraph ─ REVIEW* ─ risk ─ permission ─ REPORT* ─ quality ─    │
  │  evidence ─ PRODUCT_REVIEW* ─ verification ─ conflict ─► RunRecord+bundle │
  └─────────────────────────────────────────────────────────────────────────┘
   * = the four outer LLM prompts.  Everything else is deterministic.
```

---

## 7. What this means for the COBOL migration demo

Mapping the five primitives onto the migration, this is exactly where each piece plugs in
— and what's missing:

| Need | Where it lives in the architecture | Status |
|---|---|---|
| COBOL→target **playbook** | pack `skills/*.md` → injected into the inner agent's system suffix | **author in M4** |
| **Migration-specific guardrails** (e.g. block edits outside target paths) | pack `hooks.py` → conversation callbacks | **author in M4** |
| **Differential oracle** (old ≡ new on same input) | a **sealed** test the *outer* layer owns and re-runs in `run_tests` / Verification Stack — NOT a test the worker can edit | **design + build (the core new piece)** |
| Intent: "migrate with zero behavioral drift" | `agentops.goals.yaml` → drives the Product Reviewer | **author in M4** |
| Worker A vs Worker B side-by-side | two `worker_type`s judged against the same sealed oracle | **enabled by Path A/C; demo in M5** |
| Turn Pi / Omniagent into workers | `--worker-command` template (Path C) or a thin worker class | **adapter, if they expose a CLI/API** |

**The one genuinely new architectural piece is the sealed differential oracle.** Today
the worker runs tests inline (component #5) *and* the outer layer re-runs them
(`run_tests_node`). For migration trust, the golden inputs + expected outputs and the
comparison must be **owned by the outer layer and unwritable by the worker** — otherwise
"make tests pass" becomes "weaken the oracle." That sealing is the feature no inner-loop
competitor can offer, because they *are* the worker.

**The instinct to fix:** "bigger system prompts" is the wrong lever — the system suffix
should stay lean and constant (`HARNESS_SYSTEM_SUFFIX`); domain knowledge belongs in
**pack skills**, assembled per task. Richer *packs*, not bigger *prompts*.

---

## 8. One-paragraph version

AgentOps is an outer harness that **plans** a task with a deterministic repo graph (one
optional LLM call), hands the inner loop a **contract** — task on stdin + a constant
constraints suffix + a per-task capability pack (skills→system suffix, tools→allowlist,
hooks→callbacks) — lets a swappable worker (OpenHands SDK or any CLI) run the real
50–200× edit loop, and then **reconstructs the truth from git diff + tests + event log**,
runs a deterministic gauntlet of guards, and emits a cited evidence bundle. Four
single-shot LLM prompts think; everything else is deterministic. The worker is rented and
replaceable; the grounding and the governance are the product.
