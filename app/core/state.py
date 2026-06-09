from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from app.core.llm import LLMClient
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
    memory_report: MemoryReport
    plan: ImplementationPlan
    edit_result: ExternalEditResult | None
    changed_files: list[str]
    deleted_files: list[str]
    diff_summary: str
    test_results: TestRunSummary
    review_report: ReviewReport
    risk_report: RiskReport
    permission_report: PermissionReport
    final_report: FinalReport
    report_quality: ReportQualityReport
    evidence_report: EvidenceReport
    verification_bundle: VerificationBundle
    conflict_report: ConflictReport
    execution_logs: list[str]
    repo_graph: RepoGraph
    changed_subgraph: ChangedSubgraph
