from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PythonImport:
    name: str
    imported_from: str | None = None


@dataclass(frozen=True)
class PythonSymbol:
    name: str
    qualified_name: str
    symbol_type: str
    line: int


@dataclass(frozen=True)
class PythonRoute:
    method: str
    path: str
    function_name: str
    line: int


@dataclass
class PythonParseResult:
    imports: list[PythonImport] = field(default_factory=list)
    symbols: list[PythonSymbol] = field(default_factory=list)
    routes: list[PythonRoute] = field(default_factory=list)
    is_test: bool = False
    uses_fastapi: bool = False


class PythonParser:
    ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}

    def parse(self, repo_path: Path, relative_path: str) -> PythonParseResult:
        file_path = repo_path / relative_path
        result = PythonParseResult(is_test=self._is_test_file(relative_path))
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            return result

        module = self._module_name(relative_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result.imports.append(PythonImport(name=alias.name))
                    if alias.name == "fastapi" or alias.name.startswith("fastapi."):
                        result.uses_fastapi = True
            elif isinstance(node, ast.ImportFrom):
                imported_from = node.module or ""
                for alias in node.names:
                    name = f"{imported_from}.{alias.name}" if imported_from else alias.name
                    result.imports.append(PythonImport(name=name, imported_from=imported_from))
                if imported_from == "fastapi" or imported_from.startswith("fastapi."):
                    result.uses_fastapi = True
            elif isinstance(node, ast.ClassDef):
                result.symbols.append(
                    PythonSymbol(
                        name=node.name,
                        qualified_name=f"{module}.{node.name}",
                        symbol_type="class",
                        line=node.lineno,
                    )
                )
                for item in node.body:
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                        result.symbols.append(
                            PythonSymbol(
                                name=item.name,
                                qualified_name=f"{module}.{node.name}.{item.name}",
                                symbol_type="method",
                                line=item.lineno,
                            )
                        )
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                result.symbols.append(
                    PythonSymbol(
                        name=node.name,
                        qualified_name=f"{module}.{node.name}",
                        symbol_type="function",
                        line=node.lineno,
                    )
                )
                result.routes.extend(self._routes_for_function(node))
                if node.name.startswith("test_"):
                    result.is_test = True

        return result

    def _routes_for_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> list[PythonRoute]:
        routes: list[PythonRoute] = []
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            method = self._route_method(decorator.func)
            if method is None or not decorator.args:
                continue
            path_arg = decorator.args[0]
            if isinstance(path_arg, ast.Constant) and isinstance(path_arg.value, str):
                routes.append(
                    PythonRoute(
                        method=method.upper(),
                        path=path_arg.value,
                        function_name=node.name,
                        line=node.lineno,
                    )
                )
        return routes

    def _route_method(self, func: ast.expr) -> str | None:
        if isinstance(func, ast.Attribute) and func.attr in self.ROUTE_METHODS:
            return func.attr
        return None

    def _is_test_file(self, relative_path: str) -> bool:
        name = Path(relative_path).name
        return (
            relative_path.startswith("tests/")
            or name.startswith("test_")
            or name.endswith("_test.py")
        )

    def _module_name(self, relative_path: str) -> str:
        path = Path(relative_path)
        without_suffix = path.with_suffix("")
        parts = [part for part in without_suffix.parts if part != "__init__"]
        return ".".join(parts)
