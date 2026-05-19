from pathlib import Path

import pytest

from app.core.graph import run_harness
from app.core.storage import SQLiteRunStorage


def test_sqlite_storage_saves_and_fetches_run(tmp_path: Path) -> None:
    storage_path = tmp_path / "runs.db"
    record = run_harness(
        repo_path=Path("examples/sample_fastapi_app"),
        task="Add request logging middleware",
        storage_path=storage_path,
    )

    fetched = SQLiteRunStorage(storage_path).get(record.run_id)

    assert fetched.run_id == record.run_id
    assert fetched.final_report.markdown == record.final_report.markdown


def test_sqlite_storage_lists_latest_runs(tmp_path: Path) -> None:
    storage_path = tmp_path / "runs.db"
    first = run_harness(
        repo_path=Path("examples/sample_fastapi_app"),
        task="First task",
        storage_path=storage_path,
    )
    second = run_harness(
        repo_path=Path("examples/sample_fastapi_app"),
        task="Second task",
        storage_path=storage_path,
    )

    runs = SQLiteRunStorage(storage_path).list(limit=2)

    assert [run.run_id for run in runs] == [second.run_id, first.run_id]


def test_sqlite_storage_raises_for_missing_run(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        SQLiteRunStorage(tmp_path / "runs.db").get("missing")
