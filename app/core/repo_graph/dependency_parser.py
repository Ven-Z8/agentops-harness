from __future__ import annotations

import re
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Dependency:
    name: str
    ecosystem: str
    version: str | None = None
    source: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class DependencyParseResult:
    dependencies: list[Dependency] = field(default_factory=list)
    frameworks: set[str] = field(default_factory=set)
    build_tools: set[str] = field(default_factory=set)
    risks: list[str] = field(default_factory=list)


class DependencyParser:
    def parse(self, repo_path: Path, relative_files: list[str]) -> DependencyParseResult:
        result = DependencyParseResult()
        if "pyproject.toml" in relative_files:
            self._parse_pyproject(repo_path / "pyproject.toml", result)
        if "requirements.txt" in relative_files:
            self._parse_requirements(repo_path / "requirements.txt", result)
        if "pom.xml" in relative_files:
            self._parse_pom(repo_path / "pom.xml", result)
        if "build.gradle" in relative_files:
            self._parse_gradle(repo_path / "build.gradle", result)
        if "build.gradle.kts" in relative_files:
            self._parse_gradle(repo_path / "build.gradle.kts", result)
        return result

    def _parse_pyproject(self, path: Path, result: DependencyParseResult) -> None:
        result.build_tools.add("pyproject")
        try:
            payload = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            return
        project = payload.get("project", {})
        dependencies = project.get("dependencies", [])
        for dependency in dependencies:
            name = self._python_dependency_name(dependency)
            result.dependencies.append(
                Dependency(name=name, ecosystem="python", source="pyproject.toml")
            )
            if name == "fastapi":
                result.frameworks.add("fastapi")

    def _parse_requirements(self, path: Path, result: DependencyParseResult) -> None:
        result.build_tools.add("pip")
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            name = self._python_dependency_name(stripped)
            result.dependencies.append(
                Dependency(name=name, ecosystem="python", source="requirements.txt")
            )
            if name == "fastapi":
                result.frameworks.add("fastapi")

    def _parse_pom(self, path: Path, result: DependencyParseResult) -> None:
        result.build_tools.add("maven")
        try:
            root = ET.fromstring(path.read_text(encoding="utf-8", errors="ignore"))
        except ET.ParseError:
            return
        namespace = self._xml_namespace(root.tag)
        parent = root.find(f"{namespace}parent")
        if parent is not None:
            artifact = self._xml_text(parent, "artifactId", namespace)
            version = self._xml_text(parent, "version", namespace)
            if artifact:
                result.dependencies.append(
                    Dependency(
                        name=artifact,
                        ecosystem="java",
                        version=version,
                        source="pom.xml",
                        metadata={"scope": "parent"},
                    )
                )
                if artifact == "spring-boot-starter-parent":
                    result.frameworks.add("spring_boot")
                    if version and version.startswith("2."):
                        result.risks.append("spring_boot_2_detected")
        java_version = self._pom_property(root, namespace, "java.version")
        if java_version and self._major_version(java_version) < 17:
            result.risks.append("java_version_below_17")

        for dependency in root.findall(f".//{namespace}dependency"):
            group = self._xml_text(dependency, "groupId", namespace)
            artifact = self._xml_text(dependency, "artifactId", namespace)
            version = self._xml_text(dependency, "version", namespace)
            if not artifact:
                continue
            name = f"{group}:{artifact}" if group else artifact
            result.dependencies.append(
                Dependency(name=name, ecosystem="java", version=version, source="pom.xml")
            )
            if artifact.startswith("spring-boot-starter"):
                result.frameworks.add("spring_boot")
            if group and group.startswith("javax"):
                result.risks.append("javax_dependency_detected")

    def _parse_gradle(self, path: Path, result: DependencyParseResult) -> None:
        result.build_tools.add("gradle")
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "org.springframework.boot" in text:
            result.frameworks.add("spring_boot")
            version = re.search(
                r'id\s+["\']org\.springframework\.boot["\']\s+version\s+["\']([^"\']+)',
                text,
            )
            if version and version.group(1).startswith("2."):
                result.risks.append("spring_boot_2_detected")
        java_version = re.search(r"sourceCompatibility\s*=\s*['\"]?(\d+)", text)
        if java_version and int(java_version.group(1)) < 17:
            result.risks.append("java_version_below_17")
        for match in re.finditer(r"['\"]([A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:[^'\"]+)['\"]", text):
            parts = match.group(1).split(":")
            name = ":".join(parts[:2])
            version = parts[2] if len(parts) > 2 else None
            result.dependencies.append(
                Dependency(name=name, ecosystem="java", version=version, source=path.name)
            )
            if name.startswith("javax"):
                result.risks.append("javax_dependency_detected")

    def _python_dependency_name(self, dependency: str) -> str:
        return re.split(r"[<>=!~\[\]\s]", dependency, maxsplit=1)[0].lower()

    def _xml_namespace(self, tag: str) -> str:
        if tag.startswith("{"):
            return tag.split("}", 1)[0] + "}"
        return ""

    def _xml_text(self, element: ET.Element, name: str, namespace: str) -> str | None:
        child = element.find(f"{namespace}{name}")
        return child.text.strip() if child is not None and child.text else None

    def _pom_property(self, root: ET.Element, namespace: str, name: str) -> str | None:
        properties = root.find(f"{namespace}properties")
        if properties is None:
            return None
        value = properties.find(f"{namespace}{name}")
        return value.text.strip() if value is not None and value.text else None

    def _major_version(self, version: str) -> int:
        match = re.search(r"\d+", version)
        return int(match.group(0)) if match else 0
