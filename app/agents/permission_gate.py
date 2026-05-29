"""Classifies a proposed change into permission tiers (Code-as-Agent-Harness §5.2.5).

Where `app/core/security.py` answers a binary "is this allowed?", the permission
gate answers "at what tier should this proceed?" — auto, ask, or deny. It reuses
the existing sensitivity predicates so the two layers stay consistent, and adds
the graded middle tier the paper argues real governance needs.

Tier policy (mirrors CLAUDE.md):
  deny  — secrets touched/deleted, destructive commands (cannot be undone easily)
  ask   — sensitive folders, dependency/config changes, any file deletion
  auto  — everything else
"""

from __future__ import annotations

from app.core.security import (
    BLOCKED_COMMAND_FRAGMENTS,
    SENSITIVE_FOLDERS,
    is_sensitive_path,
    normalize_repo_path,
)
from app.schemas.permission import PermissionDecision, PermissionReport

_DEPENDENCY_SUFFIXES = ("pyproject.toml", "uv.lock", "requirements.txt", "package.json")


class PermissionGate:
    def classify(
        self,
        changed_files: list[str],
        deleted_files: list[str],
        commands: list[str],
    ) -> PermissionReport:
        decisions: list[PermissionDecision] = []

        for path in changed_files:
            decisions.append(self._classify_changed_file(path))
        for path in deleted_files:
            decisions.append(self._classify_deleted_file(path))
        for command in commands:
            decision = self._classify_command(command)
            if decision is not None:
                decisions.append(decision)

        return PermissionReport(decisions=decisions)

    # -- per-action classification -------------------------------------------

    def _classify_changed_file(self, path: str) -> PermissionDecision:
        if is_sensitive_path(path) and not self._is_sensitive_folder_only(path):
            return PermissionDecision(
                action=f"edit {path}",
                tier="deny",
                rule="secret_file",
                reason="Editing a secret/credential file cannot be auto-approved.",
            )
        if self._is_sensitive_folder_only(path):
            return PermissionDecision(
                action=f"edit {path}",
                tier="ask",
                rule="sensitive_folder",
                reason="Change touches a security-sensitive folder.",
            )
        if path.endswith(_DEPENDENCY_SUFFIXES):
            return PermissionDecision(
                action=f"edit {path}",
                tier="ask",
                rule="dependency_change",
                reason="Dependency/config change can alter the build surface.",
            )
        return PermissionDecision(
            action=f"edit {path}",
            tier="auto",
            rule="ordinary_source",
            reason="Ordinary source change with no risk markers.",
        )

    def _classify_deleted_file(self, path: str) -> PermissionDecision:
        if is_sensitive_path(path) and not self._is_sensitive_folder_only(path):
            return PermissionDecision(
                action=f"delete {path}",
                tier="deny",
                rule="secret_deletion",
                reason="Deleting a secret/credential file is destructive.",
            )
        return PermissionDecision(
            action=f"delete {path}",
            tier="ask",
            rule="file_deletion",
            reason="File deletion is not easily reversible; confirm intent.",
        )

    def _classify_command(self, command: str) -> PermissionDecision | None:
        lowered = command.lower()
        for fragment in BLOCKED_COMMAND_FRAGMENTS:
            if fragment in lowered:
                return PermissionDecision(
                    action=command,
                    tier="deny",
                    rule="destructive_command",
                    reason=f"Command contains blocked fragment: {fragment!r}",
                )
        return None

    # -- helpers -------------------------------------------------------------

    def _is_sensitive_folder_only(self, path: str) -> bool:
        """True when a path is sensitive *because of its folder* (auth/security/...),
        as opposed to being a secret file by name/extension."""
        normalized = normalize_repo_path(path)
        parts = {part.lower() for part in normalized.split("/")}
        return bool(SENSITIVE_FOLDERS.intersection(parts))
