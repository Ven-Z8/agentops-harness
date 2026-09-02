# AgentOps 14-Day Roadmap

> Generated from `coordination/roadmap/14-day-plan.yaml`; do not edit manually.

## AO-14D: AgentOps 14-Day Research Control Plane

- Kind: roadmap
- Day: None
- Phase: None
- Parent: None
- Status: planned
- Maturity: confirmed
- Priority: P0
- Risk: critical
- Blocker: release-blocking

## Outcome
A reviewable 14-day control-plane roadmap keeps approved scope and evidence authoritative in Git.
## Scope
- Maintain stable roadmap identifiers
- Render approved roadmap scope deterministically.
## Non-goals
- Change AgentOps runtime behavior
- Treat GitHub issue text as the roadmap authority.
## Dependencies
- None
## Acceptance criteria
- All approved roadmap records validate
- Generated Markdown identifies its authoritative YAML source.
## Required evidence
- Validated roadmap YAML
- Byte-stable rendered Markdown.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive roadmap evidence cannot be reported as a completed release plan.
## Compatibility
Additive coordination metadata does not alter persisted AgentOps runtime records or CLI behavior.
## Verification commands
- uv run pytest tests/unit/test_project_control_schema.py tests/unit/test_project_control_rendering.py -q
- uv run ruff check app/project_control
## Risks
- False-success reporting could hide missing roadmap evidence
- Existing coordination consumers require additive migration only.
## Rollback
Revert the coordination roadmap slice while preserving committed truthful evidence and prior generated artifacts.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-P1: Trust and Benchmark Integrity

- Kind: phase
- Day: None
- Phase: None
- Parent: AO-14D
- Status: planned
- Maturity: confirmed
- Priority: P0
- Risk: critical
- Blocker: release-blocking

## Outcome
Phase 1 establishes evidence and boundary gates before later roadmap work is considered.
## Scope
- Coordinate confirmed Days 1 and 2
- Require truthful evidence before Phase 2 work proceeds.
## Non-goals
- Implement deferred Phase 2 work
- Change runtime behavior through coordination records.
## Dependencies
- None
## Acceptance criteria
- Day 1 and Day 2 records are confirmed and reviewable
- Phase gate evidence is explicit.
## Required evidence
- Validated child task records
- Phase gate verification results.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive Phase 1 work prevents opening its downstream gate and cannot imply completion.
## Compatibility
Additive phase metadata preserves existing configuration and CLI contracts.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_langgraph_workflow.py tests/test_workload.py tests/test_permission_gate.py tests/test_sandbox_worker_type_guard.py -q
- uv run ruff check app/core app/agents app/schemas
## Risks
- False-success phase status could authorize unsafe downstream work
- Existing evidence references must remain readable.
## Rollback
Revert the Phase 1 coordination slice while retaining truthful child evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-P2: Experiment Kernel and DeepEval

- Kind: phase
- Day: None
- Phase: None
- Parent: AO-14D
- Status: planned
- Maturity: needs-revalidation
- Priority: P1
- Risk: high
- Blocker: deferred until Phase 1 gate

## Outcome
Revalidate the experiment-kernel scope after Phase 1 evidence before committing implementation claims.
## Scope
- Assess Days 3 through 5 against the then-current repository
- Define only confirmed kernel work.
## Non-goals
- Assert historical defects remain present
- Start work before the Phase 1 gate.
## Dependencies
- AO-P1
## Acceptance criteria
- Revalidation records current evidence
- Any implemented scope is approved from that evidence.
## Required evidence
- Phase 1 gate result
- Current repository and test evidence.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive revalidation prevents Phase 2 promotion and cannot imply kernel readiness.
## Compatibility
Any future persisted-schema or provider migration is deferred until revalidation confirms it.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_experiment_identity.py tests/test_deepeval_adapter.py tests/test_benchmark.py -q
- uv run ruff check app/core/benchmark.py app/schemas/benchmark.py
## Risks
- Stale assumptions can cause false success
- Future schema changes require backward-compatible readers.
## Rollback
Revert only confirmed Phase 2 coordination updates while preserving recorded revalidation evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-P3: Governed Training

- Kind: phase
- Day: None
- Phase: None
- Parent: AO-14D
- Status: planned
- Maturity: needs-revalidation
- Priority: P1
- Risk: high
- Blocker: deferred until Phase 2 gate

## Outcome
Revalidate governed-training objectives after the Phase 2 gate before any training claim is made.
## Scope
- Assess Days 6 through 8 using current contracts
- Define evidence and budget gates from current findings.
## Non-goals
- Claim a training provider is ready
- Spend training budget before approval.
## Dependencies
- AO-P2
## Acceptance criteria
- Current provider and budget evidence is documented
- Promotion criteria are explicit.
## Required evidence
- Phase 2 gate result
- Current training-contract evidence.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive training evidence prevents promotion and cannot imply governed readiness.
## Compatibility
Future provider or persisted-run changes require explicit migration after revalidation.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_training_contracts.py tests/test_governed_training.py tests/test_training_promotion.py -q
- uv run ruff check app/core app/schemas
## Risks
- Unvalidated training claims create false success
- Provider changes can break existing records.
## Rollback
Revert only Phase 3 coordination updates while preserving truthful training evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-P4: Swappable Loops and Skills

- Kind: phase
- Day: None
- Phase: None
- Parent: AO-14D
- Status: planned
- Maturity: needs-revalidation
- Priority: P2
- Risk: medium
- Blocker: deferred until kernel contracts

## Outcome
Revalidate swappable-loop and capability-pack objectives against confirmed kernel contracts.
## Scope
- Assess Days 9 and 10 after kernel contracts are known
- Record only validated capability seams.
## Non-goals
- Assume existing loop defects
- Redesign packs before contract review.
## Dependencies
- AO-P2
## Acceptance criteria
- Compatibility seams are evidenced
- Revalidation distinguishes proposed from verified behavior.
## Required evidence
- Kernel contract evidence
- Focused compatibility checks.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive seam validation cannot imply swappability or completion.
## Compatibility
Future pack migrations remain additive until contract revalidation confirms their shape.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_capability_pack.py tests/test_strategy_pack.py -q
- uv run ruff check app/core/packs app/schemas/pack.py
## Risks
- False-success capability claims can hide incompatible packs
- Contract migration can break consumers.
## Rollback
Revert only confirmed Phase 4 coordination updates and keep revalidation evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-P5: VLM and VLA Reference Paths

- Kind: phase
- Day: None
- Phase: None
- Parent: AO-14D
- Status: planned
- Maturity: needs-revalidation
- Priority: P2
- Risk: high
- Blocker: deferred until kernel contracts

## Outcome
Revalidate VLM and VLA reference-path objectives against confirmed kernel interfaces.
## Scope
- Assess Days 11 and 12 with current provider and simulator evidence
- Define reproducibility gates only after review.
## Non-goals
- Claim provider support without evidence
- Bind to a simulator before interface validation.
## Dependencies
- AO-P2
## Acceptance criteria
- Provider and simulator seams have current evidence
- Reference workflow claims remain reproducible.
## Required evidence
- Kernel contract evidence
- Current provider or simulator verification.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive reference-path evidence cannot imply supported VLM or VLA completion.
## Compatibility
Future provider configuration changes require explicit migration and compatibility review.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_vlm_reference_workflow.py tests/test_vla_provider_seam.py -q
- uv run ruff check app/core app/schemas
## Risks
- Stale provider assumptions create false success
- Interface changes can break existing configurations.
## Rollback
Revert only confirmed Phase 5 coordination updates while retaining recorded evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-P6: Open-Source Release

- Kind: phase
- Day: None
- Phase: None
- Parent: AO-14D
- Status: planned
- Maturity: needs-revalidation
- Priority: P0
- Risk: critical
- Blocker: deferred until preceding gates

## Outcome
Revalidate release readiness only after the preceding phase gates have current evidence.
## Scope
- Assess Days 13 and 14 against current release inputs
- Publish only verified limitations and results.
## Non-goals
- Release on inferred evidence
- Claim readiness before preceding gates pass.
## Dependencies
- AO-P3
- AO-P4
- AO-P5
## Acceptance criteria
- All release gates have current evidence
- Published limitations match verified results.
## Required evidence
- Preceding phase gates
- Reproducible release verification.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive release gates prevent publication and cannot imply v0.1 completion.
## Compatibility
Release metadata changes require documented package and documentation migration effects.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_release_hygiene.py tests/test_v0_1_reproduction.py -q
- npm test
## Risks
- False-success release claims mislead users
- Package changes can break installation compatibility.
## Rollback
Revert only release coordination updates while retaining truthful evidence and limitations.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D01: Truthful terminal states and strict boundaries

- Kind: outcome
- Day: 1
- Phase: AO-P1
- Parent: AO-P1
- Status: planned
- Maturity: confirmed
- Priority: P0
- Risk: critical
- Blocker: phase

## Outcome
Day 1 produces confirmed, fail-closed status and boundary work with reproducible evidence.
## Scope
- Coordinate terminal-state and boundary task slices
- Require each slice to retain failed and inconclusive evidence.
## Non-goals
- Begin deferred provider work
- Infer success from partial evidence.
## Dependencies
- AO-P1
## Acceptance criteria
- All Day 1 child records name focused tests
- Day 1 completion requires evidence from each child slice.
## Required evidence
- Validated Day 1 task records
- Focused test and status evidence.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive Day 1 tasks prevent the day outcome from being completed.
## Compatibility
Day 1 changes require explicit persisted-schema, configuration, or CLI migration review.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_langgraph_workflow.py tests/test_boundary_kind_validation.py tests/test_workload.py -q
- uv run ruff check app/core app/agents app/schemas
## Risks
- False-success terminal states can promote failed work
- Existing records may need compatible readers.
## Rollback
Revert only a Day 1 task slice while preserving truthful evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D01-01: Capture reproducible baseline and isolate ambient configuration

- Kind: task
- Day: 1
- Phase: AO-P1
- Parent: AO-D01
- Status: planned
- Maturity: confirmed
- Priority: P0
- Risk: critical
- Blocker: phase

## Outcome
Reproducible configuration does not change with ambient parent dotenv state.
## Scope
- Capture a baseline
- Isolate provider configuration from parent dotenv input.
## Non-goals
- Change provider selection policy
- Add a new provider.
## Dependencies
- None
## Acceptance criteria
- Parent dotenv input cannot change provider configuration
- Baseline evidence records effective configuration.
## Required evidence
- Focused red-green test output
- Reproducible baseline record.
## Likely files
- app/core/config.py
- app/core/workers/openhands_config.py
- provider/config tests
## First failing test
tests/test_openhands_config.py::test_parent_dotenv_does_not_change_provider_config
## Terminal semantics
Failed, blocked, or inconclusive baseline isolation prevents completion; configuration success is never inferred.
## Compatibility
Configuration migration preserves explicit user settings and documents changed ambient-variable behavior.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_openhands_config.py::test_parent_dotenv_does_not_change_provider_config -q
- uv run pytest tests/test_openhands_config.py -q
- uv run ruff check app/core/config.py app/core/workers/openhands_config.py
## Risks
- Ambient configuration can create false-success baselines
- Existing configuration users need backward-compatible migration.
## Rollback
Revert only the configuration-isolation slice while retaining baseline and failing evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D01-02: Separate execution, evaluation, and promotion status

- Kind: task
- Day: 1
- Phase: AO-P1
- Parent: AO-D01
- Status: planned
- Maturity: confirmed
- Priority: P0
- Risk: critical
- Blocker: phase

## Outcome
A failed required execution or evaluation can never produce a completed or promoted run.
## Scope
- Define independent execution
- evaluation
- and promotion terminal states.
- Derive overall status from required stages without inferring success.
## Non-goals
- Add DeepEval integration.
- Redesign the experiment kernel.
## Dependencies
- AO-D01-01
## Acceptance criteria
- Required test failure produces a non-successful run terminal state.
- Promotion is impossible when execution or evaluation is failed or inconclusive.
## Required evidence
- Focused red-green test output.
- Persisted run record showing independent statuses.
## Likely files
- app/schemas/run.py
- app/core/graph.py
- app/core/storage.py
- app/core/benchmark.py
- app/core/memory.py
## First failing test
tests/test_langgraph_workflow.py::test_required_test_failure_cannot_complete_or_converge
## Terminal semantics
Failed, blocked, or inconclusive required execution or evaluation prevents completion and promotion.
## Compatibility
Additive persisted-run schema change with an explicit reader migration for existing records.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_langgraph_workflow.py::test_required_test_failure_cannot_complete_or_converge -q
- uv run pytest tests/test_langgraph_workflow.py tests/test_benchmark.py tests/test_memory.py -q
- uv run ruff check .
## Risks
- Existing completed records may lack stage statuses and must not be reinterpreted silently.
## Rollback
Revert the schema/derivation slice while retaining migrated records and recorded failing evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D01-03: Reject unknown provider, worker, workspace, policy, and pack kinds

- Kind: task
- Day: 1
- Phase: AO-P1
- Parent: AO-D01
- Status: planned
- Maturity: confirmed
- Priority: P0
- Risk: critical
- Blocker: phase

## Outcome
Unknown execution-boundary kinds fail before any worker starts.
## Scope
- Validate provider
- worker
- workspace
- policy
- and pack kinds
- Stop execution before unknown values reach a runtime seam.
## Non-goals
- Add new kinds
- Silently coerce unknown configuration.
## Dependencies
- None
## Acceptance criteria
- Unknown boundary kinds fail before execution
- Error evidence identifies the rejected boundary.
## Required evidence
- Focused red-green test output
- Rejected configuration record.
## Likely files
- app/core/config.py
- app/core/llm.py
- app/cli.py
- app/core/graph.py
- app/core/workspace/
- app/core/packs/
## First failing test
tests/test_boundary_kind_validation.py::test_unknown_boundary_kinds_fail_before_execution
## Terminal semantics
Failed, blocked, or inconclusive boundary validation prevents completion and no accepted kind is inferred.
## Compatibility
Configuration and CLI migrations retain explicit supported kinds and reject removed kinds with actionable errors.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_boundary_kind_validation.py::test_unknown_boundary_kinds_fail_before_execution -q
- uv run pytest tests/test_boundary_kind_validation.py -q
- uv run ruff check app/core app/cli.py
## Risks
- Permissive fallback can create false-success execution
- Existing configurations may require backward-compatible migration notices.
## Rollback
Revert only the boundary-validation slice while preserving rejected-input evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D01-04: Fail closed on missing evidence and failed required commands

- Kind: task
- Day: 1
- Phase: AO-P1
- Parent: AO-D01
- Status: planned
- Maturity: confirmed
- Priority: P0
- Risk: critical
- Blocker: phase

## Outcome
Missing evidence and failed required commands cannot pass a workload.
## Scope
- Require evidence for workload completion
- Propagate required-command failure into terminal status.
## Non-goals
- Relax evidence policy
- Add unrelated workflow features.
## Dependencies
- AO-D01-02
## Acceptance criteria
- Failed required command cannot pass
- Missing evidence remains missing or inconclusive.
## Required evidence
- Focused red-green test output
- Persisted failed-command evidence.
## Likely files
- app/core/workload.py
- app/agents/evidence_guard.py
- app/core/graph.py
- app/schemas/evidence.py
- app/schemas/workload.py
## First failing test
tests/test_workload.py::test_failed_required_command_cannot_pass
## Terminal semantics
Failed, blocked, or inconclusive evidence prevents completion; no workload pass is inferred.
## Compatibility
Persisted evidence and workload schema changes require explicit reader migration.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_workload.py::test_failed_required_command_cannot_pass -q
- uv run pytest tests/test_workload.py -q
- uv run ruff check app/core/workload.py app/agents/evidence_guard.py
## Risks
- Missing evidence can create false success
- Existing workload records require backward-compatible interpretation.
## Rollback
Revert only the evidence-guard slice while preserving recorded failed evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D02: Permission, sandbox, grounding, CI, and release integrity

- Kind: outcome
- Day: 2
- Phase: AO-P1
- Parent: AO-P1
- Status: planned
- Maturity: confirmed
- Priority: P0
- Risk: critical
- Blocker: phase

## Outcome
Day 2 establishes confirmed permission, security, grounding, CI, and release-integrity gates.
## Scope
- Coordinate the five confirmed Day 2 task slices
- Require explicit evidence for each gate.
## Non-goals
- Claim sandbox enforcement without proof
- Release before integrity checks are complete.
## Dependencies
- AO-D01
## Acceptance criteria
- Each Day 2 child has a focused test target
- Day completion is based on required evidence.
## Required evidence
- Validated Day 2 task records
- Focused test and release-gate evidence.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive Day 2 tasks prevent the day outcome from being completed.
## Compatibility
Day 2 changes require explicit permission, sandbox, CI, or documentation migration review.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_permission_gate.py tests/test_sandbox_worker_type_guard.py tests/test_worker_grounding.py tests/test_release_hygiene.py -q
- npm test
## Risks
- False-success security claims can expose unsafe work
- Existing configurations and docs require compatible transitions.
## Rollback
Revert only a Day 2 task slice while preserving truthful gate evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D02-01: Normalize allow, ask, and deny semantics

- Kind: task
- Day: 2
- Phase: AO-P1
- Parent: AO-D02
- Status: planned
- Maturity: confirmed
- Priority: P0
- Risk: critical
- Blocker: phase

## Outcome
Ask requires approval and cannot be represented as completed work.
## Scope
- Normalize allow
- ask
- and deny decisions
- Preserve approval state through the workflow.
## Non-goals
- Bypass approval
- Change unrelated worker policy.
## Dependencies
- AO-D01-04
## Acceptance criteria
- Ask requires approval and is not completed
- Deny remains a non-successful terminal decision.
## Required evidence
- Focused red-green test output
- Persisted approval-state record.
## Likely files
- app/schemas/permission.py
- app/agents/permission_gate.py
- app/core/security.py
- app/core/graph.py
## First failing test
tests/test_permission_gate.py::test_ask_requires_approval_and_is_not_completed
## Terminal semantics
Failed, blocked, and inconclusive permission outcomes prevent completion; approval is never inferred.
## Compatibility
Permission-schema and CLI behavior changes preserve explicit legacy decisions with documented migration.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_permission_gate.py::test_ask_requires_approval_and_is_not_completed -q
- uv run pytest tests/test_permission_gate.py -q
- uv run ruff check app/schemas/permission.py app/agents/permission_gate.py app/core/security.py
## Risks
- Ask interpreted as allow creates false success
- Existing permission records need backward-compatible handling.
## Rollback
Revert only the permission-semantic slice while preserving approval and denial evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D02-02: Make sandbox and security claims match enforcement

- Kind: task
- Day: 2
- Phase: AO-P1
- Parent: AO-D02
- Status: planned
- Maturity: confirmed
- Priority: P0
- Risk: critical
- Blocker: phase

## Outcome
Isolation claims are limited to boundaries that are actually enforced.
## Scope
- Verify sandbox-worker enforcement
- Align security claims and documentation with verified boundaries.
## Non-goals
- Claim full isolation without enforcement
- Replace the workspace architecture.
## Dependencies
- AO-D02-01
## Acceptance criteria
- Full isolation claim requires an enforced container boundary
- Unsupported claims are rejected or corrected.
## Required evidence
- Focused red-green test output
- Enforcement configuration evidence.
## Likely files
- app/cli.py
- app/core/workspace/local.py
- app/core/workspace/docker.py
- app/core/security.py
- README.md
- sandbox tests
## First failing test
tests/test_sandbox_worker_type_guard.py::test_full_isolation_claim_requires_enforced_container_boundary
## Terminal semantics
Failed, blocked, or inconclusive sandbox enforcement prevents a full-isolation claim and completion is not inferred.
## Compatibility
CLI, configuration, and documentation migration preserves accurate legacy boundary descriptions.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_sandbox_worker_type_guard.py::test_full_isolation_claim_requires_enforced_container_boundary -q
- uv run pytest tests/test_sandbox_worker_type_guard.py -q
- uv run ruff check app/cli.py app/core/workspace app/core/security.py
- npm test -- --runInBand
## Risks
- Overstated sandbox claims create false success
- Existing configurations and docs may require backward-compatible migration.
## Rollback
Revert only the sandbox-claim slice while preserving enforcement and failing evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D02-03: Provide equal grounding packets to equivalent workers

- Kind: task
- Day: 2
- Phase: AO-P1
- Parent: AO-D02
- Status: planned
- Maturity: confirmed
- Priority: P0
- Risk: critical
- Blocker: phase

## Outcome
Equivalent workers receive equal grounding inputs before work begins.
## Scope
- Define a common grounding packet
- Verify equivalent worker handoffs receive the same packet.
## Non-goals
- Make workers identical
- Change worker-model selection.
## Dependencies
- AO-D02-01
## Acceptance criteria
- Equivalent workers receive equal grounding packet
- Missing grounding remains explicit rather than inferred.
## Required evidence
- Focused red-green test output
- Captured equivalent-worker grounding records.
## Likely files
- app/core/graph.py
- app/core/handoff.py
- app/prompts/workers.py
- app/core/workers/
## First failing test
tests/test_worker_grounding.py::test_equivalent_workers_receive_equal_grounding_packet
## Terminal semantics
Failed, blocked, or inconclusive grounding prevents completion and no equivalent context is inferred.
## Compatibility
Worker configuration and handoff migrations preserve existing explicit grounding inputs.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_worker_grounding.py::test_equivalent_workers_receive_equal_grounding_packet -q
- uv run pytest tests/test_worker_grounding.py -q
- uv run ruff check app/core/graph.py app/core/handoff.py app/prompts/workers.py app/core/workers
## Risks
- Unequal context can create false-success comparisons
- Existing handoffs need compatible grounding migration.
## Rollback
Revert only the grounding-packet slice while preserving captured comparison evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D02-04: Run Python and JavaScript suites in CI

- Kind: task
- Day: 2
- Phase: AO-P1
- Parent: AO-D02
- Status: planned
- Maturity: confirmed
- Priority: P0
- Risk: critical
- Blocker: phase

## Outcome
CI runs both repository Python and JavaScript verification suites.
## Scope
- Define CI checks for Python and JavaScript
- Report individual suite failure without inferring release success.
## Non-goals
- Rewrite application tests
- Hide flaky or missing suite results.
## Dependencies
- AO-D02-02
## Acceptance criteria
- CI runs Python and JavaScript suites
- Any required suite failure is non-successful.
## Required evidence
- Focused red-green test output
- CI workflow and suite output.
## Likely files
- .github/workflows/ci.yml
- web/package.json
- Python and web test suites
## First failing test
tests/test_release_hygiene.py::test_ci_runs_python_and_javascript_suites
## Terminal semantics
Failed, blocked, or inconclusive required suites prevent CI completion and release success is never inferred.
## Compatibility
CI and package-script migrations preserve documented local commands and failure reporting.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_release_hygiene.py::test_ci_runs_python_and_javascript_suites -q
- uv run pytest tests/test_release_hygiene.py -q
- uv run ruff check .
- npm test
## Risks
- A missing suite produces false-success CI
- Existing package scripts and CI consumers need compatible migration.
## Rollback
Revert only the CI-suite slice while preserving truthful workflow and failing-suite evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D02-05: Add OSI license and reconcile documentation and package drift

- Kind: task
- Day: 2
- Phase: AO-P1
- Parent: AO-D02
- Status: planned
- Maturity: confirmed
- Priority: P0
- Risk: critical
- Blocker: phase

## Outcome
Release metadata has an OSI license and a consistent documented package identity.
## Scope
- Add or validate OSI license metadata
- Reconcile package and documentation identity.
## Non-goals
- Publish a release
- Change product scope.
## Dependencies
- AO-D02-04
## Acceptance criteria
- Release metadata has OSI license and consistent identity
- Documentation and package evidence agree.
## Required evidence
- Focused red-green test output
- License and metadata verification record.
## Likely files
- LICENSE
- SECURITY.md
- CONTRIBUTING.md
- pyproject.toml
- README.md
- package/release docs
## First failing test
tests/test_release_hygiene.py::test_release_metadata_has_osi_license_and_consistent_identity
## Terminal semantics
Failed, blocked, or inconclusive metadata prevents release completion and no package identity is inferred.
## Compatibility
Documentation and package metadata migration records user-facing identity changes explicitly.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_release_hygiene.py::test_release_metadata_has_osi_license_and_consistent_identity -q
- uv run pytest tests/test_release_hygiene.py -q
- uv run ruff check .
- npm test
## Risks
- Metadata drift creates false-success release claims
- Existing users need backward-compatible documentation and package migration.
## Rollback
Revert only the release-metadata slice while preserving validation evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D03: Define experiment identity and immutable run records

- Kind: outcome
- Day: 3
- Phase: AO-P2
- Parent: AO-P2
- Status: planned
- Maturity: needs-revalidation
- Priority: P1
- Risk: high
- Blocker: deferred until Phase 1 gate

## Outcome
Revalidate experiment identity and immutable-run objectives using current Phase 1 evidence.
## Scope
- Inspect current run-record contracts
- Propose confirmed identity work only after review.
## Non-goals
- Assert a run-record defect exists
- Mutate persisted schemas before revalidation.
## Dependencies
- AO-D02
## Acceptance criteria
- Current run identity evidence is captured
- Any schema work has an explicit migration plan.
## Required evidence
- Current run-record inspection
- Phase 1 gate evidence.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive revalidation prevents completed identity claims.
## Compatibility
Potential persisted-run migration remains deferred pending confirmed current evidence.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_experiment_identity.py -q
- uv run ruff check app/schemas/benchmark.py app/core/benchmark.py
## Risks
- Stale defect claims create false success
- Schema changes can break legacy readers.
## Rollback
Revert only confirmed Day 3 coordination updates and retain inspection evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D04: Add a DeepEval provider adapter without leaking provider schema

- Kind: outcome
- Day: 4
- Phase: AO-P2
- Parent: AO-P2
- Status: planned
- Maturity: needs-revalidation
- Priority: P1
- Risk: high
- Blocker: deferred until Phase 1 gate

## Outcome
Revalidate whether a provider-agnostic DeepEval adapter is currently warranted.
## Scope
- Inspect provider interfaces
- Define an adapter boundary only if current evidence supports it.
## Non-goals
- Assume DeepEval integration is missing
- Leak provider schema into shared contracts.
## Dependencies
- AO-D03
## Acceptance criteria
- Current provider boundaries are evidenced
- Any adapter proposal preserves provider isolation.
## Required evidence
- Current interface inspection
- Focused adapter-contract evidence if approved.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive adapter evidence prevents a supported-provider claim.
## Compatibility
Future provider configuration migration is explicit and deferred until revalidation.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_deepeval_adapter.py -q
- uv run ruff check app/core/benchmark.py app/schemas/benchmark.py
## Risks
- Provider leakage creates false success
- Existing configurations can be incompatible with new adapters.
## Rollback
Revert only confirmed Day 4 coordination updates while retaining interface evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D05: Run split-safe coding benchmark comparison and promotion

- Kind: outcome
- Day: 5
- Phase: AO-P2
- Parent: AO-P2
- Status: planned
- Maturity: needs-revalidation
- Priority: P1
- Risk: high
- Blocker: deferred until Phase 1 gate

## Outcome
Revalidate benchmark comparison and promotion criteria using current split and evidence contracts.
## Scope
- Inspect benchmark split controls
- Define promotion only from verified comparison evidence.
## Non-goals
- Assert a benchmark flaw exists
- Promote a model from incomplete evidence.
## Dependencies
- AO-D04
## Acceptance criteria
- Split handling is evidenced before comparison
- Promotion criteria reject incomplete evidence.
## Required evidence
- Current benchmark inspection
- Verified comparison output if work is approved.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive comparison evidence prevents promotion and completion.
## Compatibility
Future benchmark-record changes require explicit reader and CLI migration review.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_benchmark.py -q
- uv run ruff check app/core/benchmark.py app/schemas/benchmark.py
## Risks
- Split leakage creates false success
- Existing benchmark records may need compatible readers.
## Rollback
Revert only confirmed Day 5 coordination updates while preserving comparison evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D06: Define governed training provider and budget contracts

- Kind: outcome
- Day: 6
- Phase: AO-P3
- Parent: AO-P3
- Status: planned
- Maturity: needs-revalidation
- Priority: P1
- Risk: high
- Blocker: deferred until Phase 2 gate

## Outcome
Revalidate training-provider and budget contract objectives from current Phase 2 evidence.
## Scope
- Inspect provider and budget controls
- Define only evidenced governed-training contracts.
## Non-goals
- Assume training controls are absent
- Spend a training budget before approval.
## Dependencies
- AO-D05
## Acceptance criteria
- Provider and budget boundaries have current evidence
- Proposed controls identify approval gates.
## Required evidence
- Phase 2 gate result
- Current provider and budget inspection.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive contract evidence prevents governed-training completion.
## Compatibility
Future provider, CLI, and persisted-record migrations require explicit compatibility review.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_training_contracts.py -q
- uv run ruff check app/core app/schemas
## Risks
- Unvalidated controls create false success
- Provider changes can break existing configurations.
## Rollback
Revert only confirmed Day 6 coordination updates while preserving current evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D07: Execute one tiny reproducible governed training run

- Kind: outcome
- Day: 7
- Phase: AO-P3
- Parent: AO-P3
- Status: planned
- Maturity: needs-revalidation
- Priority: P1
- Risk: high
- Blocker: deferred until Phase 2 gate

## Outcome
Revalidate whether a small governed training run is safe and reproducible under confirmed contracts.
## Scope
- Assess current reproducibility controls
- Execute only an approved minimal run with recorded evidence.
## Non-goals
- Scale training
- Infer reproducibility from a partial run.
## Dependencies
- AO-D06
## Acceptance criteria
- Any run has declared budget and provider evidence
- Reproducibility result is explicit.
## Required evidence
- Approved run contract
- Captured run and verification output.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive run evidence prevents training completion and promotion.
## Compatibility
Future training-record migration preserves existing run evidence and configuration semantics.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_governed_training.py -q
- uv run ruff check app/core app/schemas
## Risks
- Partial runs can create false success
- Provider and record changes may break compatibility.
## Rollback
Revert only confirmed Day 7 coordination updates while retaining run evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D08: Compare training evidence and make a promotion decision

- Kind: outcome
- Day: 8
- Phase: AO-P3
- Parent: AO-P3
- Status: planned
- Maturity: needs-revalidation
- Priority: P1
- Risk: high
- Blocker: deferred until Phase 2 gate

## Outcome
Revalidate the training-evidence comparison and promotion decision from current governed-run results.
## Scope
- Assess available training evidence
- Record a promotion decision only from complete comparison evidence.
## Non-goals
- Promote from incomplete evidence
- Claim a prior comparison remains current.
## Dependencies
- AO-D07
## Acceptance criteria
- Comparison inputs are documented
- Promotion or non-promotion is evidence-backed.
## Required evidence
- Current training comparison
- Explicit decision record.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive comparison prevents promotion and cannot imply completion.
## Compatibility
Decision and persisted-run migrations remain explicit and additive.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_training_promotion.py -q
- uv run ruff check app/core app/schemas
## Risks
- Incomplete comparison creates false success
- Record-format changes can break existing readers.
## Rollback
Revert only confirmed Day 8 coordination updates while retaining decision evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D09: Validate and record a swappable inner-loop capability pack

- Kind: outcome
- Day: 9
- Phase: AO-P4
- Parent: AO-P4
- Status: planned
- Maturity: needs-revalidation
- Priority: P2
- Risk: medium
- Blocker: deferred until kernel contracts

## Outcome
Revalidate an inner-loop capability-pack seam against confirmed current kernel contracts.
## Scope
- Inspect inner-loop interfaces
- Validate one pack only if the seam is confirmed.
## Non-goals
- Assume a pack is compatible
- Redesign the full capability system.
## Dependencies
- AO-D08
## Acceptance criteria
- Current seam evidence is recorded
- Any validated pack reports its compatibility limits.
## Required evidence
- Kernel-contract evidence
- Focused pack validation output.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive validation prevents a swappable-pack completion claim.
## Compatibility
Future pack configuration migration is explicit and preserves supported contracts.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_capability_pack.py -q
- uv run ruff check app/core/packs app/schemas/pack.py
## Risks
- Assumed compatibility creates false success
- Pack contract changes can break consumers.
## Rollback
Revert only confirmed Day 9 coordination updates while retaining seam evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D10: Validate and record a swappable outer-loop strategy pack

- Kind: outcome
- Day: 10
- Phase: AO-P4
- Parent: AO-P4
- Status: planned
- Maturity: needs-revalidation
- Priority: P2
- Risk: medium
- Blocker: deferred until kernel contracts

## Outcome
Revalidate an outer-loop strategy-pack seam against confirmed current kernel contracts.
## Scope
- Inspect outer-loop interfaces
- Validate one strategy pack only when contract evidence supports it.
## Non-goals
- Claim universal strategy support
- Change unvalidated loop behavior.
## Dependencies
- AO-D09
## Acceptance criteria
- Current outer-loop seam is evidenced
- Validated strategy limits are recorded.
## Required evidence
- Kernel-contract evidence
- Focused strategy-pack verification.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive validation prevents a swappable-strategy completion claim.
## Compatibility
Strategy-pack migration remains explicit and additive for existing loop consumers.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_strategy_pack.py -q
- uv run ruff check app/core/packs app/schemas/pack.py
## Risks
- Unverified substitution creates false success
- Contract changes can break existing strategies.
## Rollback
Revert only confirmed Day 10 coordination updates while retaining validation evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D11: Complete one small reproducible VLM workflow

- Kind: outcome
- Day: 11
- Phase: AO-P5
- Parent: AO-P5
- Status: planned
- Maturity: needs-revalidation
- Priority: P2
- Risk: high
- Blocker: deferred until kernel contracts

## Outcome
Revalidate whether one small VLM workflow can be made reproducible with current interfaces.
## Scope
- Inspect VLM provider and workflow seams
- Execute only an approved small reproducibility check.
## Non-goals
- Claim broad VLM support
- Scale a workflow without verified evidence.
## Dependencies
- AO-D10
## Acceptance criteria
- Workflow inputs and output evidence are captured
- Reproducibility result is explicit.
## Required evidence
- Current VLM interface evidence
- Captured reproducibility verification.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive workflow evidence prevents a VLM completion claim.
## Compatibility
Future VLM configuration migration is documented and preserves existing provider settings.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_vlm_reference_workflow.py -q
- uv run ruff check app/core app/schemas
## Risks
- A one-off result creates false success
- Provider changes can break existing workflows.
## Rollback
Revert only confirmed Day 11 coordination updates while retaining workflow evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D12: Verify the VLA provider and simulator seam

- Kind: outcome
- Day: 12
- Phase: AO-P5
- Parent: AO-P5
- Status: planned
- Maturity: needs-revalidation
- Priority: P2
- Risk: high
- Blocker: deferred until kernel contracts

## Outcome
Revalidate the VLA provider and simulator seam using current interface evidence.
## Scope
- Inspect provider and simulator interfaces
- Verify only a confirmed seam.
## Non-goals
- Claim simulator compatibility without evidence
- Bind a provider to an unvalidated interface.
## Dependencies
- AO-D11
## Acceptance criteria
- Provider and simulator assumptions are tested
- Seam limitations are recorded.
## Required evidence
- Current interface inspection
- Focused seam verification output.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive seam evidence prevents VLA readiness and completion claims.
## Compatibility
Provider and simulator configuration migration remains explicit and backward compatible.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_vla_provider_seam.py -q
- uv run ruff check app/core app/schemas
## Risks
- Assumed seam compatibility creates false success
- Interface changes can break existing configurations.
## Rollback
Revert only confirmed Day 12 coordination updates while retaining verification evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D13: Close license, packaging, documentation, and release gates

- Kind: outcome
- Day: 13
- Phase: AO-P6
- Parent: AO-P6
- Status: planned
- Maturity: needs-revalidation
- Priority: P0
- Risk: critical
- Blocker: deferred until preceding gates

## Outcome
Revalidate release-gate inputs and close only the license, packaging, and documentation gaps proven by current evidence.
## Scope
- Inspect release inputs
- Record complete and incomplete gates separately.
## Non-goals
- Publish a release on inferred readiness
- Treat prior documentation as current proof.
## Dependencies
- AO-D12
## Acceptance criteria
- Each gate has current evidence
- Incomplete gates remain explicit.
## Required evidence
- Current license and package inspection
- Documentation and release-gate verification.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive gate evidence prevents release completion and publication.
## Compatibility
Package and documentation migration effects are documented before release changes.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_release_hygiene.py -q
- npm test
## Risks
- Incomplete gates create false-success release claims
- Metadata changes can break existing installation guidance.
## Rollback
Revert only confirmed Day 13 coordination updates while retaining gate evidence.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md

## AO-D14: Reproduce v0.1 end to end and publish honest limitations

- Kind: outcome
- Day: 14
- Phase: AO-P6
- Parent: AO-P6
- Status: planned
- Maturity: needs-revalidation
- Priority: P0
- Risk: critical
- Blocker: deferred until preceding gates

## Outcome
Revalidate v0.1 reproducibility and publish only limitations supported by current end-to-end evidence.
## Scope
- Attempt an approved end-to-end reproduction
- Publish verified results and explicit limitations.
## Non-goals
- Hide failed reproduction steps
- Claim release readiness from partial evidence.
## Dependencies
- AO-D13
## Acceptance criteria
- Reproduction result is captured
- Published limitations match the evidence.
## Required evidence
- End-to-end reproduction output
- Reviewed limitations record.
## Likely files
- None
## First failing test
None
## Terminal semantics
Failed, blocked, or inconclusive reproduction prevents release completion and cannot imply v0.1 success.
## Compatibility
Publication, package, and documentation changes identify explicit migration effects for users.
## Planned verification commands (not current evidence)
- uv run pytest tests/test_v0_1_reproduction.py -q
- npm test
## Risks
- Partial evidence creates false-success publication
- Release changes can break user installation expectations.
## Rollback
Revert only confirmed Day 14 coordination updates while retaining reproduction evidence and limitations.
## Source documents
- coordination/designs/2026-08-30-project-control-room-design.md
