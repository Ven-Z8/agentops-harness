from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import yaml

from app.core.git_utils import is_git_repo, run_git
from app.core.handoff import render_handoff_markdown, worker_handoff_from_run
from app.schemas.run import RunRecord


def artifact_root_for_storage(storage_path: Path) -> Path:
    """Return the directory that contains per-run artifact folders."""
    return storage_path.parent / "runs"


def artifact_dir_for_run(storage_path: Path, run_id: str) -> Path:
    return artifact_root_for_storage(storage_path) / run_id


def artifact_path_for_run(storage_path: Path, run_id: str) -> Path:
    return artifact_dir_for_run(storage_path, run_id)


class RunArtifactWriter:
    """Writes inspectable file artifacts for a completed harness run."""

    def write(self, record: RunRecord, storage_path: Path) -> Path:
        artifact_dir = artifact_dir_for_run(storage_path, record.run_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        self._write_json(artifact_dir / "repo_profile.json", record.repo_profile)
        self._write_json(artifact_dir / "repo_graph.json", record.repo_graph)
        self._write_yaml(artifact_dir / "task_plan.yaml", record.plan.model_dump(mode="json"))
        self._write_text(
            artifact_dir / "worker_packet.md",
            render_handoff_markdown(worker_handoff_from_run(record)),
        )
        self._write_json(artifact_dir / "impacted_graph.json", record.changed_subgraph)
        self._write_diff_patch(artifact_dir / "diff.patch", Path(record.repo_path))
        self._write_json(artifact_dir / "test_results.json", record.test_results)
        self._write_json(artifact_dir / "risk_report.json", record.risk_report)
        self._write_json(artifact_dir / "permission_report.json", record.permission_report)
        self._write_json(artifact_dir / "evidence_report.json", record.evidence_report)
        self._write_json(artifact_dir / "verification_bundle.json", record.verification_bundle)
        self._write_json(artifact_dir / "conflict_report.json", record.conflict_report)
        self._write_text(artifact_dir / "final_report.md", record.final_report.markdown)
        self._write_trace(artifact_dir / "trace.jsonl", record)
        self._write_json(artifact_dir / "run_record.json", record)
        return artifact_dir

    def _write_json(self, path: Path, value: Any) -> None:
        payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _write_yaml(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    def _write_text(self, path: Path, text: str) -> None:
        path.write_text(text.rstrip() + "\n", encoding="utf-8")

    def _write_diff_patch(self, path: Path, repo_path: Path) -> None:
        if not is_git_repo(repo_path):
            return
        diff = run_git(repo_path, ["diff", "--binary"])
        if diff.stdout.strip():
            path.write_text(diff.stdout, encoding="utf-8")

    def _write_trace(self, path: Path, record: RunRecord) -> None:
        lines = []
        for index, event in enumerate(record.execution_logs):
            lines.append(
                json.dumps(
                    {
                        "index": index,
                        "event": event,
                        "run_id": record.run_id,
                        "task": record.task,
                        "status": record.status,
                    },
                    sort_keys=True,
                )
            )
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def artifact_links_markdown(artifact_dir: Path) -> str:
    return (
        "\n\n## Run artifacts\n\n"
        f"- Artifact directory: `{artifact_dir}`\n"
        "- Key files: `repo_profile.json`, `repo_graph.json`, `task_plan.yaml`, "
        "`worker_packet.md`, `impacted_graph.json`, `test_results.json`, "
        "`final_report.md`, `trace.jsonl`\n"
    )


def append_artifact_links(record: RunRecord, artifact_dir: Path) -> RunRecord:
    suffix = artifact_links_markdown(artifact_dir)
    if "## Run artifacts" in record.final_report.markdown:
        return record
    record.final_report.markdown = record.final_report.markdown.rstrip() + suffix
    return record


def export_artifact_bundle(artifact_dir: Path, output_file: Path) -> Path:
    if not artifact_dir.is_dir():
        raise FileNotFoundError(f"Artifact directory not found: {artifact_dir}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(artifact_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(artifact_dir))
    return output_file
