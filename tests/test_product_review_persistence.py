import json
from pathlib import Path

from app.core.run_artifacts import RunArtifactWriter
from app.schemas.run import RunRecord


def test_run_record_has_product_review_default():
    fields = RunRecord.model_fields
    assert "product_review" in fields


def test_artifact_writer_writes_product_review_json(tmp_path: Path, monkeypatch):
    # Build a minimal record via the existing test helper pattern is heavy; assert the
    # writer emits product_review.json when given a record that has the field.
    from app.schemas.product_review import ProductReview
    record = _minimal_run_record()
    record.product_review = ProductReview(overall_verdict="aligned", summary="ok")
    artifact_dir = RunArtifactWriter().write(record, tmp_path / "runs.db")
    payload = json.loads((artifact_dir / "product_review.json").read_text())
    assert payload["overall_verdict"] == "aligned"


def _minimal_run_record() -> RunRecord:
    # Reuse the project's existing minimal-record factory if present; otherwise import
    # from an existing test helper. Implemented inline here against current RunRecord.
    from tests.helpers_runrecord import minimal_run_record  # see Step 3
    return minimal_run_record()
