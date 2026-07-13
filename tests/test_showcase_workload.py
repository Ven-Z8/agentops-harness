from pathlib import Path

FIXTURE = Path("examples/showcase/fixtures/pydantic-v1-app")


def test_legacy_fixture_contains_real_v1_migration_seams() -> None:
    models = (FIXTURE / "app" / "models.py").read_text(encoding="utf-8")
    service = (FIXTURE / "app" / "service.py").read_text(encoding="utf-8")

    assert "@validator" in models
    assert "class Config:" in models
    assert "orm_mode" in models
    assert ".dict(" in service
    assert ".from_orm(" in service
