from app.agents.permission_gate import PermissionGate
from app.schemas.permission import PermissionReport


def _classify(
    changed_files=None,
    deleted_files=None,
    commands=None,
) -> PermissionReport:
    return PermissionGate().classify(
        changed_files=changed_files or [],
        deleted_files=deleted_files or [],
        commands=commands or [],
    )


def test_benign_change_is_auto():
    report = _classify(changed_files=["app/x.py", "tests/test_x.py"])
    assert report.highest_tier == "auto"
    assert report.blocked is False
    assert report.needs_human is False


def test_secret_file_edit_is_denied():
    report = _classify(changed_files=["config/.env"])
    assert report.blocked is True
    assert report.highest_tier == "deny"
    deny = report.of_tier("deny")
    assert any(".env" in d.action for d in deny)


def test_destructive_command_is_denied():
    report = _classify(commands=["rm -rf build/"])
    assert report.blocked is True
    assert any("rm -rf" in d.reason or "rm -rf" in d.action for d in report.decisions)


def test_sensitive_folder_change_asks_human():
    report = _classify(changed_files=["app/auth/login.py"])
    assert report.needs_human is True
    assert report.blocked is False
    assert report.highest_tier == "ask"


def test_dependency_change_asks_human():
    report = _classify(changed_files=["pyproject.toml"])
    assert report.highest_tier == "ask"


def test_file_deletion_asks_human():
    report = _classify(deleted_files=["app/old_module.py"])
    assert report.highest_tier == "ask"


def test_deny_dominates_ask():
    report = _classify(
        changed_files=["app/auth/login.py", "config/.env"],
        deleted_files=["app/old.py"],
    )
    assert report.highest_tier == "deny"
    assert report.blocked is True


def test_secret_deletion_is_denied_not_merely_asked():
    # Deleting a secret is destructive, not a routine "ask".
    report = _classify(deleted_files=["secrets.yaml"])
    assert report.highest_tier == "deny"


def test_every_decision_records_a_rule_and_reason():
    report = _classify(
        changed_files=["app/auth/login.py", "pyproject.toml"],
        commands=["rm -rf /"],
    )
    assert report.decisions
    assert all(d.rule and d.reason for d in report.decisions)
