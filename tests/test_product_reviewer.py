from app.agents.product_reviewer import ProductReviewer
from app.schemas.goal_model import Goal, ProductGoalModel
from app.schemas.plan import ImplementationPlan, PlanStep
from app.schemas.test import CommandResult, TestRunSummary


def model() -> ProductGoalModel:
    return ProductGoalModel(
        north_star="Local control harness.",
        not_this=["hosted saas"],
        goals=[
            Goal(
                id="G1",
                statement="Ground worker runs.",
                priority="now",
                success_when=["healthz endpoint added", "test added"],
                scope_out=["billing"],
            ),
            Goal(id="G2", statement="Later thing.", priority="later", success_when=["x"]),
        ],
    )


def plan(files_to_edit: list[str]) -> ImplementationPlan:
    return ImplementationPlan(
        task="t",
        summary="s",
        steps=[PlanStep(id=1, title="x", description="d", files_to_edit=files_to_edit)],
        acceptance_criteria=["ok"],
        tests_to_run=["python -m pytest -q"],
    )


def make_test_results(passed: bool) -> TestRunSummary:
    return TestRunSummary(
        commands=[CommandResult(command="python -m pytest -q", exit_code=0 if passed else 1,
                                duration_seconds=0.1, stdout="", stderr="")]
    )


def test_no_goal_model_returns_not_evaluated():
    review = ProductReviewer().review(
        task="t", plan=plan(["app/main.py"]), changed_files=["app/main.py"],
        diff_summary="", changed_subgraph=None, test_results=make_test_results(True),
        goal_model=None, target_goal_id=None,
    )
    assert review.overall_verdict == "not_evaluated"
    assert all(f.verdict == "not_evaluated" for f in review.findings)
    assert all(f.citation for f in review.findings)


def test_scope_out_touch_flags_drift():
    review = ProductReviewer().review(
        task="add billing hook", plan=plan(["app/billing.py"]),
        changed_files=["app/billing.py"], diff_summary="", changed_subgraph=None,
        test_results=make_test_results(True), goal_model=model(), target_goal_id="G1",
    )
    assert review.overall_verdict == "drifted"
    assert any(f.lens == "goal_alignment" and f.verdict == "fail" for f in review.findings)


def test_unmet_success_signal_flags_incomplete():
    review = ProductReviewer().review(
        task="add healthz", plan=plan(["app/main.py"]), changed_files=["app/main.py"],
        diff_summary="added healthz endpoint", changed_subgraph=None,
        test_results=make_test_results(True), goal_model=model(), target_goal_id="G1",
    )
    # "test added" signal is unmet (no tests/ file changed) -> completeness concern
    assert any(f.lens == "completeness" and f.verdict == "concern" for f in review.findings)
    assert review.overall_verdict in {"incomplete", "drifted", "overbuilt", "unclear"}


def test_every_finding_is_cited():
    review = ProductReviewer().review(
        task="t", plan=plan(["app/main.py"]), changed_files=["app/main.py", "tests/test_x.py"],
        diff_summary="healthz endpoint added; test added", changed_subgraph=None,
        test_results=make_test_results(True), goal_model=model(), target_goal_id="G1",
    )
    assert review.findings
    assert all(f.citation for f in review.findings)


def test_later_goal_while_now_open_flags_prioritization():
    review = ProductReviewer().review(
        task="t", plan=plan(["app/main.py"]), changed_files=["app/main.py"],
        diff_summary="x", changed_subgraph=None, test_results=make_test_results(True),
        goal_model=model(), target_goal_id="G2",
    )
    assert any(f.lens == "prioritization" and f.verdict == "concern" for f in review.findings)


def test_completeness_credits_signals_found_only_in_diff_body():
    # The signals ("healthz endpoint added", "test added") are absent from the file
    # paths and the --stat summary; they appear only in the diff body. The reviewer
    # must read the body, otherwise it false-negatives on real work (the gap a real
    # codex run exposed on contextiq).
    diff_body = (
        "+@app.get('/healthz')\n+def healthz():\n+    return {'status': 'ok'}\n"
        "+def test_api_healthz_readiness():\n+    assert resp.status_code == 200\n"
    )
    review = ProductReviewer().review(
        task="add healthz",
        plan=plan(["src/main.py", "tests/test_api.py"]),
        changed_files=["src/main.py", "tests/test_api.py"],
        diff_summary="2 files changed, 13 insertions(+)",
        diff_body=diff_body,
        changed_subgraph=None,
        test_results=make_test_results(True),
        goal_model=model(),
        target_goal_id="G1",
    )
    completeness = next(f for f in review.findings if f.lens == "completeness")
    assert completeness.verdict == "pass", completeness.observation


def test_llm_path_includes_diff_body_in_prompt():
    """With a provider configured, the LLM Product Reviewer must see the actual diff body.

    Regression for the blocker: completeness was graded from changed_files + diff_summary
    only — the diff body never reached the prompt, so a half-finished migration could be
    judged 'done' from file names alone (the Cockpit then shows green on a half-done repo).
    """
    from app.schemas.product_review import ProductReview

    captured: dict[str, str] = {}

    class CapturingClient:
        def generate_structured(self, prompt: str, schema):
            captured["prompt"] = prompt
            return ProductReview()

    diff_body = (
        "+SENTINEL_DIFF_MARKER_4242\n"
        "+@app.get('/healthz')\n+def healthz():\n+    return {'status': 'ok'}\n"
    )
    ProductReviewer(llm_client=CapturingClient()).review(
        task="add healthz",
        plan=plan(["src/main.py"]),
        changed_files=["src/main.py"],
        diff_summary="1 file changed",
        diff_body=diff_body,
        changed_subgraph=None,
        test_results=make_test_results(True),
        goal_model=model(),
        target_goal_id="G1",
    )
    assert "prompt" in captured, "LLM client was not called"
    assert "SENTINEL_DIFF_MARKER_4242" in captured["prompt"], (
        "the diff body did not reach the Product Reviewer prompt"
    )
