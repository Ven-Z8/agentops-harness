from __future__ import annotations

from pathlib import Path


class TestMapper:
    def likely_source_for_test(self, test_path: str, source_files: list[str]) -> str | None:
        test_name = Path(test_path).stem
        candidates = self._candidate_names(test_name)
        by_stem = {Path(path).stem.lower(): path for path in source_files}
        for candidate in candidates:
            if candidate in by_stem:
                return by_stem[candidate]
        non_init_sources = [path for path in source_files if Path(path).name != "__init__.py"]
        if len(non_init_sources) == 1:
            return non_init_sources[0]
        return None

    def _candidate_names(self, test_name: str) -> list[str]:
        normalized = test_name.lower()
        candidates = [normalized]
        for prefix in ("test_", "test"):
            if normalized.startswith(prefix):
                candidates.append(normalized.removeprefix(prefix))
        for suffix in ("_test", "test", "tests"):
            if normalized.endswith(suffix):
                candidates.append(normalized.removesuffix(suffix))
        return [candidate for candidate in candidates if candidate]
