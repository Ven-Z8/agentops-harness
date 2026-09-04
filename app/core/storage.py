from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.schemas.run import RunRecord


class RunStorage:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, record: RunRecord) -> None:
        if self.path.suffix in {".db", ".sqlite", ".sqlite3"}:
            SQLiteRunStorage(self.path).save(record)
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")

    def get(self, run_id: str) -> RunRecord:
        if self.path.suffix in {".db", ".sqlite", ".sqlite3"}:
            return SQLiteRunStorage(self.path).get(run_id)

        if not self.path.exists():
            raise KeyError(f"Run not found: {run_id}")

        # Append-only log: a re-saved run_id is a REVISION (e.g. the
        # positive-contract gate folding its verdict into record.status).
        # Latest write wins — mirroring SQLite's INSERT OR REPLACE. First
        # match wins would silently keep a stale verdict.
        latest: dict | None = None
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                if payload.get("run_id") == run_id:
                    latest = payload
        if latest is None:
            raise KeyError(f"Run not found: {run_id}")
        return RunRecord.model_validate(latest)

    def list(self, limit: int = 20) -> list[RunRecord]:
        if self.path.suffix in {".db", ".sqlite", ".sqlite3"}:
            return SQLiteRunStorage(self.path).list(limit=limit)

        if not self.path.exists():
            return []

        # Latest-first, deduped by run_id: a revision supersedes its
        # earlier lines so a run never appears twice in a list view.
        records: list[RunRecord] = []
        seen: set[str] = set()
        with self.path.open(encoding="utf-8") as handle:
            for line in reversed(handle.readlines()):
                if not line.strip():
                    continue
                record = RunRecord.model_validate_json(line)
                if record.run_id in seen:
                    continue
                seen.add(record.run_id)
                records.append(record)
                if len(records) >= limit:
                    break
        return records


class SQLiteRunStorage:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, record: RunRecord) -> None:
        self._ensure_schema()
        payload = record.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id, task, repo_path, status, risk_score, risk_level,
                    started_at, completed_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.task,
                    record.repo_path,
                    record.status,
                    record.risk_report.risk_score,
                    record.risk_report.risk_level,
                    record.started_at.isoformat(),
                    record.completed_at.isoformat(),
                    payload,
                ),
            )

    def get(self, run_id: str) -> RunRecord:
        self._ensure_schema()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Run not found: {run_id}")
        return RunRecord.model_validate_json(row["payload"])

    def list(self, limit: int = 20) -> list[RunRecord]:
        self._ensure_schema()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM runs ORDER BY completed_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [RunRecord.model_validate_json(row["payload"]) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    repo_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    risk_score INTEGER NOT NULL,
                    risk_level TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_completed_at ON runs(completed_at DESC)"
            )
