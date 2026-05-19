from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from app.core.llm import LLMClient
from app.schemas.edit import ExternalEditResult
from app.schemas.evidence import EvidenceReport
from app.schemas.plan import ImplementationPlan
from app.schemas.quality import ReportQualityReport
from app.schemas.repo import RepoProfile
from app.schemas.report import FinalReport
from app.schemas.review import ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.test import TestRunSummary


class AgentOpsGraphState(TypedDict, total=False):
    run_id: str
    task: str
    repo_path: Path
    storage_path: Path
    test_commands: list[str] | None
    llm_client: LLMClient | None
    worker_command: str | None
    worker_type: str | None
    worker_timeout_seconds: int
    allow_dirty: bool
    repo_profile: RepoProfile
    plan: ImplementationPlan
    edit_result: ExternalEditResult | None
    changed_files: list[str]
    deleted_files: list[str]
    diff_summary: str
    test_results: TestRunSummary
    review_report: ReviewReport
    risk_report: RiskReport
    final_report: FinalReport
    report_quality: ReportQualityReport
    evidence_report: EvidenceReport
    execution_logs: list[str]
