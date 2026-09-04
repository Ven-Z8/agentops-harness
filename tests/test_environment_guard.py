"""Environment-identity enforcement tests (AO-D03-02).

A task spec may pin the execution environment (image digest). Enforcement is
fail-closed: if the pinned environment cannot be guaranteed, the run must NOT
proceed on an unverified environment — dependency rot must never masquerade
as a code result. The resolver is injected so the logic is hermetic; a real
docker-backed test (auto-skipped when the daemon is down) covers the actual
`docker image inspect` path.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from app.core.environment_guard import (
    normalize_image_digest,
    verify_environment_identity,
)
from app.schemas.task_spec import EnvironmentIdentity

IMAGE_REF = "ghcr.io/astral-sh/uv:python3.12-bookworm-slim"
DIGEST = "sha256:" + "ab" * 32


class TestNoIdentityPinned:
    def test_empty_identity_is_ok_and_records_the_gap(self) -> None:
        v = verify_environment_identity(
            EnvironmentIdentity(),
            workspace_kind="local",
            image_ref=IMAGE_REF,
            resolve_image_digest=lambda ref: DIGEST,
        )
        assert v.pinned is False
        assert v.ok is True
        assert any("gap" in r.lower() for r in v.reasons)

    def test_lockfile_or_python_only_is_recorded_not_blocking(self) -> None:
        """Only image_digest is enforceable in this slice; lockfile/python
        pins are disclosed as declared-but-unverified, never silently matched."""
        v = verify_environment_identity(
            EnvironmentIdentity(lockfile_digest="sha256:ff", python_version="3.12"),
            workspace_kind="docker",
            image_ref=IMAGE_REF,
            resolve_image_digest=lambda ref: DIGEST,
        )
        assert v.pinned is False
        assert v.ok is True
        assert any("declared" in r.lower() or "not enforced" in r.lower() for r in v.reasons)


class TestImageDigestEnforced:
    def _pinned(self) -> EnvironmentIdentity:
        return EnvironmentIdentity(image_digest=DIGEST)

    def test_matching_digest_on_docker_workspace_is_verified(self) -> None:
        v = verify_environment_identity(
            self._pinned(),
            workspace_kind="docker",
            image_ref=IMAGE_REF,
            resolve_image_digest=lambda ref: DIGEST,
        )
        assert v.pinned is True
        assert v.verified is True
        assert v.indeterminate is False
        assert v.ok is True
        assert v.resolved_image_digest == DIGEST

    def test_digest_mismatch_blocks(self) -> None:
        drifted = "sha256:" + "cd" * 32
        v = verify_environment_identity(
            self._pinned(),
            workspace_kind="docker",
            image_ref=IMAGE_REF,
            resolve_image_digest=lambda ref: drifted,
        )
        assert v.verified is False
        assert v.ok is False
        assert any("mismatch" in r.lower() for r in v.reasons)

    def test_local_workspace_cannot_guarantee_pinned_image(self) -> None:
        v = verify_environment_identity(
            self._pinned(),
            workspace_kind="local",
            image_ref=IMAGE_REF,
            resolve_image_digest=lambda ref: DIGEST,
        )
        assert v.indeterminate is True
        assert v.ok is False
        assert any("docker" in r.lower() for r in v.reasons)

    def test_unresolvable_digest_is_indeterminate_not_pass(self) -> None:
        v = verify_environment_identity(
            self._pinned(),
            workspace_kind="docker",
            image_ref=IMAGE_REF,
            resolve_image_digest=lambda ref: None,
        )
        assert v.indeterminate is True
        assert v.verified is False
        assert v.ok is False

    def test_docker_workspace_without_image_ref_blocks(self) -> None:
        v = verify_environment_identity(
            self._pinned(),
            workspace_kind="docker",
            image_ref=None,
            resolve_image_digest=lambda ref: DIGEST,
        )
        assert v.ok is False
        assert v.indeterminate is True


class TestDigestNormalization:
    def test_extracts_sha_from_repo_qualified_digest(self) -> None:
        assert normalize_image_digest(f"repo/name@{DIGEST}") == DIGEST

    def test_passthrough_bare_digest(self) -> None:
        assert normalize_image_digest(DIGEST) == DIGEST

    def test_match_ignores_repo_prefix(self) -> None:
        v = verify_environment_identity(
            EnvironmentIdentity(image_digest=DIGEST),
            workspace_kind="docker",
            image_ref=IMAGE_REF,
            resolve_image_digest=lambda ref: f"{IMAGE_REF}@{DIGEST}",
        )
        assert v.verified is True
        assert v.ok is True


def _docker_up() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(
            ["docker", "info"], capture_output=True, timeout=15, check=False
        ).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


@pytest.mark.skipif(not _docker_up(), reason="docker daemon not available")
class TestRealDockerResolver:
    def test_resolve_default_image_digest_and_verify(self) -> None:
        from app.core.environment_guard import docker_image_digest
        from app.core.workspace.docker import DEFAULT_IMAGE

        resolved = docker_image_digest(DEFAULT_IMAGE)
        if resolved is None:
            pytest.skip("default image not present and pull unavailable")
        v = verify_environment_identity(
            EnvironmentIdentity(image_digest=resolved),
            workspace_kind="docker",
            image_ref=DEFAULT_IMAGE,
            resolve_image_digest=docker_image_digest,
        )
        assert v.verified is True
        assert v.ok is True

    def test_real_resolver_mismatch_blocks(self) -> None:
        from app.core.environment_guard import docker_image_digest
        from app.core.workspace.docker import DEFAULT_IMAGE

        v = verify_environment_identity(
            EnvironmentIdentity(image_digest="sha256:" + "00" * 32),
            workspace_kind="docker",
            image_ref=DEFAULT_IMAGE,
            resolve_image_digest=docker_image_digest,
        )
        # Either the image resolves (mismatch blocks) or it can't be resolved
        # (indeterminate blocks) — both are fail-closed, never a pass.
        assert v.ok is False
