from __future__ import annotations

import hashlib
from datetime import UTC
from pathlib import Path

from app.project_control.io import load_yaml
from app.project_control.models import ArtifactIndex, VerificationEvidence
from app.project_control.roadmap import load_roadmap


def load_artifact_index(root: Path) -> ArtifactIndex:
    """Load the artifact metadata index and reject records outside the roadmap."""
    index = load_yaml(root / "coordination" / "artifacts" / "index.yaml", ArtifactIndex, root=root)
    roadmap_ids = {item.id for item in load_roadmap(root).items}
    for artifact in index.artifacts:
        if artifact.task_id not in roadmap_ids:
            raise ValueError(f"Roadmap does not include item: {artifact.task_id}")
        if artifact.kind == "verification-evidence":
            if artifact.availability != "repository" or not artifact.locator:
                raise ValueError("verification evidence must be a repository artifact")
            evidence_path = root / artifact.locator
            evidence = load_yaml(evidence_path, VerificationEvidence, root=root)
            if evidence.task_id != artifact.task_id:
                raise ValueError("verification evidence task_id does not match artifact")
            if artifact.immutable and artifact.sha256:
                actual = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
                if actual != artifact.sha256:
                    raise ValueError("verification evidence sha256 does not match artifact")
    return index


def _timestamp(value) -> str:
    if value.tzinfo is not None:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return value.isoformat()


def render_artifact_summary(index: ArtifactIndex) -> str:
    """Render portable, deterministic artifact metadata without inferring evidence."""
    lines = ["# Artifact summary", ""]
    artifacts = sorted(index.artifacts, key=lambda item: (item.task_id, item.created_at, item.id))
    for artifact in artifacts:
        availability = artifact.availability
        if availability == "local":
            availability = "local (non-portable)"
        evidence = artifact.evidence_state
        if artifact.required and artifact.availability == "unavailable":
            evidence = "inconclusive"
        lines.extend(
            [
                f"## {artifact.id}",
                f"- Task: {artifact.task_id}",
                f"- Kind: {artifact.kind}",
                f"- Availability: {availability}",
                f"- Locator: {artifact.locator or 'None'}",
                f"- SHA-256: {artifact.sha256 or 'None'}",
                f"- Evidence: {evidence}",
                f"- Created at: {_timestamp(artifact.created_at)}",
                f"- Producer: {artifact.producer}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
