# Worker Packet
You are a coding worker running inside AgentOps Harness.
AgentOps is the outer governance harness.
You are the inner implementation worker.

## Task
Migrate this application from deprecated Pydantic v1 APIs to supported Pydantic v2 APIs. Preserve behavior, make the smallest controlled change, and run the focused tests.

## Plan as Contract
- Summary: Update app/models.py to use Pydantic v2 APIs (BaseModel, Field, validators, etc.) while preserving behavior. Run existing tests to confirm no regressions.
- Step 1: Inspect current Pydantic v1 usage - Read app/models.py and app/service.py to identify all Pydantic v1 APIs (e.g., BaseModel, Field, validators, root_validator, validator, Config class, etc.) that need migration.
  - Inspect: app/models.py, app/service.py, tests/test_service.py
- Step 2: Update app/models.py to Pydantic v2 - Replace deprecated Pydantic v1 patterns with v2 equivalents: change BaseModel import, update validators (use @field_validator, @model_validator), replace Config class with model_config, update Field usage if needed. Preserve all field names, types, and validation logic exactly.
  - Edit: app/models.py
- Step 3: Update app/service.py if needed - Check if service.py uses any Pydantic v1-specific APIs (e.g., .dict(), .schema(), .json() with v1 behavior). If so, update to v2 equivalents (.model_dump(), .model_dump_json()).
  - Edit: app/service.py
- Step 4: Run focused tests - Execute the existing test suite to verify behavior is preserved.
  - Tests: uv run pytest -q tests/test_service.py
- Acceptance criteria:
  - All existing tests pass with no failures
  - No Pydantic v1 deprecation warnings in test output
  - Application behavior unchanged (same inputs produce same outputs)
- Risk notes:
  - No secrets or auth concerns in this migration
  - Dependency: Ensure pydantic>=2.0 is installed (uv add pydantic@latest)
  - No broad refactor needed; only targeted API changes in models.py and possibly service.py
  - If validators use v1-specific patterns (e.g., pre=True, each_item=True), ensure v2 equivalents are correct
  - Check for any use of .dict() -> .model_dump(), .json() -> .model_dump_json(), .schema() -> .model_json_schema()
Follow this plan unless repo inspection proves it is wrong.
If the plan is wrong, make the smallest safe correction and explain it.

## Repo Context
- Repo path: examples/showcase/fixtures/pydantic-v1-app
- Language: python
- Package manager: uv
- Test framework: pytest
- Important folders: app, tests
- Config files: pyproject.toml

## Likely Impacted Files
- app/models.py
- app/service.py
- tests/test_service.py

## Constraints
- Keep the diff minimal.
- Do not edit unrelated files.
- Do not touch sensitive paths.
- Do not modify tests just to make them pass unless explicitly required.
- Prefer implementation changes over test weakening.
- If you cannot proceed safely, stop and explain why.

## Forbidden Actions
- Do not add secrets, credentials, tokens, private keys, or real API keys.
- Do not modify lockfiles, generated files, or CI configuration unless the plan requires it.
- Do not change public behavior outside the task scope.
- Do not claim tests passed unless you actually ran them and saw success.

## Forbidden Paths
- .env, .env.*, **/*secret*, **/*token*, private keys, credential stores

## Permission Tier
standard

## Verification Obligations
Run these if possible:
- uv run pytest -q
- uv run pytest -q tests/test_service.py
- uv run ruff check .
If you cannot run them, explain why.

## Definition of Done
The task is done only when:
- required implementation is complete
- diff is minimal
- validation has been attempted
- no forbidden paths are touched
- final message summarizes exactly what changed

## Reporting Rules
Do not claim tests passed unless you actually ran them and saw success.
Do not claim files changed unless you changed them.
Do not claim routes/endpoints were added unless they exist in the diff.
If blocked, explain the blocker and stop.
