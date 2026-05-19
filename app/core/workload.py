from __future__ import annotations

from pathlib import Path

import yaml

from app.schemas.run import RunRecord
from app.schemas.workload import WorkloadGateResult, WorkloadManifest


def load_workload_manifest(path: Path) -> WorkloadManifest:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = "Workload manifest must be a YAML mapping at the root."
        raise ValueError(msg)
    return WorkloadManifest.model_validate(payload)


def evaluate_workload_gates(record: RunRecord, manifest: WorkloadManifest) -> WorkloadGateResult:
    reasons: list[str] = []
    ok = True
    exp = manifest.expected

    if exp.max_risk_score is not None and record.risk_report.risk_score > exp.max_risk_score:
        ok = False
        reasons.append(
            f"risk_score {record.risk_report.risk_score} exceeds max "
            f"{exp.max_risk_score} declared in workload '{manifest.name}'",
        )

    executed = {cmd.command for cmd in record.test_results.commands}
    for required in exp.required_commands:
        if required not in executed:
            ok = False
            reasons.append(
                f"missing required test command `{required}` (executed: {sorted(executed)!r})",
            )

    return WorkloadGateResult(passed=ok, reasons=reasons)
