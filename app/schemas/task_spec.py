"""SWE-bench-style task-spec contract (Phase 2 kernel entry).

A `SweTaskSpec` pins the deterministic tuple that makes an issue run
*reproducible* rather than merely repeatable (ROADMAP.md "What remains",
item 3; agentops-codex-handover Phase 2 memo, research question 1).

The spec is the first concrete `ExperimentSpec`: it is decoupled from any
particular worker (execution provider) and from any particular test
machinery (evaluation provider). The flagship issue path consumes it; the
Phase 2 benchmark and the Phase 5 VLM/VLA reference paths reuse the same
contract shape.

Fields follow the SWE-bench Verified convention:

- ``repo`` + ``base_commit``: the exact code baseline (no HEAD drift).
- ``problem_statement``: what the agent is asked to do.
- ``fail_to_pass``: maintainer tests that FAIL at ``base_commit`` and MUST
  pass after the fix (the negative contract proves the first half before
  the worker starts).
- ``pass_to_pass``: existing tests that must KEEP passing (regression
  prevention).
- ``environment``: identity of the pinned execution environment (image
  digest, Python/uv pins, lockfile digest) so dependency rot cannot
  masquerade as a code result.

Fail-closed semantics (AO-D01 class): a spec without at least one
``fail_to_pass`` test cannot prove its bug exists and therefore cannot
open a run. Missing evidence is inconclusive, never an inferred pass.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class EnvironmentIdentity(BaseModel):
    """Identity of the pinned execution environment.

    Every field is optional-but-hashable: a spec with no environment
    identity is still valid, but comparisons against it must record the
    gap rather than assume environments match.
    """

    image_digest: str | None = None
    python_version: str | None = None
    lockfile_digest: str | None = None
    notes: list[str] = Field(default_factory=list)


class SweTaskSpec(BaseModel):
    """The deterministic task tuple (SWE-bench Verified convention)."""

    repo: str = Field(min_length=3, description="owner/name, e.g. 'psf/requests'.")
    base_commit: str = Field(min_length=1, description="Exact commit hash; never HEAD.")
    problem_statement: str = Field(min_length=1)
    fail_to_pass: list[str] = Field(min_length=1)
    pass_to_pass: list[str] = Field(default_factory=list)
    environment: EnvironmentIdentity = Field(default_factory=EnvironmentIdentity)
    source: Literal["swebench_verified", "github_issue", "manual"] = "manual"

    @field_validator("base_commit")
    @classmethod
    def _reject_head_ref(cls, value: str) -> str:
        if value.strip().lower() in {"head", "origin/head", "@"}:
            raise ValueError(
                "base_commit must be a pinned hash, not HEAD — a movable ref "
                "makes the task non-reproducible (dependency/state drift)."
            )
        return value

    @field_validator("fail_to_pass")
    @classmethod
    def _require_negative_contract(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError(
                "A task spec needs at least one fail_to_pass test: without a "
                "test that fails at base_commit, the bug's existence cannot "
                "be proven before the worker starts (negative contract)."
            )
        return value

    @classmethod
    def from_swebench_instance(cls, raw: dict) -> SweTaskSpec:
        """Parse a SWE-bench-style task-instance JSON.

        SWE-bench serializes FAIL_TO_PASS / PASS_TO_PASS as JSON *strings*
        (a list encoded as a JSON array literal); tolerate both the string
        form and a real list so datasets load without preprocessing.
        """
        def _parse_tests(value: object) -> list[str]:
            if value is None:
                return []
            if isinstance(value, str):
                parsed = json.loads(value)
                if not isinstance(parsed, list):
                    raise ValueError(
                        f"Expected a JSON-encoded list of test ids, got: {value[:120]!r}"
                    )
                return [str(item) for item in parsed]
            if isinstance(value, list):
                return [str(item) for item in value]
            raise ValueError(f"Unsupported FAIL_TO_PASS/PASS_TO_PASS shape: {type(value)}")

        def _parse_environment(value: object) -> EnvironmentIdentity:
            # AO-D03-02: carry a pinned execution environment through the
            # parser so enforcement can act on it. Absent/empty → the default
            # empty identity (a recorded gap, never an assumed match).
            if not isinstance(value, dict):
                return EnvironmentIdentity()
            notes = value.get("notes") or []
            if not isinstance(notes, list):
                notes = [str(notes)]
            return EnvironmentIdentity(
                image_digest=value.get("image_digest"),
                python_version=value.get("python_version"),
                lockfile_digest=value.get("lockfile_digest"),
                notes=[str(note) for note in notes],
            )

        return cls(
            repo=str(raw["repo"]),
            base_commit=str(raw["base_commit"]),
            problem_statement=str(raw.get("problem_statement") or raw.get("issue_body") or ""),
            fail_to_pass=_parse_tests(raw.get("FAIL_TO_PASS") or []),
            pass_to_pass=_parse_tests(raw.get("PASS_TO_PASS") or []),
            environment=_parse_environment(raw.get("environment")),
            source="swebench_verified",
        )
