from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class JavaClass:
    name: str
    qualified_name: str
    class_type: str
    annotations: list[str]
    line: int


@dataclass(frozen=True)
class JavaRoute:
    method: str
    path: str
    owner: str
    line: int


@dataclass
class JavaParseResult:
    package: str | None = None
    imports: list[str] = field(default_factory=list)
    classes: list[JavaClass] = field(default_factory=list)
    routes: list[JavaRoute] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)
    is_spring: bool = False
    is_test: bool = False


class JavaParser:
    CLASS_RE = re.compile(r"\b(class|interface|enum)\s+([A-Za-z_][A-Za-z0-9_]*)")
    IMPORT_RE = re.compile(r"^\s*import\s+([^;]+);", re.MULTILINE)
    PACKAGE_RE = re.compile(r"^\s*package\s+([^;]+);", re.MULTILINE)
    ANNOTATION_RE = re.compile(r"^\s*@([A-Za-z_][A-Za-z0-9_]*)(?:\((.*?)\))?", re.MULTILINE)
    ROUTE_METHODS = {
        "GetMapping": "GET",
        "PostMapping": "POST",
        "PutMapping": "PUT",
        "PatchMapping": "PATCH",
        "DeleteMapping": "DELETE",
    }
    SPRING_ANNOTATIONS = {
        "RestController",
        "Controller",
        "Service",
        "Repository",
        "Entity",
        "SpringBootApplication",
        "GetMapping",
        "PostMapping",
        "PutMapping",
        "PatchMapping",
        "DeleteMapping",
        "RequestMapping",
    }

    def parse(self, repo_path: Path, relative_path: str) -> JavaParseResult:
        text = (repo_path / relative_path).read_text(encoding="utf-8", errors="ignore")
        result = JavaParseResult(is_test=self._is_test_file(relative_path))

        package_match = self.PACKAGE_RE.search(text)
        if package_match:
            result.package = package_match.group(1).strip()

        result.imports = [match.group(1).strip() for match in self.IMPORT_RE.finditer(text)]
        annotations = [
            (match.group(1), match.group(2) or "", self._line_for(text, match.start()))
            for match in self.ANNOTATION_RE.finditer(text)
        ]
        result.annotations = sorted({name for name, _, _ in annotations})
        result.is_spring = bool(set(result.annotations).intersection(self.SPRING_ANNOTATIONS))

        class_annotations = [name for name, _, _ in annotations if name in self.SPRING_ANNOTATIONS]
        for match in self.CLASS_RE.finditer(text):
            class_type = match.group(1)
            name = match.group(2)
            qualified = f"{result.package}.{name}" if result.package else name
            result.classes.append(
                JavaClass(
                    name=name,
                    qualified_name=qualified,
                    class_type=class_type,
                    annotations=class_annotations,
                    line=self._line_for(text, match.start()),
                )
            )

        owner = result.classes[0].qualified_name if result.classes else relative_path
        for name, raw_args, line in annotations:
            route = self._route_for_annotation(name, raw_args, owner, line)
            if route is not None:
                result.routes.append(route)

        result.risks = self._detect_risks(text, result.imports)
        return result

    def _route_for_annotation(
        self,
        name: str,
        raw_args: str,
        owner: str,
        line: int,
    ) -> JavaRoute | None:
        if name in self.ROUTE_METHODS:
            return JavaRoute(
                method=self.ROUTE_METHODS[name],
                path=self._mapping_path(raw_args),
                owner=owner,
                line=line,
            )
        if name == "RequestMapping":
            return JavaRoute(
                method="ANY",
                path=self._mapping_path(raw_args),
                owner=owner,
                line=line,
            )
        return None

    def _mapping_path(self, raw_args: str) -> str:
        quoted = re.search(r'"([^"]+)"', raw_args)
        if quoted:
            return quoted.group(1)
        value_arg = re.search(r"value\s*=\s*\"([^\"]+)\"", raw_args)
        if value_arg:
            return value_arg.group(1)
        return "/"

    def _detect_risks(self, text: str, imports: list[str]) -> list[str]:
        risks: set[str] = set()
        if any(name.startswith("javax.") for name in imports) or "javax." in text:
            risks.add("javax_to_jakarta_required")
        if "WebSecurityConfigurerAdapter" in text:
            risks.add("web_security_configurer_adapter_removed")
        return sorted(risks)

    def _is_test_file(self, relative_path: str) -> bool:
        name = Path(relative_path).name
        return (
            "/src/test/" in f"/{relative_path}"
            or name.endswith("Test.java")
            or name.endswith("Tests.java")
        )

    def _line_for(self, text: str, index: int) -> int:
        return text.count("\n", 0, index) + 1
