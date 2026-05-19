from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.edit import ExternalEditResult
from app.schemas.evidence import EvidenceReport
from app.schemas.plan import ImplementationPlan
from app.schemas.quality import ReportQualityReport
from app.schemas.repo import RepoProfile
from app.schemas.report import FinalReport
from app.schemas.review import ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.test import TestRunSummary

RunStatus = Literal["completed", "blocked", "failed"]


class RunRecord(BaseModel):
    run_id: str
    task: str
    repo_path: str
    repo_profile: RepoProfile
    plan: ImplementationPlan
    changed_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    diff_summary: str = ""
    test_results: TestRunSummary
    review_report: ReviewReport
    risk_report: RiskReport
    final_report: FinalReport
    report_quality: ReportQualityReport = Field(default_factory=ReportQualityReport)
    evidence_report: EvidenceReport = Field(default_factory=EvidenceReport)
    edit_result: ExternalEditResult | None = None
    execution_logs: list[str] = Field(default_factory=list)
    token_usage: dict[str, int] = Field(default_factory=dict)
    status: RunStatus
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
