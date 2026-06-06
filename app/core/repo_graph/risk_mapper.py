from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GraphRisk:
    name: str
    severity: str
    reason: str


class RiskMapper:
    RISK_DEFINITIONS = {
        "spring_boot_2_detected": GraphRisk(
            name="spring_boot_2_detected",
            severity="medium",
            reason="Spring Boot 2 projects need version-aware migration checks before Boot 3 work.",
        ),
        "java_version_below_17": GraphRisk(
            name="java_version_below_17",
            severity="high",
            reason="Spring Boot 3 requires Java 17 or newer.",
        ),
        "javax_dependency_detected": GraphRisk(
            name="javax_dependency_detected",
            severity="high",
            reason="Spring Boot 3 migrations usually require Jakarta dependency changes.",
        ),
        "javax_to_jakarta_required": GraphRisk(
            name="javax_to_jakarta_required",
            severity="high",
            reason="Spring Boot 3 requires Jakarta namespace migration for javax APIs.",
        ),
        "web_security_configurer_adapter_removed": GraphRisk(
            name="web_security_configurer_adapter_removed",
            severity="high",
            reason="WebSecurityConfigurerAdapter was removed in newer Spring Security versions.",
        ),
        "sensitive_file": GraphRisk(
            name="sensitive_file",
            severity="high",
            reason="Sensitive files need explicit review before worker edits.",
        ),
    }

    def describe(self, name: str) -> GraphRisk:
        return self.RISK_DEFINITIONS.get(
            name,
            GraphRisk(name=name, severity="medium", reason="Detected by repo graph scan."),
        )

    def risks_for_path(self, relative_path: str) -> list[str]:
        name = relative_path.lower()
        if name in {".env", ".env.local"} or "secret" in name or "credential" in name:
            return ["sensitive_file"]
        return []
