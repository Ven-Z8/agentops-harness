import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from app.core.workers.openhands_worker import OpenHandsWorker


def test_blocks_on_non_git_repo(tmp_path: Path):
    result = OpenHandsWorker().run(repo_path=tmp_path, task="x", timeout_seconds=5)
    assert result.status == "blocked"
    assert "git repository" in result.stderr


def test_blocks_on_dirty_repo(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "f.py").write_text("x=1\n")  # untracked -> dirty
    result = OpenHandsWorker().run(repo_path=tmp_path, task="x", timeout_seconds=5)
    assert result.status == "blocked"
    assert "dirty" in result.stderr.lower()


def test_allows_dirty_repo_when_requested_and_passes_prompt_on_stdin(tmp_path: Path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "f.py").write_text("x=1\n")
    seen = {}

    def fake_run(argv, *args, **kwargs):
        if argv[:2] == ["git", "rev-parse"]:
            return SimpleNamespace(returncode=0, stdout=str(tmp_path), stderr="")
        if argv[:3] == ["git", "status", "--porcelain"]:
            return SimpleNamespace(returncode=0, stdout="?? f.py\n", stderr="")
        seen["argv"] = argv
        seen["input"] = kwargs["input"]
        seen["cwd"] = kwargs["cwd"]
        seen["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = OpenHandsWorker().run(
        repo_path=tmp_path,
        task="Add logging",
        timeout_seconds=5,
        allow_dirty=True,
    )

    assert result.status == "completed"
    assert "agentops-harness" in str(seen["cwd"])
    assert "PYTHONPATH" in seen["env"]
    assert "agentops-harness" in seen["env"]["PYTHONPATH"]
    assert seen["input"].startswith("# Worker Packet")
    assert "## Task\nAdd logging" in seen["input"]


def test_runner_exits_2_without_a_task():
    # The runner reads the task from stdin; an empty task is a usage error (exit 2),
    # reached before any SDK import or auth — so this needs neither.
    completed = subprocess.run(
        [sys.executable, "-m", "app.core.workers.openhands_runner", "."],
        input="",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 2


def test_missing_sdk_exit_maps_to_setup_missing(tmp_path: Path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    def fake_run(argv, *args, **kwargs):
        if argv[:2] == ["git", "rev-parse"]:
            return SimpleNamespace(returncode=0, stdout=str(tmp_path), stderr="")
        if argv[:3] == ["git", "status", "--porcelain"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=4, stdout="", stderr="OpenHands SDK not installed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = OpenHandsWorker().run(repo_path=tmp_path, task="x", timeout_seconds=5)

    assert result.status == "setup_missing"
    assert result.termination_reason == "sdk_missing"
    assert "OpenHands SDK not installed" in result.stderr


def test_config_error_exit_maps_to_configuration_error(tmp_path: Path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    def fake_run(argv, *args, **kwargs):
        if argv[:2] == ["git", "rev-parse"]:
            return SimpleNamespace(returncode=0, stdout=str(tmp_path), stderr="")
        if argv[:3] == ["git", "status", "--porcelain"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(
            returncode=6,
            stdout="",
            stderr="configuration_error: OPENHANDS_MAX_ITERATIONS must be a positive integer.",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = OpenHandsWorker().run(repo_path=tmp_path, task="x", timeout_seconds=5)

    assert result.status == "configuration_error"
    assert result.termination_reason == "configuration_error"
    # The bad-config case must NOT tell the operator to reinstall the SDK.
    assert "uv sync --extra openhands" not in result.stderr
    assert "OPENHANDS_MAX_ITERATIONS" in result.stderr


def test_missing_auth_exit_maps_to_auth_missing(tmp_path: Path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    def fake_run(argv, *args, **kwargs):
        if argv[:2] == ["git", "rev-parse"]:
            return SimpleNamespace(returncode=0, stdout=str(tmp_path), stderr="")
        if argv[:3] == ["git", "status", "--porcelain"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=3, stdout="", stderr="authentication_error: missing key")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = OpenHandsWorker().run(repo_path=tmp_path, task="x", timeout_seconds=5)

    assert result.status == "auth_missing"
    assert result.termination_reason == "auth_missing"


def test_timeout_maps_to_timeout_status(tmp_path: Path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    def fake_run(argv, *args, **kwargs):
        if argv[:2] == ["git", "rev-parse"]:
            return SimpleNamespace(returncode=0, stdout=str(tmp_path), stderr="")
        if argv[:3] == ["git", "status", "--porcelain"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise subprocess.TimeoutExpired(cmd=["openhands"], timeout=1, output="out", stderr="err")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = OpenHandsWorker().run(repo_path=tmp_path, task="x", timeout_seconds=1)

    assert result.status == "timeout"
    assert result.termination_reason == "timeout"
    assert result.stdout == "out"
    assert result.stderr == "err"


def test_worker_writes_artifacts_when_run_dir_is_available(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    run_dir = tmp_path / "runs" / "run-1"

    def fake_run(argv, *args, **kwargs):
        if argv[:2] == ["git", "rev-parse"]:
            return SimpleNamespace(returncode=0, stdout=str(repo), stderr="")
        if argv[:3] == ["git", "status", "--porcelain"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        Path(kwargs["env"]["OPENHANDS_EVENTS_PATH"]).write_text(
            '{"event_type":"FakeEvent"}\n',
            encoding="utf-8",
        )
        return SimpleNamespace(
            returncode=0,
            stdout=(
                'OPENHANDS_WORKER_SUMMARY_JSON={"worker_type":"openhands",'
                '"loop_owner":"openhands_sdk","status":"completed","exit_code":0,'
                '"duration_seconds":0.5,"tools_requested":["terminal","file_editor"]}\n'
                "openhands run complete\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = OpenHandsWorker().run(
        repo_path=repo,
        task="x",
        timeout_seconds=5,
        run_dir=run_dir,
        run_id="run-1",
    )

    assert result.status == "completed"
    assert (run_dir / "worker_prompt.md").exists()
    assert (run_dir / "worker_stdout.log").exists()
    assert (run_dir / "worker_stderr.log").exists()
    assert (run_dir / "worker_loop_summary.json").exists()
    assert (run_dir / "worker_result.json").exists()
    assert (run_dir / "worker_scorecard.json").exists()
    assert (run_dir / "openhands_events.jsonl").exists()
    assert (run_dir / "openhands_state").exists()
    assert result.artifact_paths["summary"].endswith("worker_loop_summary.json")
    assert result.artifact_paths["events"].endswith("openhands_events.jsonl")


def test_failed_runner_exit_is_failed(tmp_path: Path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    def fake_run(argv, *args, **kwargs):
        if argv[:2] == ["git", "rev-parse"]:
            return SimpleNamespace(returncode=0, stdout=str(tmp_path), stderr="")
        if argv[:3] == ["git", "status", "--porcelain"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="out", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = OpenHandsWorker().run(repo_path=tmp_path, task="x", timeout_seconds=5)

    assert result.status == "failed"
    assert result.exit_code == 1
    assert result.stdout == "out"
    assert result.stderr == "boom"
