# Pydantic v2 migration playbook

Migrate only the Pydantic v1 API seams in the application. Preserve the tested
behavior, keep the patch focused, and do not change dependency or CI files.

1. Run the focused behavior tests before editing and record the baseline result.
2. Replace `@validator` with `@field_validator`; update the import and use a
   classmethod-compatible validator signature.
3. Replace the inner `Config` class and `orm_mode` with
   `model_config = ConfigDict(from_attributes=True)`; update the import.
4. Replace `.dict(...)` calls with `.model_dump(...)`.
5. Replace `.from_orm(...)` calls with `.model_validate(...)`. Object-attribute
   validation is enabled by the model's `from_attributes=True` configuration.
6. Run the focused behavior tests again and confirm normalization, omit-none
   serialization, and object-attribute validation still pass.
7. Search the repository for remaining `validator`, `Config`, `orm_mode`, and
   `.dict(` migration seams. Resolve application-code matches without changing
   unrelated files.

Do not edit dependency declarations, lockfiles, CI configuration, or workflows.
