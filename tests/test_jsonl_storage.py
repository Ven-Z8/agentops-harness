"""JSONL RunStorage revision semantics (AO-D03-01 support).

The governed pipeline may need to REVISE a stored record after the fact —
the canonical case is the positive-contract gate folding its verdict into
``record.status`` after ``run_harness`` already persisted the run. An
append-only log supports revision by re-saving the same run_id: the latest
write must win, mirroring SQLite's INSERT OR REPLACE. First-write-wins
would silently keep a stale (dishonest) verdict.
"""

from __future__ import annotations

from pathlib import Path

from app.core.storage import RunStorage
from tests.helpers_runrecord import minimal_run_record


class TestJsonlRevisionSemantics:
    def test_get_returns_latest_write_after_resave(self, tmp_path: Path) -> None:
        storage = RunStorage(tmp_path / "runs.jsonl")
        record = minimal_run_record()
        assert record.status == "completed"
        storage.save(record)

        # The positive-contract gate revises the verdict post-hoc.
        revised = record.model_copy(update={"status": "failed"})
        storage.save(revised)

        assert storage.get(record.run_id).status == "failed"

    def test_list_dedupes_revisions_keeping_latest(self, tmp_path: Path) -> None:
        """The console's /runs list must not show the same run twice — the
        revision supersedes the original line."""
        storage = RunStorage(tmp_path / "runs.jsonl")
        first = minimal_run_record()
        second = minimal_run_record().model_copy(
            update={"run_id": "other-run", "status": "blocked"}
        )
        storage.save(first)
        storage.save(second)
        storage.save(first.model_copy(update={"status": "failed"}))

        listed = storage.list()
        by_id = {record.run_id: record for record in listed}

        assert len(listed) == len(by_id)  # no duplicates
        assert by_id["testrun"].status == "failed"  # latest revision wins
        assert by_id["other-run"].status == "blocked"

    def test_list_preserves_latest_first_order(self, tmp_path: Path) -> None:
        storage = RunStorage(tmp_path / "runs.jsonl")
        storage.save(minimal_run_record())
        storage.save(minimal_run_record().model_copy(update={"run_id": "newer"}))

        assert [record.run_id for record in storage.list()] == ["newer", "testrun"]
