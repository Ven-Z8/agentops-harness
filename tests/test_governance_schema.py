from app.schemas.governance import PreDispatchDecision
from app.schemas.permission import PermissionReport
from app.schemas.run import RunRecord


def test_pre_dispatch_decision_defaults():
    d = PreDispatchDecision()
    assert d.blocked is False and d.denied_paths == [] and d.reason == ""


def test_permission_report_has_enforced_reverts():
    assert "enforced_reverts" in PermissionReport.model_fields


def test_run_record_has_attempts_and_converged():
    assert "attempts" in RunRecord.model_fields
    assert "converged" in RunRecord.model_fields
