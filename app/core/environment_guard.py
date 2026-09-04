"""Environment-identity enforcement for task specs (AO-D03-02).

A spec may pin its execution environment via ``EnvironmentIdentity`` (image
digest, python pin, lockfile digest) so dependency rot cannot masquerade as a
code result. This module is the fail-closed sensor that decides whether the
pinned environment is actually guaranteed:

- no identity pinned → nothing to enforce; the gap is RECORDED, never assumed
  away (honesty: environments-match is not the default assumption);
- ``image_digest`` pinned → the Docker testbed's resolved digest must match,
  and only a docker workspace can guarantee a pinned image (host execution
  cannot) — anything else is indeterminate and blocks;
- ``lockfile_digest`` / ``python_version`` pins are disclosed as
  declared-but-not-enforced in this slice (image identity is the testbed
  handle); enforcing them inside the container is the follow-up.

Fail-closed everywhere: an unresolvable digest is indeterminate, never an
inferred pass.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

from app.schemas.task_spec import EnvironmentIdentity

ImageDigestResolver = Callable[[str], str | None]

INSPECT_TIMEOUT = 20


@dataclass(frozen=True)
class EnvironmentVerification:
    """The verdict on a spec's pinned environment.

    ``ok`` is the gate input: True when nothing is pinned (gap recorded) or
    when the pinned identity is positively verified. Indeterminate or
    mismatched environments are never ok.
    """

    pinned: bool
    verified: bool
    indeterminate: bool
    resolved_image_digest: str | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (not self.pinned) or (self.verified and not self.indeterminate)


def normalize_image_digest(value: str) -> str:
    """Reduce 'repo/name@sha256:…' (or a bare 'sha256:…') to the digest part."""
    marker = "sha256:"
    index = value.find(marker)
    return value[index:] if index >= 0 else value


def docker_image_digest(image_ref: str) -> str | None:
    """Resolve an image's repo digest via the docker CLI (production resolver).

    Returns None when docker or the image is unavailable — callers treat that
    as indeterminate, never as a match.
    """
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_ref, "--format", "{{index .RepoDigests 0}}"],
            capture_output=True,
            text=True,
            timeout=INSPECT_TIMEOUT,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    digest = result.stdout.strip()
    if not digest or digest.startswith("[") or "@" not in digest:
        return None
    return normalize_image_digest(digest)


def verify_environment_identity(
    environment: EnvironmentIdentity,
    *,
    workspace_kind: str,
    image_ref: str | None,
    resolve_image_digest: ImageDigestResolver,
) -> EnvironmentVerification:
    """Decide whether the spec's pinned environment is guaranteed."""
    declared_non_image = bool(environment.lockfile_digest or environment.python_version)

    if not environment.image_digest:
        reasons = [
            "No image identity pinned — recording the environment gap rather "
            "than assuming environments match."
        ]
        if declared_non_image:
            reasons.append(
                "Spec declares lockfile/python identity but no image_digest; "
                "declared pins are not enforced in this slice (image identity "
                "is the testbed handle)."
            )
        return EnvironmentVerification(
            pinned=False,
            verified=False,
            indeterminate=False,
            resolved_image_digest=None,
            reasons=reasons,
        )

    pinned_digest = normalize_image_digest(environment.image_digest)

    if workspace_kind != "docker":
        return EnvironmentVerification(
            pinned=True,
            verified=False,
            indeterminate=True,
            reasons=[
                f"Environment identity pins image digest {pinned_digest[:19]}… but "
                f"the workspace is '{workspace_kind}'. Host execution cannot "
                "guarantee a pinned image — run against a docker testbed."
            ],
        )

    if image_ref is None:
        return EnvironmentVerification(
            pinned=True,
            verified=False,
            indeterminate=True,
            reasons=[
                "Environment identity pins an image digest but no testbed image "
                "is configured for the docker workspace."
            ],
        )

    resolved = resolve_image_digest(image_ref)
    if resolved is None:
        return EnvironmentVerification(
            pinned=True,
            verified=False,
            indeterminate=True,
            resolved_image_digest=None,
            reasons=[
                f"Could not resolve a digest for testbed image '{image_ref}' "
                "(docker unavailable or image missing) — inconclusive, never a pass."
            ],
        )

    resolved_digest = normalize_image_digest(resolved)
    if resolved_digest != pinned_digest:
        return EnvironmentVerification(
            pinned=True,
            verified=False,
            indeterminate=False,
            resolved_image_digest=resolved_digest,
            reasons=[
                "Image digest MISMATCH: testbed resolves to "
                f"{resolved_digest[:19]}… but the spec pins {pinned_digest[:19]}… "
                "— environment drift; refusing to run on an unverified environment."
            ],
        )

    return EnvironmentVerification(
        pinned=True,
        verified=True,
        indeterminate=False,
        resolved_image_digest=resolved_digest,
        reasons=[
            f"Environment identity verified: testbed image matches pinned digest "
            f"{resolved_digest[:19]}…"
        ],
    )
