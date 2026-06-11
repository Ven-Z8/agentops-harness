from __future__ import annotations

import re

from app.core.llm import LLMClient
from app.schemas.goal_model import Goal, ProductGoalModel
from app.schemas.plan import ImplementationPlan
from app.schemas.product_review import ProductFinding, ProductReview
from app.schemas.test import TestRunSummary

_STOPWORDS = {"the", "a", "an", "is", "to", "and", "of", "for", "with", "added", "add"}


def _planned_files(plan: ImplementationPlan) -> set[str]:
    files: set[str] = set()
    for step in plan.steps:
        files.update(step.files_to_edit)
    return files


def _signal_met(signal: str, haystack: str) -> bool:
    tokens = []
    for raw in signal.lower().replace("/", " ").split():
        token = raw.strip(".,;:#<>()[]\"'")
        if token and token not in _STOPWORDS and len(token) > 2 and any(c.isalnum() for c in token):
            tokens.append(token)
    if not tokens:
        return False
    return all(bool(re.search(r"\b" + re.escape(t) + r"\b", haystack)) for t in tokens)


class ProductReviewer:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client

    def review(
        self,
        *,
        task: str,
        plan: ImplementationPlan,
        changed_files: list[str],
        diff_summary: str,
        changed_subgraph: object | None,
        test_results: TestRunSummary,
        goal_model: ProductGoalModel | None,
        target_goal_id: str | None,
    ) -> ProductReview:
        if goal_model is None:
            return self._not_evaluated()

        # LLM path mirrors other agents. Exceptions propagate so the calling node
        # can record a provider_fallback event (the deterministic path is the net).
        if self.llm_client is not None:
            from app.prompts.product_reviewer import build_product_reviewer_prompt

            return self.llm_client.generate_structured(
                build_product_reviewer_prompt(
                    task=task, plan=plan, changed_files=changed_files,
                    diff_summary=diff_summary, goal_model=goal_model,
                    target_goal_id=target_goal_id,
                ),
                ProductReview,
            )

        return self._deterministic(
            plan=plan, changed_files=changed_files, diff_summary=diff_summary,
            test_results=test_results, goal_model=goal_model, target_goal_id=target_goal_id,
        )

    def _not_evaluated(self) -> ProductReview:
        findings = [
            ProductFinding(
                lens=lens, verdict="not_evaluated",
                observation="No intent graph found; product intent not evaluated.",
                source_of_truth="goal_model", citation="no agentops.goals.yaml",
                confidence="high",
                recommendation="Author agentops.goals.yaml to enable product review.",
            )
            for lens in ("goal_alignment", "completeness", "value", "prioritization")
        ]
        return ProductReview(
            overall_verdict="not_evaluated",
            per_lens={f.lens: "not_evaluated" for f in findings},
            findings=findings,
            summary="Product review skipped: no intent graph (agentops.goals.yaml).",
        )

    def _deterministic(
        self, *, plan: ImplementationPlan, changed_files: list[str], diff_summary: str,
        test_results: TestRunSummary, goal_model: ProductGoalModel, target_goal_id: str | None,
    ) -> ProductReview:
        goal = goal_model.goal(target_goal_id) if target_goal_id else None
        gid = goal.id if goal else "model"
        planned = _planned_files(plan)
        outside = [f for f in changed_files if planned and f not in planned]
        lowered_paths = " ".join(changed_files).lower()
        findings: list[ProductFinding] = []

        # goal_alignment
        scope_terms = list(goal.scope_out) if goal else []
        scope_terms += goal_model.not_this
        hit = next(
            (
                t for t in scope_terms
                if t.strip()
                and re.search(r"\b" + re.escape(t.lower()) + r"\b", lowered_paths)
            ),
            None,
        )
        if hit:
            align = ProductFinding(
                lens="goal_alignment", verdict="fail",
                observation=f"Change touches excluded area: '{hit}'.",
                source_of_truth=f"goal_model.{gid}.scope_out",
                citation=f"agentops.goals.yaml#{gid}", confidence="medium",
                recommendation="Stop and confirm this is intended product scope.",
            )
        elif outside:
            align = ProductFinding(
                lens="goal_alignment", verdict="concern",
                observation=f"{len(outside)} changed file(s) outside the planned set.",
                source_of_truth="plan.files_to_edit", citation="RunRecord.plan",
                confidence="low", recommendation="Confirm the extra files serve the goal.",
            )
        else:
            align = ProductFinding(
                lens="goal_alignment", verdict="pass",
                observation="Changes stay within the planned files.",
                source_of_truth="plan.files_to_edit", citation="RunRecord.plan",
                confidence="medium", recommendation="",
            )
        findings.append(align)

        # completeness
        haystack = (lowered_paths + " " + diff_summary.lower() + " " +
                    " ".join(c.command for c in test_results.commands).lower())
        signals = (
            goal.success_when if goal
            else [s for g in goal_model.goals for s in g.success_when]
        )
        unmet = [s for s in signals if not _signal_met(s, haystack)]
        complete = ProductFinding(
            lens="completeness",
            verdict="pass" if (not unmet and test_results.passed) else "concern",
            observation=f"{len(signals) - len(unmet)} of {len(signals)} success signals met"
            + ("; validation failed." if not test_results.passed else "."),
            source_of_truth=f"goal_model.{gid}.success_when",
            citation=f"agentops.goals.yaml#{gid}", confidence="low",
            recommendation="Address unmet success signals before marking done."
            if unmet else "",
        )
        findings.append(complete)

        # value (overbuilt)
        value = ProductFinding(
            lens="value",
            verdict="concern" if (planned and len(outside) > len(planned)) else "pass",
            observation="Diff scope exceeds the planned scope."
            if (planned and len(outside) > len(planned)) else "Diff scope matches the plan.",
            source_of_truth="plan.files_to_edit", citation="RunRecord.plan",
            confidence="low",
            recommendation="Trim gold-plating not tied to a success signal."
            if (planned and len(outside) > len(planned)) else "",
        )
        findings.append(value)

        # prioritization
        findings.append(self._prioritization(goal, goal_model, gid))

        return ProductReview(
            overall_verdict=self._overall(findings),
            per_lens={f.lens: f.verdict for f in findings},
            findings=findings,
            summary=self._summary(findings),
        )

    def _prioritization(
        self, goal: Goal | None, goal_model: ProductGoalModel, gid: str
    ) -> ProductFinding:
        if goal is None:
            return ProductFinding(
                lens="prioritization", verdict="not_evaluated",
                observation="No target goal supplied (--goal); priority not evaluated.",
                source_of_truth="goal_model", citation="RunRecord.target_goal_id",
                confidence="high", recommendation="Pass --goal <id> to ground prioritization.",
            )
        now_open = any(g.priority == "now" and g.id != goal.id for g in goal_model.goals)
        if goal.priority != "now" and now_open:
            return ProductFinding(
                lens="prioritization", verdict="concern",
                observation=f"Working {goal.priority}-priority {goal.id} while now-goals are open.",
                source_of_truth=f"goal_model.{gid}.priority",
                citation=f"agentops.goals.yaml#{gid}", confidence="medium",
                recommendation="Confirm this is the right thing to build now.",
            )
        return ProductFinding(
            lens="prioritization", verdict="pass",
            observation=f"{goal.id} is a {goal.priority}-priority goal.",
            source_of_truth=f"goal_model.{gid}.priority",
            citation=f"agentops.goals.yaml#{gid}", confidence="medium", recommendation="",
        )

    def _overall(self, findings: list[ProductFinding]) -> str:
        by = {f.lens: f.verdict for f in findings}
        if by.get("goal_alignment") == "fail":
            return "drifted"
        if by.get("completeness") == "concern":
            return "incomplete"
        if by.get("value") == "concern":
            return "overbuilt"
        all_pass = all(
            by.get(lens) in {"pass"}
            for lens in ("goal_alignment", "completeness", "value")
        )
        if all_pass:
            return "aligned"
        return "unclear"

    def _summary(self, findings: list[ProductFinding]) -> str:
        return "; ".join(f"{f.lens}: {f.verdict}" for f in findings)

    def append_to_report(self, final_report, review: ProductReview):
        from app.schemas.report import FinalReport

        lines = ["", "", "## Product Review", "",
                 f"Overall verdict: **{review.overall_verdict}**", ""]
        for f in review.findings:
            lines.append(
                f"- **{f.lens}** — {f.verdict}: {f.observation} "
                f"(source: {f.source_of_truth}; cite: {f.citation})"
            )
        markdown = final_report.markdown.rstrip() + "\n".join(lines) + "\n"
        return FinalReport(title=final_report.title, markdown=markdown)
