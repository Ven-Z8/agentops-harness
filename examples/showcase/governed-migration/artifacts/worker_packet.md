# Worker handoff packet

> **Completed run snapshot:** Harness already executed through review and risk gates.

## Metadata

- Phase: `completed_run`
- Repo: `examples/showcase/fixtures/pydantic-v1-app`
- Run ID: `showcase-governed-migration`
- Harness status: `completed`

## Original task

Migrate this application from deprecated Pydantic v1 APIs to supported Pydantic v2 APIs. Preserve behavior, make the smallest controlled change, and run the focused tests.

## Plan summary

Update app/models.py to use Pydantic v2 APIs (BaseModel, Field, validators, etc.) while preserving behavior. Run existing tests to confirm no regressions.

## Acceptance criteria

- All existing tests pass with no failures
- No Pydantic v1 deprecation warnings in test output
- Application behavior unchanged (same inputs produce same outputs)

## Suggested execution steps

1. **Inspect current Pydantic v1 usage**
   - Read app/models.py and app/service.py to identify all Pydantic v1 APIs (e.g., BaseModel, Field, validators, root_validator, validator, Config class, etc.) that need migration.
   - Inspect: `app/models.py, app/service.py, tests/test_service.py`
   - Edit: `—`

2. **Update app/models.py to Pydantic v2**
   - Replace deprecated Pydantic v1 patterns with v2 equivalents: change BaseModel import, update validators (use @field_validator, @model_validator), replace Config class with model_config, update Field usage if needed. Preserve all field names, types, and validation logic exactly.
   - Inspect: `—`
   - Edit: `app/models.py`

3. **Update app/service.py if needed**
   - Check if service.py uses any Pydantic v1-specific APIs (e.g., .dict(), .schema(), .json() with v1 behavior). If so, update to v2 equivalents (.model_dump(), .model_dump_json()).
   - Inspect: `—`
   - Edit: `app/service.py`

4. **Run focused tests**
   - Execute the existing test suite to verify behavior is preserved.
   - Inspect: `—`
   - Edit: `—`

## Tests the harness associates with this task

- uv run pytest -q
- uv run ruff check .

## Verification commands (exact)

```bash
uv run pytest -q
uv run ruff check .
```

## Plan risk notes

- No secrets or auth concerns in this migration
- Dependency: Ensure pydantic>=2.0 is installed (uv add pydantic@latest)
- No broad refactor needed; only targeted API changes in models.py and possibly service.py
- If validators use v1-specific patterns (e.g., pre=True, each_item=True), ensure v2 equivalents are correct
- Check for any use of .dict() -> .model_dump(), .json() -> .model_dump_json(), .schema() -> .model_json_schema()

## Worker constraints

- Do not rewrite unrelated files.
- Keep changes minimal and reversible; prefer small commits.
- Do not force-push, hard-reset, or delete git history.
- Run the verification commands exactly as listed before declaring done.
- If blocked, summarize blockers instead of speculative large refactors.

## Harness outcome (filled after a full run)

| Field | Value |
|---|---|
| changed_files | `app/models.py, app/service.py` |
| deleted_files | `—` |
| risk_level | `low` |
| risk_score | `18` |
| risk_blocked | `False` |
| external worker | `completed` |
