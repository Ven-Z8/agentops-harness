from app.core.workers.worker_env import find_worker_bin, worker_env


def test_worker_env_includes_npm_global_on_path():
    path = worker_env()["PATH"]
    assert ".npm-global/bin" in path or "/.bun/bin" in path


def test_find_worker_bin_returns_none_for_missing():
    assert find_worker_bin("definitely-not-a-real-cli-zzz") is None
