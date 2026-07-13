from __future__ import annotations

import re

from app.core.repo_graph.impact import ChangedSubgraph
from app.schemas.evidence import EvidenceFinding, EvidenceReport
from app.schemas.report import FinalReport
from app.schemas.risk import RiskReport
from app.schemas.test import TestRunSummary


class EvidenceGuard:
    FILE_CLAIM_PATTERN = re.compile(r"`([^`]+\.[A-Za-z0-9_]+)`")
    CHANGE_WORDS = (
        "add",
        "added",
        "adds",
        "modify",
        "modified",
        "change",
        "changed",
        "create",
        "created",
        "implement",
        "implemented",
    )
    TEST_CLAIM_PATTERNS = (
        "tests were added",
        "test was added",
        "added tests",
        "new tests",
        "comprehensive tests",
        "tests changed",
        "test changed",
    )
    TEST_CHANGE_VERB = re.compile(
        r"\b(?:added|created|updated|modified|changed)\b"
    )
    TEST_SUBJECT_CHANGE = re.compile(
        r"\b(?:new\s+)?tests?(?:\s+files?)?\s+(?:were|was|are|is)\s+"
        r"(?:added|created|updated|modified|changed)\b"
    )
    TEST_OBJECT_TOKEN = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
    TEST_OBJECT_MAX_TOKENS = 8
    TEST_CLAUSE_STARTERS = frozenset({"and", "but", "so", "then", "yet"})
    TEST_OBJECT_BARRIERS = frozenset(
        {
            "about",
            "checked",
            "confirm",
            "confirmed",
            "execute",
            "executed",
            "for",
            "no",
            "not",
            "pass",
            "passed",
            "passes",
            "ran",
            "run",
            "that",
            "to",
            "use",
            "used",
            "using",
            "verify",
            "verified",
            "verifies",
            "via",
            "which",
            "with",
            "without",
        }
    )
    NEGATED_TEST_CHANGE = re.compile(
        r"\b(?:"
        r"no\s+(?:(?:additional|new)\s+){0,2}tests?(?:\s+files?)?\s+"
        r"(?:were\s+|was\s+)?"
        r"(?:added|updated|modified|changed|created)"
        r"|tests?(?:\s+files?)?\s+(?:were|was)\s+not\s+"
        r"(?:added|updated|modified|changed|created)"
        r")\b"
    )
    ROUTE_CLAIM_PATTERN = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|ANY)\s+(/[A-Za-z0-9_./{}-]*)")
    VALIDATION_RECOMMENDATION_WORDS = (
        "recommended targeted validation",
        "recommended validation",
        "should run",
    )

    def check(
        self,
        final_report: FinalReport,
        changed_files: list[str],
        test_results: TestRunSummary,
        risk_report: RiskReport | None = None,
        changed_subgraph: ChangedSubgraph | None = None,
    ) -> EvidenceReport:
        markdown = final_report.markdown
        findings: list[EvidenceFinding] = []
        changed_file_set = set(changed_files)

        findings.extend(self._check_file_claims(markdown, changed_file_set))
        findings.extend(self._check_new_test_claims(markdown, changed_file_set))
        findings.extend(self._check_analysis_only(markdown, changed_files))
        findings.extend(self._check_test_pass_claims(markdown, test_results))
        findings.extend(self._check_lint_claims(markdown, test_results))
        findings.extend(self._check_risk_claims(markdown, risk_report))
        findings.extend(self._check_route_claims(markdown, changed_subgraph))
        findings.extend(
            self._check_validation_execution_claims(
                markdown,
                test_results,
                changed_subgraph,
            )
        )
        findings = self._dedupe_findings(findings)

        return EvidenceReport(
            grounded=not findings,
            unsupported_claim_count=len(findings),
            findings=findings,
        )

    def append_to_report(
        self,
        final_report: FinalReport,
        evidence_report: EvidenceReport,
    ) -> FinalReport:
        if evidence_report.grounded:
            return final_report

        findings = "\n".join(
            (
                f"- **Unsupported claim** `{finding.claim}`: "
                f"{finding.reason} "
                f"Source: {finding.source_of_truth}. "
                f"Observed: {finding.observed or finding.evidence}."
            )
            for finding in evidence_report.findings
        )
        markdown = f"""{final_report.markdown.rstrip()}

## Evidence Guard

This report contains claims that are not supported by the run record.

{findings}
"""
        return FinalReport(title=final_report.title, markdown=markdown)

    def _check_file_claims(
        self,
        markdown: str,
        changed_file_set: set[str],
    ) -> list[EvidenceFinding]:
        findings: list[EvidenceFinding] = []
        for line in markdown.splitlines():
            if not self._looks_like_change_claim(line):
                continue
            for file_path in self.FILE_CLAIM_PATTERN.findall(line):
                if file_path not in changed_file_set:
                    findings.append(
                        EvidenceFinding(
                            severity="error",
                            claim=file_path,
                            reason=(
                                "Report claims a file was changed, but git evidence "
                                "does not include it."
                            ),
                            evidence=f"changed_files={sorted(changed_file_set)}",
                            claim_type="file_changed_without_diff",
                            source_of_truth="changed_files",
                            expected=file_path,
                            observed=str(sorted(changed_file_set)),
                            citation="RunRecord.changed_files",
                        )
                    )
        return findings

    def _check_new_test_claims(
        self,
        markdown: str,
        changed_file_set: set[str],
    ) -> list[EvidenceFinding]:
        has_test_claim = False
        for line in markdown.lower().splitlines():
            claim_text = self.NEGATED_TEST_CHANGE.sub("", line)
            if any(pattern in claim_text for pattern in self.TEST_CLAIM_PATTERNS):
                has_test_claim = True
                break
            if self.TEST_SUBJECT_CHANGE.search(claim_text) is not None:
                has_test_claim = True
                break
            if self._claims_test_object(claim_text):
                has_test_claim = True
                break
        has_changed_tests = any(path.startswith("tests/") for path in changed_file_set)
        if has_test_claim and not has_changed_tests:
            return [
                EvidenceFinding(
                    severity="error",
                    claim="new tests added",
                    reason="Report claims tests were added, but no changed test file is present.",
                    evidence=f"changed_files={sorted(changed_file_set)}",
                    claim_type="tests_added_without_test_diff",
                    source_of_truth="changed_files",
                    expected="at least one tests/ file",
                    observed=str(sorted(changed_file_set)),
                    citation="RunRecord.changed_files",
                )
            ]
        return []

    @classmethod
    def _claims_test_object(cls, text: str) -> bool:
        """Detect when a change verb's direct object is a bounded test noun phrase."""
        for verb in cls.TEST_CHANGE_VERB.finditer(text):
            if re.search(r"\b(?:never|not)\s*$", text[: verb.start()]):
                continue
            clause = re.split(r"[.;:\n]", text[verb.end() :], maxsplit=1)[0]
            tokens = cls.TEST_OBJECT_TOKEN.findall(clause.lower())
            if not tokens or tokens[0] in cls.TEST_CLAUSE_STARTERS:
                continue
            for index, token in enumerate(tokens):
                if index > cls.TEST_OBJECT_MAX_TOKENS:
                    break
                if token in {"test", "tests"}:
                    return True
                if token in cls.TEST_OBJECT_BARRIERS:
                    break
        return False

    LINT_EXECUTION_WORDS = (
        "passed",
        "pass",
        "ran",
        "executed",
        "completed",
        "clean",
        "no errors",
        "succeeded",
        "verified",
    )
    LINT_RECOMMENDATION_WORDS = (
        "recommended",
        "should run",
        "not executed",
        "planned",
        "follow-up",
        "to run",
    )

    def _check_lint_claims(
        self,
        markdown: str,
        test_results: TestRunSummary,
    ) -> list[EvidenceFinding]:
        claims_lint = any(
            self._line_claims_lint_executed(line) for line in markdown.splitlines()
        )
        executed = {result.command for result in test_results.commands}
        ran_lint = any("ruff" in command or "lint" in command for command in executed)
        if claims_lint and not ran_lint:
            return [
                EvidenceFinding(
                    severity="error",
                    claim="linting passed",
                    reason=(
                        "Report claims lint/static validation ran, but no lint command executed."
                    ),
                    evidence=f"executed_commands={sorted(executed)}",
                    claim_type="lint_claim_without_execution",
                    source_of_truth="test_results.commands",
                    expected="a ruff/lint command in executed validation",
                    observed=str(sorted(executed)),
                    citation="RunRecord.test_results.commands",
                )
            ]
        return []

    def _check_analysis_only(
        self,
        markdown: str,
        changed_files: list[str],
    ) -> list[EvidenceFinding]:
        lowered = markdown.lower()
        if changed_files:
            return []
        if any(word in lowered for word in ("added `", "modified `", "created `")):
            return []
        if "analysis-only" in lowered or "no files changed" in lowered:
            return []
        return [
            EvidenceFinding(
                severity="warning",
                claim="implementation report without changed files",
                reason=(
                    "Run has no changed files, so report should clearly state "
                    "it is analysis-only."
                ),
                evidence="changed_files=[]",
                claim_type="implementation_claim_without_diff",
                source_of_truth="changed_files",
                expected="analysis-only wording or changed files",
                observed="[]",
                citation="RunRecord.changed_files",
            )
        ]

    def _check_test_pass_claims(
        self,
        markdown: str,
        test_results: TestRunSummary,
    ) -> list[EvidenceFinding]:
        lowered = markdown.lower()
        claims_pass = "all tests pass" in lowered or "tests pass" in lowered
        if claims_pass and not test_results.passed:
            return [
                EvidenceFinding(
                    severity="error",
                    claim="tests pass",
                    reason="Report claims tests pass, but validation commands failed.",
                    evidence="test_results.passed=False",
                    claim_type="tests_pass_claim_but_failed",
                    source_of_truth="test_results",
                    expected="all command exit codes are 0",
                    observed="test_results.passed=False",
                    citation="RunRecord.test_results.commands",
                )
            ]
        return []

    def _check_risk_claims(
        self,
        markdown: str,
        risk_report: RiskReport | None,
    ) -> list[EvidenceFinding]:
        if risk_report is None:
            return []
        lowered = markdown.lower()
        claims_low_risk = any(
            phrase in lowered
            for phrase in (
                "no risk",
                "low risk",
                "minimal risk",
                "risk level: low",
                "level: low",
            )
        )
        if claims_low_risk and risk_report.risk_level in {"medium", "high", "critical"}:
            return [
                EvidenceFinding(
                    severity="error",
                    claim="low risk",
                    reason="Report claims low/no risk, but risk report is elevated.",
                    evidence=f"risk_level={risk_report.risk_level}",
                    claim_type="risk_level_understated",
                    source_of_truth="risk_report",
                    expected="low risk claim only when risk_report.risk_level is low",
                    observed=f"risk_level={risk_report.risk_level}",
                    citation="RunRecord.risk_report.risk_level",
                )
            ]
        return []

    def _check_route_claims(
        self,
        markdown: str,
        changed_subgraph: ChangedSubgraph | None,
    ) -> list[EvidenceFinding]:
        if changed_subgraph is None:
            return []
        impacted = {
            (route.method.upper(), route.path)
            for route in changed_subgraph.impacted_routes
        }
        findings: list[EvidenceFinding] = []
        for method, path in self.ROUTE_CLAIM_PATTERN.findall(markdown):
            route = (method.upper(), path)
            if route not in impacted:
                findings.append(
                    EvidenceFinding(
                        severity="warning",
                        claim=f"{method.upper()} {path}",
                        reason=(
                            "Report claims route/API impact, but changed subgraph "
                            "does not include that route."
                        ),
                        evidence=f"impacted_routes={sorted(impacted)}",
                        claim_type="route_claim_without_graph_impact",
                        source_of_truth="changed_subgraph.impacted_routes",
                        expected=f"{method.upper()} {path}",
                        observed=str(sorted(impacted)),
                        citation="RunRecord.changed_subgraph.impacted_routes",
                    )
                )
        return findings

    def _check_validation_execution_claims(
        self,
        markdown: str,
        test_results: TestRunSummary,
        changed_subgraph: ChangedSubgraph | None,
    ) -> list[EvidenceFinding]:
        if changed_subgraph is None:
            return []
        executed = {result.command for result in test_results.commands}
        recommended = {item.command for item in changed_subgraph.recommended_validation}
        if not recommended:
            return []
        lowered = markdown.lower()
        if any(word in lowered for word in self.VALIDATION_RECOMMENDATION_WORDS):
            return []
        claimed_as_run = recommended.intersection(
            command for command in recommended if command.lower() in lowered
        )
        unsupported = sorted(claimed_as_run - executed)
        if not unsupported:
            return []
        return [
            EvidenceFinding(
                severity="error",
                claim=command,
                reason="Report presents recommended validation as executed.",
                evidence=f"executed_commands={sorted(executed)}",
                claim_type="recommended_validation_claimed_as_executed",
                source_of_truth="test_results.commands",
                expected="command appears in executed validation",
                observed=str(sorted(executed)),
                citation="RunRecord.test_results.commands",
            )
            for command in unsupported
        ]

    def _line_claims_lint_executed(self, line: str) -> bool:
        lowered = line.lower()
        if "ruff" not in lowered and "lint" not in lowered:
            return False
        if any(word in lowered for word in self.LINT_RECOMMENDATION_WORDS):
            return False
        return any(word in lowered for word in self.LINT_EXECUTION_WORDS)

    def _looks_like_change_claim(self, line: str) -> bool:
        lowered = line.lower()
        if "external worker" in lowered or "executed the change" in lowered:
            return False
        return any(word in lowered for word in self.CHANGE_WORDS)

    def _dedupe_findings(self, findings: list[EvidenceFinding]) -> list[EvidenceFinding]:
        seen: set[tuple[str, str, str]] = set()
        deduped: list[EvidenceFinding] = []
        for finding in findings:
            key = (finding.claim_type, finding.claim, finding.source_of_truth)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(finding)
        return deduped
