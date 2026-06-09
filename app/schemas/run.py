from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.repo_graph.impact import ChangedSubgraph
from app.core.repo_graph.models import RepoGraph
from app.schemas.conflict import ConflictReport
from app.schemas.edit import ExternalEditResult
from app.schemas.evidence import EvidenceReport
from app.schemas.memory import MemoryReport
from app.schemas.permission import PermissionReport
from app.schemas.plan import ImplementationPlan
from app.schemas.quality import ReportQualityReport
from app.schemas.repo import RepoProfile
from app.schemas.report import FinalReport
from app.schemas.review import ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.test import TestRunSummary
from app.schemas.verification import VerificationBundle

RunStatus = Literal["completed", "blocked", "failed"]


class RunRecord(BaseModel):
    run_id: str
    task: str
    repo_path: str
    repo_profile: RepoProfile
    repo_graph: RepoGraph | None = None
    memory_report: MemoryReport = Field(default_factory=MemoryReport)
    plan: ImplementationPlan
    changed_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    diff_summary: str = ""
    changed_subgraph: ChangedSubgraph = Field(default_factory=ChangedSubgraph)
    test_results: TestRunSummary
    review_report: ReviewReport
    risk_report: RiskReport
    permission_report: PermissionReport = Field(default_factory=PermissionReport)
    final_report: FinalReport
    report_quality: ReportQualityReport = Field(default_factory=ReportQualityReport)
    evidence_report: EvidenceReport = Field(default_factory=EvidenceReport)
    verification_bundle: VerificationBundle = Field(default_factory=VerificationBundle)
    conflict_report: ConflictReport = Field(default_factory=ConflictReport)
    edit_result: ExternalEditResult | None = None
    execution_logs: list[str] = Field(default_factory=list)
    token_usage: dict[str, int] = Field(default_factory=dict)
    status: RunStatus
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
