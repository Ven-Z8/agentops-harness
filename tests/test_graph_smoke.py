import subprocess
from pathlib import Path

from app.core.graph import run_harness
from app.core.workers.openhands_artifacts import write_worker_summary
from app.core.workers.openhands_worker import OpenHandsWorker
from app.schemas.edit import ExternalEditResult
from app.schemas.pack import CapabilityPackProvenance
from app.schemas.worker_loop import WorkerLoopSummary

_SKIP_PARTS = {".git", "__pycache__", ".pytest_cache", ".venv"}


def _copy_sample_repo(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if _SKIP_PARTS.intersection(relative.parts):
            continue
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())


def _init_git_repo(repo_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repo_path, check=True, capture_output=True
    )


def test_run_harness_produces_report_and_persists_record(tmp_path: Path) -> None:
    # Run against an isolated clean git copy of the fixture so the fixture does
    # not need to be a nested git repo (which cannot be cloned from origin).
    repo = tmp_path / "sample_fastapi_app"
    _copy_sample_repo(Path("examples/sample_fastapi_app"), repo)
    _init_git_repo(repo)
    storage_path = tmp_path / "runs.jsonl"

    result = run_harness(
        repo_path=repo,
        task="Add request logging middleware",
        storage_path=storage_path,
        test_commands=["python -m pytest -q"],
    )

    assert result.status == "completed"
    assert result.repo_profile.framework == "fastapi"
    assert result.plan.acceptance_criteria
    assert result.changed_files == []
    assert result.test_results.passed is True
    assert "Risk assessment" in result.final_report.markdown
    assert storage_path.exists()
    assert result.run_id in storage_path.read_text()

    artifact_dir = storage_path.parent / "runs" / result.run_id
    assert artifact_dir.is_dir()
    assert (artifact_dir / "repo_profile.json").exists()
    assert (artifact_dir / "repo_graph.json").exists()
    assert (artifact_dir / "task_plan.yaml").exists()
    assert (artifact_dir / "worker_packet.md").exists()
    assert (artifact_dir / "impacted_graph.json").exists()
    assert (artifact_dir / "test_results.json").exists()
    assert (artifact_dir / "risk_report.json").exists()
    assert (artifact_dir / "permission_report.json").exists()
    assert (artifact_dir / "evidence_report.json").exists()
    assert (artifact_dir / "verification_bundle.json").exists()
    assert (artifact_dir / "conflict_report.json").exists()
    assert (artifact_dir / "final_report.md").exists()
    assert (artifact_dir / "trace.jsonl").exists()
    assert "## Run artifacts" in result.final_report.markdown
    assert str(artifact_dir) in result.final_report.markdown


def test_bad_pack_name_blocks_run_instead_of_crashing(tmp_path: Path) -> None:
    # A typo'd --pack must NOT crash graph.invoke() with no run record. The most common
    # authoring mistake should produce a blocked run with a clear message, not a traceback.
    repo = tmp_path / "sample_fastapi_app"
    _copy_sample_repo(Path("examples/sample_fastapi_app"), repo)
    _init_git_repo(repo)
    storage_path = tmp_path / "runs.jsonl"

    result = run_harness(
        repo_path=repo,
        task="x",
        storage_path=storage_path,
        worker_type="openhands",
        pack="definitely-not-a-real-pack-xyz",
        test_commands=["python -m pytest -q"],
    )

    assert result.edit_result is not None
    assert result.edit_result.status == "blocked"
    assert result.edit_result.termination_reason == "pack_error"
    assert "pack" in (result.edit_result.stderr or "").lower()
    # the run was still persisted (no crash)
    assert storage_path.exists() and result.run_id in storage_path.read_text()


def test_openhands_summary_provenance_is_lifted_to_run_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    _copy_sample_repo(Path("examples/sample_fastapi_app"), repo)
    _init_git_repo(repo)
    provenance = CapabilityPackProvenance(
        name="example",
        domain="general",
        version="0.1.0",
        description="example",
        skills=["overview.md"],
        resolved_tools=["terminal", "file_editor"],
        hooks=[],
        manifest_sha256="c" * 64,
    )

    def fake_run(self, **kwargs):
        write_worker_summary(
            kwargs["run_dir"],
            WorkerLoopSummary(
                status="completed",
                tools_requested=provenance.resolved_tools,
                capability_pack=provenance,
            ),
        )
        return ExternalEditResult(
            status="completed",
            command="fake",
            worker_type="openhands",
        )

    monkeypatch.setattr(OpenHandsWorker, "run", fake_run)
    record = run_harness(
        repo_path=repo,
        task="inspect provenance",
        storage_path=tmp_path / "runs.db",
        worker_type="openhands",
        pack="example",
        test_commands=["python -m pytest -q"],
    )
    assert record.capability_pack == provenance


def test_run_harness_maps_changed_file_to_impacted_graph(tmp_path: Path) -> None:
    repo = tmp_path / "sample_fastapi_app"
    _copy_sample_repo(Path("examples/sample_fastapi_app"), repo)
    _init_git_repo(repo)
    storage_path = tmp_path / "runs.db"
    worker_path = tmp_path / "worker.py"
    worker_path.write_text(
        "from pathlib import Path\n"
        "path = Path('app/main.py')\n"
        "addition = '\\n\\n@app.get(\"/smoke\")\\ndef smoke():\\n    return {\"smoke\": True}\\n'\n"
        "path.write_text(path.read_text() + addition)\n"
        "print('added /smoke route to app/main.py')\n"
    )

    result = run_harness(
        repo_path=repo,
        task="Add a /smoke endpoint to the FastAPI app",
        storage_path=storage_path,
        worker_command=f"python {worker_path}",
    )

    assert result.status == "completed"
    assert "app/main.py" in result.changed_files
    assert "app/main.py" in result.changed_subgraph.changed_files
    # M2: the worker-added route is detected; the untouched /health and /version
    # routes are scoped out (no longer over-included just because the file changed).
    assert {route.path for route in result.changed_subgraph.impacted_routes} == {"/smoke"}
    assert "tests/test_health.py" in result.changed_subgraph.related_tests
    commands = [item.command for item in result.changed_subgraph.recommended_validation]
    assert "uv run pytest tests/test_health.py tests/test_version.py -q" in commands
    assert "uv run ruff check ." in commands
    assert "## Impacted Area" in result.final_report.markdown
    assert "GET /smoke" in result.final_report.markdown

    artifact_dir = storage_path.parent / "runs" / result.run_id
    impacted_graph = artifact_dir / "impacted_graph.json"
    assert impacted_graph.exists()
    assert "app/main.py" in impacted_graph.read_text()
