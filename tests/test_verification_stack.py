from app.agents.verification_stack import VerificationStack
from app.schemas.evidence import EvidenceFinding, EvidenceReport
from app.schemas.report import FinalReport
from app.schemas.review import ReviewFinding, ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.test import CommandResult, TestRunSummary


def _passing_tests() -> TestRunSummary:
    return TestRunSummary(
        commands=[CommandResult(command="pytest", exit_code=0, duration_seconds=0.1)]
    )


def _clean_review() -> ReviewReport:
    return ReviewReport(findings=[], summary="No issues found.")


def _low_risk() -> RiskReport:
    return RiskReport(risk_score=5, risk_level="low", factors=[], blocked=False)


def _grounded_evidence() -> EvidenceReport:
    return EvidenceReport(grounded=True, unsupported_claim_count=0, findings=[])


def test_bundle_has_one_scope_per_verifier():
    bundle = VerificationStack().assemble(
        changed_files=["app/x.py", "tests/test_x.py"],
        test_results=_passing_tests(),
        review_report=_clean_review(),
        risk_report=_low_risk(),
        evidence_report=_grounded_evidence(),
    )
    names = {c.name for c in bundle.checks}
    assert names == {"tests", "code_review", "risk_guard", "evidence_guard"}
    # Each scope must declare what it cannot verify (the paper's key requirement).
    assert all(c.cannot_verify for c in bundle.checks)


def test_all_green_run_is_accepted():
    bundle = VerificationStack().assemble(
        changed_files=["app/x.py", "tests/test_x.py"],
        test_results=_passing_tests(),
        review_report=_clean_review(),
        risk_report=_low_risk(),
        evidence_report=_grounded_evidence(),
    )
    assert bundle.accepted is True


def test_failed_tests_make_bundle_not_accepted():
    failing = TestRunSummary(
        commands=[CommandResult(command="pytest", exit_code=1, duration_seconds=0.1)]
    )
    bundle = VerificationStack().assemble(
        changed_files=["app/x.py"],
        test_results=failing,
        review_report=_clean_review(),
        risk_report=_low_risk(),
        evidence_report=_grounded_evidence(),
    )
    tests_scope = next(c for c in bundle.checks if c.name == "tests")
    assert tests_scope.verdict == "fail"
    assert bundle.accepted is False


def test_no_test_commands_flags_untested_region_and_not_run():
    bundle = VerificationStack().assemble(
        changed_files=["app/x.py"],
        test_results=TestRunSummary(commands=[]),
        review_report=_clean_review(),
        risk_report=_low_risk(),
        evidence_report=_grounded_evidence(),
    )
    tests_scope = next(c for c in bundle.checks if c.name == "tests")
    assert tests_scope.verdict == "not_run"
    assert bundle.untested_regions  # something must be flagged as untested


def test_production_code_changed_without_tests_is_untested_region():
    bundle = VerificationStack().assemble(
        changed_files=["app/x.py"],  # no tests/ file changed
        test_results=_passing_tests(),
        review_report=_clean_review(),
        risk_report=_low_risk(),
        evidence_report=_grounded_evidence(),
    )
    assert any("app/x.py" in region for region in bundle.untested_regions)


def test_remaining_risks_aggregate_risk_factors_and_findings():
    risky = RiskReport(
        risk_score=80,
        risk_level="high",
        factors=["deletes 3 files"],
        blocked=True,
    )
    review = ReviewReport(
        findings=[
            ReviewFinding(
                severity="high",
                title="SQL injection",
                description="raw string interpolation",
                recommendation="use parameters",
            )
        ],
        summary="One high issue.",
    )
    evidence = EvidenceReport(
        grounded=False,
        unsupported_claim_count=1,
        findings=[
            EvidenceFinding(
                severity="error",
                claim="tests pass",
                reason="tests did not pass",
                evidence="test_results.passed=False",
            )
        ],
    )
    bundle = VerificationStack().assemble(
        changed_files=["app/x.py"],
        test_results=_passing_tests(),
        review_report=review,
        risk_report=risky,
        evidence_report=evidence,
    )
    joined = " ".join(bundle.remaining_risks).lower()
    assert "deletes 3 files" in joined
    assert "sql injection" in joined
    assert "tests pass" in joined


def test_benign_no_risk_sentinel_is_not_a_remaining_risk():
    bundle = VerificationStack().assemble(
        changed_files=["app/x.py", "tests/test_x.py"],
        test_results=_passing_tests(),
        review_report=_clean_review(),
        risk_report=RiskReport(
            risk_score=0,
            risk_level="low",
            factors=["No material risk factors detected"],
            blocked=False,
        ),
        evidence_report=_grounded_evidence(),
    )
    assert bundle.remaining_risks == []


def test_overall_confidence_is_weakest_running_signal():
    # tests (high) + review (medium) + risk (medium) + evidence (high) -> medium
    bundle = VerificationStack().assemble(
        changed_files=["app/x.py", "tests/test_x.py"],
        test_results=_passing_tests(),
        review_report=_clean_review(),
        risk_report=_low_risk(),
        evidence_report=_grounded_evidence(),
    )
    assert bundle.overall_confidence == "medium"


def test_render_markdown_section():
    bundle = VerificationStack().assemble(
        changed_files=["app/x.py", "tests/test_x.py"],
        test_results=_passing_tests(),
        review_report=_clean_review(),
        risk_report=_low_risk(),
        evidence_report=_grounded_evidence(),
    )
    report = VerificationStack().append_to_report(
        FinalReport(title="t", markdown="# Body"),
        bundle,
    )
    assert "Verification Stack" in report.markdown
    assert "Cannot verify" in report.markdown
    assert "# Body" in report.markdown
