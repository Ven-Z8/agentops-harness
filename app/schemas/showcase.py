from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.pack import CapabilityPackProvenance


class ShowcaseManifest(BaseModel):
    mission_id: str
    run_id: str
    source_run_id: str = Field(min_length=1)
    target_fixture: str
    source_commit: str
    captured_at: datetime
    pack: CapabilityPackProvenance
    required_artifacts: list[str] = Field(min_length=1)
    sanitation_notes: list[str] = Field(default_factory=list)
