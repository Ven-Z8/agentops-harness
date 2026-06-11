from app.schemas.product_review import ProductFinding, ProductReview


def test_finding_carries_cited_claim_contract():
    finding = ProductFinding(
        lens="goal_alignment",
        verdict="concern",
        observation="Changed files fall outside the planned set.",
        source_of_truth="plan.files_to_edit",
        citation="RunRecord.plan",
        confidence="medium",
        recommendation="Confirm the extra files serve G1.",
    )
    assert finding.lens == "goal_alignment"
    assert finding.citation


def test_review_defaults_suggested_next_to_empty():
    review = ProductReview(overall_verdict="aligned", summary="ok")
    assert review.suggested_next == []
    assert review.findings == []
