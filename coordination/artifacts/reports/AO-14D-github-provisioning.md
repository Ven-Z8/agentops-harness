# AO-14D GitHub provisioning report

Status: **approved apply partial / completed fields preserved / reserved-name repair locally verified**.

## Current desired board schema after the reserved-name repair

The managed field formerly labeled `Type` is now labeled `Roadmap kind` because
GitHub rejects the bare name as reserved/already taken. Its single-select
options remain exactly `Roadmap`, `phase`, `outcome`, `task`, `decision`, and
`research`; every planned item value still comes directly from the roadmap
record's `kind`. Bare `Type` is treated as a GitHub-owned built-in and is never
created, updated, or populated by the provisioner. Earlier plan evidence below
that names `Type` remains historical evidence of the mutation set that failed.

## Historical successful authenticated dry-run

- Authenticated GitHub CLI account: `Ven-Z8`, with project scope confirmed. No
  token or other credential value is recorded.
- First live `github-provision --dry-run`: exit `0`.
- Second live dry-run capture: exit `0`; the captured plan is
  `/tmp/ao14d-github-plan.json`.
- Target: owner `Ven-Z8`; repository `Ven-Z8/agentops-harness`; project
  `AgentOps Research Control Plane — 14-Day v0.1`.
- The plan contains **395 create actions**: 1 project, 12 fields, 30 issues
  with 30 unique exact stable roadmap IDs, 30 items, 316 field-values, and 6
  views.
- It contains zero reuse, update, or delete actions.
- Fields: `Day`, `Dependency`, `Evidence`, `Handoff`, `Harness`, `Phase`,
  `Priority`, `Risk`, `Status`, `Target date`, `Type`, `Workstream`.
- Views: `Harness`, `Inbox`, `Kanban`, `Phase`, `Roadmap`, `Trust Blockers`.
- No mutation, `--apply`, or board export occurred while producing or recording
  this dry-run evidence.

## Historical dry-run gate failure

- Run timestamp (UTC): `2026-09-01T14:13:37Z`
- Source HEAD: `a15a9072d1cf4b5a4b4f265305003d41808609e0`
- Intended owner: `Ven-Z8`
- Intended repository: `Ven-Z8/agentops-harness`
- Intended project: `AgentOps Research Control Plane — 14-Day v0.1`
- Auth account: `Ven-Z8` (GitHub CLI reports the stored credential is invalid; no secret recorded)

### Commands and exact results

| Command | Exit | stdout | stderr |
| --- | ---: | --- | --- |
| `gh auth status` | 1 | *(empty)* | `github.com\n  X Failed to log in to github.com account Ven-Z8 (default)\n  - Active account: true\n  - The token in default is invalid.\n  - To re-authenticate, run: gh auth login -h github.com\n  - To forget about this account, run: gh auth logout -h github.com -u Ven-Z8` |
| `uv run python scripts/project_control.py validate` (with `UV_CACHE_DIR=/tmp/ao14d-uv-cache`) | 0 | `Control room valid.` | *(empty)* |
| `uv run python scripts/project_control.py github-provision --dry-run` (with `UV_CACHE_DIR=/tmp/ao14d-uv-cache`) | 3 | *(empty)* | `dependency unavailable: GitHub CLI is unavailable or unauthenticated` |

The first validation attempt without the temporary cache failed locally with a
permissions error opening `/Users/venkat/.cache/uv`; it was rerun successfully
with the task-scoped cache above.

## Historical expected plan contract (not produced before authentication was restored)

The deterministic local contract specifies 30 stable roadmap IDs (each must
appear exactly once), 12 fields, and six views. The 12 fields and types are:

`Status` single-select; `Priority` single-select; `Day` single-select;
`Phase` single-select; `Workstream` single-select; `Type` single-select;
`Risk` single-select; `Evidence` single-select; `Harness` text;
`Dependency` text; `Handoff` text; `Target date` date.

The six views are `Inbox`, `Kanban`, `Phase`, `Harness`, `Trust Blockers`, and
`Roadmap`. Seventeen roadmap records currently carry `needs-revalidation` in
the committed YAML and must retain that status. Exact create/reuse/update,
issue, item, field-value, and view action counts were **unavailable at that
time** because no authenticated discovery or plan was emitted.

## Historical safety checks before the successful dry-run

- No `--apply` command was run.
- No GraphQL mutation, issue/project create/edit/delete, remote write, or board
  export was run.
- No delete action can be claimed from the unavailable live plan; this gate is
  inconclusive rather than passed.
- No mutation calls were possible after the unauthenticated dry-run exited 3.

## Required explicit approval

The reviewed dry-run is ready for apply only after the user gives this exact
approval wording:

> I approve running `UV_CACHE_DIR=/tmp/ao14d-uv-cache uv run python scripts/project_control.py github-provision --apply --confirm` for the reviewed AO-14D plan targeting owner `Ven-Z8`, repository `Ven-Z8/agentops-harness`, and project `AgentOps Research Control Plane — 14-Day v0.1`, with no delete actions.

## Recheck attempt (2026-09-01T14:36:02Z UTC)

Authentication remains invalid. `gh auth status` exited `1` with the same
sanitized Ven-Z8 invalid-token message. Local validation exited `0` with
`Control room valid.` The fresh `github-provision --dry-run` (using
`UV_CACHE_DIR=/tmp/ao14d-uv-cache`) exited `3`, stdout empty, stderr
`dependency unavailable: GitHub CLI is unavailable or unauthenticated`.

No remote discovery or mutation was attempted; exact live action counts remain
unavailable. The gate remains partial/inconclusive and must stop before apply.

## Query-union seam fix evidence (local only)

- RED: the new regression test initially failed because discovery queries made
  direct selections on ProjectV2 unions.
- GREEN: corrected discovery and nested field-value queries with `__typename`
  and inline fragments for supported variants.
- Focused GitHub unit suite: `48 passed`.
- Focused Ruff on the changed test: all checks passed; `git diff --check`
  passed.
- No GitHub command, discovery, dry-run, export, apply, mutation, or commit
  was run in this fix cycle. Commit remains blocked by worktree index-lock
  permissions.

## Query fan-out fix round 3

Initial project discovery now requests `first: 1` only for nested fields, views,
items, and item field values; top-level projects and repository issues remain
fully paginated. Boundary assertions cover these limits.

- Focused GitHub tests: `48 passed`.
- Focused Ruff on the test: passed.
- Production Ruff currently reports E501 on long inline GraphQL documents from
  prior union fixes; formatting remains for controller follow-up.
- `git diff --check`: passed. No remote commands, dry-run, export, apply,
  mutations, or commit.

## Query-union seam fix round 2

Live review found nested `field { id name }` selections invalid because the
field reference is also a union. All item-value fragments now use explicit
`ProjectV2Field`, `ProjectV2SingleSelectField`, `ProjectV2IterationField`, and
`ProjectV2MultiSelectField` fragments; field-definition connections include all
four concrete variants. The boundary regression test now asserts the emitted
query contains these fragments and no direct nested field selection.

- Focused suite: `48 passed`.
- `git diff --check`: passed.
- No remote commands or mutations; changes remain uncommitted for controller
  commit because index-lock permissions are restricted.

## Query document formatting round 4

Expanded the prior union-fragment GraphQL selections onto readable lines in
the discovery and nested pagination documents without changing selections or
pagination limits.

- `UV_CACHE_DIR=/tmp/ao14d-uv-cache uv run ruff check app/project_control/github.py tests/unit/test_project_control_github.py`: `All checks passed!`
- `UV_CACHE_DIR=/tmp/ao14d-uv-cache uv run pytest tests/unit/test_project_control_github.py -q`: `48 passed in 0.05s`
- `git diff --check`: passed.
- No GitHub command, discovery, dry-run, export, apply, mutation, or commit was run.

## Discovery parser strictness round 5

The discovery parser now treats field-definition options according to the exact
GraphQL union discriminator: single-select definitions still require an
`options` list, while `ProjectV2Field`, `ProjectV2IterationField`, and
`ProjectV2MultiSelectField` definitions accept the schema-normal omission.
Other field-definition types fail closed. Item field values must carry one of
the supported concrete value discriminators, the selected scalar must match
that discriminator, and the nested field ID, name, and discriminator must all
match the discovered definition.

The former empty-transport query substring test was replaced with a successful
client fixture containing text, date, and single-select values plus normal
field, iteration, and multi-select definitions. The fixture exercises separate
field-definition and item-value pagination calls and checks their emitted
read-only documents and variables. Malformed definition discriminators, value
discriminators/scalar shapes, and nested field relationships are covered as
fail-closed cases. Repeated field-definition, field-reference, and item-value
GraphQL selections are now shared constants used by initial and nested query
documents.

- RED: the focused regression command exited `1` with `9 failed, 47 deselected`;
  the schema-shaped success case failed on omitted non-single-select options,
  while the discriminator/relationship cases either did not raise or raised
  only through the old unrelated duplicate-value path.
- GREEN: `UV_CACHE_DIR=/tmp/ao14d-round5-uv-cache uv run pytest tests/unit/test_project_control_github.py tests/unit/test_project_control_provisioning.py -q`
  exited `0` with `82 passed in 0.06s`.
- `UV_CACHE_DIR=/tmp/ao14d-round5-uv-cache uv run ruff check app/project_control/github.py tests/unit/test_project_control_github.py`
  exited `0` with `All checks passed!`.
- `git diff --check` exited `0` with no output.
- Pre-work local validation exited `1` with
  `control room invalid: coordination/codegraph/manifest.json: Codegraph is stale: source-tree digest differs from manifest`.
  No generated snapshot was edited or regenerated during this focused fix.
- No GitHub/network command, discovery, dry-run, export, apply, mutation, or
  commit was run.

## Urgent checkpoint after field and item provisioning (2026-09-02T06:26:27Z)

Provisioning is intentionally stopped in a truthful `partial` state. The live
project is `PVT_kwHODk-yLc4BiKTb` at
`https://github.com/users/Ven-Z8/projects/1`.

Confirmed completed remote resources:

- one project;
- all 12 managed fields, including `Roadmap kind` in place of GitHub's
  reserved `Type` name;
- all 30 stable-ID GitHub issues;
- all 30 project items.

Confirmed remaining work:

- 316 managed field values;
- six desired views, which may require documented manual configuration if the
  GitHub API does not support the required view mutations.

The first field-value mutation was rejected because GitHub requires typed
field values inside the non-null `value` object of
`UpdateProjectV2ItemFieldValueInput`; the current reviewed commit emitted the
typed key at the input root. Rediscovery then encountered GitHub's built-in
`ProjectV2ItemFieldRepositoryValue`, which does not implement the common field
value interface and therefore has no node ID in the current query. Both issues
have focused RED tests and an interrupted local repair preserved in the Git
stash named `WIP Task 10 field-value schema repair`; that repair is not part of
this pushed checkpoint because it has not passed review.

No delete action was planned or executed. No managed field value or desired
view is claimed complete. The machine-readable authoritative state is
`coordination/artifacts/reports/github-provisioning.json`.

## Dry-run transport seam fix (local only)

The dry-run path previously constructed a read-only `SubprocessGhTransport`
for discovery, then passed it to `GitHubProvisioner`, whose constructor rejected
any transport without `mutate`. Planning itself is pure and must not require a
mutation-capable transport.

- RED: `UV_CACHE_DIR=/tmp/ao14d-task10-uv-cache uv run pytest tests/integration/test_project_control_cli.py tests/unit/test_project_control_provisioning.py -q -k 'github_dry_run_plans_without_constructing_mutation_transport or apply_requires_mutation_transport_after_pure_planning'` exited `1` with the CLI regression returning `2` and `control room invalid: GitHub provisioning requires a mutate-only transport`; the unit regression also showed pure planning could not instantiate a provisioner without a transport.
- GREEN: the same focused regression command exited `0` with `2 passed, 46 deselected in 0.19s` after making the mutation transport optional for planning, requiring a callable mutate transport at `apply()`, and constructing no mutation transport in CLI dry-run mode.
- Focused suites: `UV_CACHE_DIR=/tmp/ao14d-task10-uv-cache uv run pytest tests/integration/test_project_control_cli.py -q -k 'not test_validate_command_succeeds_on_committed_control_room'` exited `0` with `23 passed, 1 deselected`; `UV_CACHE_DIR=/tmp/ao14d-task10-uv-cache uv run pytest tests/unit/test_project_control_github.py tests/unit/test_project_control_provisioning.py -q` exited `0` with `83 passed in 0.06s`.
- The combined focused run had `106 passed` and one unrelated failure in `test_validate_command_succeeds_on_committed_control_room`: the already-stale `coordination/codegraph/manifest.json` causes local validation to exit `2`. The manifest was not regenerated because this slice must not edit generated snapshots.
- `UV_CACHE_DIR=/tmp/ao14d-task10-uv-cache uv run ruff check app/project_control/cli.py app/project_control/github.py tests/integration/test_project_control_cli.py tests/unit/test_project_control_provisioning.py` exited `0` with `All checks passed!`; `git diff --check` exited `0` with no output.
- No GitHub/network command, live dry-run, export, apply, mutation, generated snapshot, or commit was run in this fix cycle.

## Approved live apply partial result

The reviewed apply was approved and run before this local repair cycle. It
stopped partial and preserved the one confirmed remote mutation:

- Project node ID: `PVT_kwHODk-yLc4BiKTb`.
- Project number: `1`.
- Project URL: `https://github.com/users/Ven-Z8/projects/1`.
- The project create action completed. The `Day` field create action was
  attempted but did not complete. No field, issue, item, field value, or view
  creation completed, so the remote project remains empty.
- The captured reconciliation report remains `partial`; all 12 fields, all 30
  issues, all 30 items, all planned field values, and all six views remain for
  a future reviewed resume. No delete action was introduced or run.
- The first blocker was a GraphQL validation failure because the create/update
  field mutation selected `options` directly on the
  `ProjectV2FieldConfiguration` union. The old transport mislabeled that
  nonzero result as `GitHub CLI is unavailable or unauthenticated`.
- Mandatory post-mutation read-only rediscovery then found the live default
  built-in `Linked pull requests`, which the local parser rejected as unknown.
  The complete live default set also includes `Parent issue`,
  `Sub-issues progress`, `Created`, `Updated`, and `Closed`, in addition to the
  previously ignored defaults.

## Reviewed resume dry-run after the partial apply

After the blocker repair and security re-review, two authenticated read-only
dry-runs produced byte-identical JSON and exited `0`. The latest capture is
`/tmp/ao14d-github-plan-reviewed-resume.json`.

- Total plan records: 395; remote mutations remaining: 394.
- Reuse the existing empty project `PVT_kwHODk-yLc4BiKTb`.
- Create 11 custom fields.
- Update GitHub's default `Status` field
  `PVTSSF_lAHODk-yLc4BiKTbzhhDVb0` from its default options to exactly
  `Inbox`, `Ready`, `In progress`, `In review`, `Blocked`, and `Done`.
- Create 30 issues, 30 project items, 316 field values, and six views.
- Zero delete actions.

This differs materially from the original all-create plan because GitHub
created the default `Status` field with the new project. No resume apply or
other mutation has run. A new explicit approval is required for the one update
and the remaining creates.

No retry, discovery, dry-run, export, apply, mutation, or other GitHub/network
command was run during the repair below.

## Partial-apply blocker repair (local only, 2026-09-01T21:12:08Z)

The local repair starts from source HEAD `4718fb2` and keeps the created project
for reconciliation; it performs no remote mutation.

- Discovery/export now ignores the complete confirmed live default field-name
  set while continuing to reject unknown custom fields.
- Create/update field mutations now select `__typename` and exact inline
  fragments for `ProjectV2Field`, `ProjectV2SingleSelectField`,
  `ProjectV2IterationField`, and `ProjectV2MultiSelectField`; `options` is
  selected only inside the single-select fragment.
- Field response parsing requires `options` for the exact single-select variant,
  accepts omission only for exact known non-single-select variants, and rejects
  unknown variants or impossible non-select responses that contain `options`.
- `Harness` remains a text field whose per-item text value is `Unassigned`; its
  field definition no longer carries an invalid single-select option.
- Nonzero apply results with structured or stderr GraphQL validation evidence
  now raise a sanitized validation error instead of a false authentication
  classification. Credential-like values in that evidence are redacted.

TDD and verification evidence:

- RED: `UV_CACHE_DIR=/tmp/ao14d-task10-partial-fix-uv-cache uv run pytest tests/unit/test_project_control_github.py tests/unit/test_project_control_provisioning.py -q -k 'complete_live_default_builtin_set or field_mutation_documents_select_union_variants or field_mutation_options_allow_omission_for_exact_non_select_variants or field_mutation_options_require_options_for_single_select or field_mutation_options_reject_unknown_or_impossible_variant_shape or apply_transport_preserves_sanitized_graphql_validation_evidence'` exited `1` with `9 failed, 1 passed, 83 deselected`. The failures independently exposed the missing built-in, both invalid union documents, omitted-option rejection for the known non-select variants, acceptance of malformed variants, and the false dependency classification.
- A broader unit run then exposed the text-field option mismatch before view
  handling. The focused schema invariant exited `1` with `1 failed, 36
  deselected` because `Harness` still carried `("Unassigned",)` as definition
  options.
- GREEN: `UV_CACHE_DIR=/tmp/ao14d-task10-partial-fix-uv-cache uv run pytest tests/unit/test_project_control_github.py tests/unit/test_project_control_provisioning.py -q` exited `0` with `97 passed in 0.07s`.
- Affected CLI tests: `UV_CACHE_DIR=/tmp/ao14d-task10-partial-fix-uv-cache uv run pytest tests/integration/test_project_control_cli.py -q -k 'github'` exited `0` with `3 passed, 21 deselected in 0.31s`.
- Ruff: `UV_CACHE_DIR=/tmp/ao14d-task10-partial-fix-uv-cache uv run ruff check app/project_control/github.py tests/unit/test_project_control_github.py tests/unit/test_project_control_provisioning.py tests/integration/test_project_control_cli.py` exited `0` with `All checks passed!`.
- `git diff --check` exited `0` with no output.
- Pre-repair `uv run python scripts/project_control.py validate` remained blocked
  by the already-stale `coordination/codegraph/manifest.json`; generated
  snapshots were not regenerated or edited in this repair.
- No commit was created.

## Partial-apply repair review round 1 (local only, 2026-09-01T21:19:38Z)

Review found that the first sanitizer could redact only the `Bearer` scheme in
an `Authorization` header and leave the actual credential in captured GraphQL
stderr. The transport boundary now removes the complete value for
case-insensitive `Authorization: Bearer ...` headers and token, secret, and
password assignments before applying the existing 500-character evidence
bound. It does not redact ordinary context such as `authorization policy
rejected requested field`, and useful GraphQL validation text remains visible.

The planning regression also now proves both sides of the Harness contract:
the text field definition has no options, while every planned Harness item
field value has `field_type: text` and `logical_value: Unassigned`.

- RED: `UV_CACHE_DIR=/tmp/ao14d-task10-redaction-round1-uv-cache uv run pytest tests/unit/test_project_control_provisioning.py -q -k 'harness_definition_is_optionless or preserves_sanitized_graphql_validation_evidence or bounds_sanitized_graphql_stderr'` exited `1` with `2 failed, 5 passed, 35 deselected`. Both failures exposed the leaked credential following mixed-case `Authorization: Bearer` headers, including the multiline case.
- Focused GREEN: the same command exited `0` with `7 passed, 35 deselected in 0.04s`.
- Full GitHub/provisioning units: `UV_CACHE_DIR=/tmp/ao14d-task10-redaction-round1-full-uv-cache uv run pytest tests/unit/test_project_control_github.py tests/unit/test_project_control_provisioning.py -q` exited `0` with `102 passed in 0.07s`.
- Ruff: `UV_CACHE_DIR=/tmp/ao14d-task10-redaction-round1-ruff-uv-cache uv run ruff check app/project_control/github.py tests/unit/test_project_control_github.py tests/unit/test_project_control_provisioning.py tests/integration/test_project_control_cli.py` exited `0` with `All checks passed!`.
- `git diff --check` exited `0` with no output.
- No GitHub/network command, discovery, dry-run, export, apply, mutation, or
  commit was run.

## Second approved resume partial result and repair (2026-09-01T21:26:41Z)

The second reviewed resume reused project `PVT_kwHODk-yLc4BiKTb`, attempted the
first remaining action (`Day` field creation), and stopped before any remote
mutation. GitHub rejected `singleSelectOptions` because the allowlisted input
contained strings such as `"Day 1"`; the schema requires
`ProjectV2SingleSelectFieldOptionInput` objects. The existing project and its
GitHub-created default `Status` field remain unchanged; no custom field, issue,
item, field value, or view was created or updated by this resume.

Read-only schema evidence established these exact boundaries:

- `CreateProjectV2FieldInput` accepts `projectId`, `dataType`, `name`, and
  `singleSelectOptions`.
- Each single-select option input requires `name`, `color`, and `description`,
  with optional `id`.
- `UpdateProjectV2FieldInput` accepts `fieldId`, optional `name`, and
  `singleSelectOptions`; it does not accept `projectId` or `dataType`.

The local repair uses a deterministic neutral visual policy: every option is
serialized with `color: GRAY` and an empty description. Desired option order is
preserved. Updates attach a validated existing option ID only when its name is
still desired, so matching identities such as `Done` can be reused while
removed defaults such as `Todo` are omitted. Create inputs never
emit IDs, and update inputs never emit create-only keys. Response reconciliation
continues to require the exact desired option-name order.

TDD and verification evidence:

- RED: `UV_CACHE_DIR=/tmp/ao14d-task10-option-input-round2-uv-cache uv run pytest tests/unit/test_project_control_provisioning.py -q -k 'create_day_field_input_serializes_literal_option_objects or update_status_field_input_reuses_matching_ids_without_create_only_keys or update_field_input_rejects_malformed_option_id_maps'` exited `1` with `7 failed, 42 deselected`. Day returned strings, Status included `projectId`/`dataType` and dropped existing IDs, and all five malformed option-ID maps bypassed validation.
- Focused GREEN: the same command exited `0` with `7 passed, 42 deselected in 0.04s` against literal Day and Status payloads.
- Full GitHub/provisioning units: `UV_CACHE_DIR=/tmp/ao14d-task10-option-input-round2-full-uv-cache uv run pytest tests/unit/test_project_control_github.py tests/unit/test_project_control_provisioning.py -q` exited `0` with `109 passed in 0.07s`.
- Affected CLI tests: `UV_CACHE_DIR=/tmp/ao14d-task10-option-input-round2-cli-uv-cache uv run pytest tests/integration/test_project_control_cli.py -q -k 'github'` exited `0` with `3 passed, 21 deselected in 0.32s`.
- Ruff: `UV_CACHE_DIR=/tmp/ao14d-task10-option-input-round2-ruff-uv-cache uv run ruff check app/project_control/github.py tests/unit/test_project_control_github.py tests/unit/test_project_control_provisioning.py tests/integration/test_project_control_cli.py` exited `0` with `All checks passed!`.
- `git diff --check` exited `0` with no output.
- No GitHub/network command, discovery, dry-run, export, apply, mutation, or
  commit was run during this repair.

## Field-option identity review round 3 (local only, 2026-09-02T06:02:56Z)

Review found that a malformed update map could assign the same remote option ID
to multiple desired names. The input boundary now rejects duplicate option IDs
before serialization. It also rejects duplicate desired option names, ensuring
the ordered option-object list carries a one-to-one name/identity relationship.

- RED: `UV_CACHE_DIR=/tmp/ao14d-task10-option-identity-round3-uv-cache uv run pytest tests/unit/test_project_control_provisioning.py -q -k 'update_field_input_rejects_malformed_option_id_maps or update_field_input_rejects_duplicate_desired_option_names'` exited `1` with `2 failed, 5 passed, 44 deselected`; both duplicate identities and duplicate desired names were accepted.
- Focused GREEN: the same command exited `0` with `7 passed, 44 deselected in 0.04s`.
- Full GitHub/provisioning units: `UV_CACHE_DIR=/tmp/ao14d-task10-option-identity-round3-full-uv-cache uv run pytest tests/unit/test_project_control_github.py tests/unit/test_project_control_provisioning.py -q` exited `0` with `111 passed in 0.07s`.
- Ruff: `UV_CACHE_DIR=/tmp/ao14d-task10-option-identity-round3-ruff-uv-cache uv run ruff check app/project_control/github.py tests/unit/test_project_control_github.py tests/unit/test_project_control_provisioning.py` exited `0` with `All checks passed!`.
- `git diff --check` exited `0` with no output.
- No GitHub/network command, discovery, dry-run, export, apply, mutation, or
  commit was run.

## Reserved `Type` partial result and local repair (2026-09-02T06:13:43Z)

The approved resume recorded at `2026-09-02T06:04:54.046203Z` reused project
`PVT_kwHODk-yLc4BiKTb` and completed `Day`, `Dependency`, `Evidence`,
`Handoff`, `Harness`, `Phase`, `Priority`, `Risk`, the `Status` update, and
`Target date`. Its next action was the `Type` field creation. GitHub rejected
that mutation with `Name cannot have a reserved value, Name has already been
taken`, so `Workstream` and every issue, item, field value, and view remained
unattempted in that run.

The local repair starts from source HEAD `e7bfd19`. It changes only the managed
remote label from `Type` to `Roadmap kind`, classifies bare `Type` as an ignored
GitHub built-in, and preserves the six approved option names and each roadmap
item's logical `kind` value. The approved design and implementation-plan field
lists now use the schema-valid label.

TDD and verification evidence:

- RED: `UV_CACHE_DIR=/tmp/ao14d-roadmap-kind-red-uv-cache uv run pytest tests/unit/test_project_control_provisioning.py -q -k reserved_type_is_unmanaged_and_roadmap_kind_preserves_item_kinds` exited `1` with `1 failed, 51 deselected`; the literal plan assertion showed `Type` was still emitted as a managed field.
- Focused GREEN: `UV_CACHE_DIR=/tmp/ao14d-roadmap-kind-green-uv-cache uv run pytest tests/unit/test_project_control_provisioning.py -q -k reserved_type_is_unmanaged_and_roadmap_kind_preserves_item_kinds` exited `0` with `1 passed, 51 deselected in 0.04s`.
- Full GitHub/provisioning units: `UV_CACHE_DIR=/tmp/ao14d-roadmap-kind-full-uv-cache uv run pytest tests/unit/test_project_control_github.py tests/unit/test_project_control_provisioning.py -q` exited `0` with `112 passed in 0.08s`.
- The first focused Ruff run found one overlong test assertion; the assertion was
  reformatted without changing behavior and the final Ruff result is recorded
  below.
- Final Ruff: `UV_CACHE_DIR=/tmp/ao14d-roadmap-kind-ruff-uv-cache uv run ruff check app/project_control/github.py tests/unit/test_project_control_github.py tests/unit/test_project_control_provisioning.py` exited `0` with `All checks passed!`.
- `git diff --check` exited `0` with no output.
- No GitHub/network command, discovery, dry-run, export, apply, or mutation was
  run during this repair.
