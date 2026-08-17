"""Serialize local planning outputs for a future Google ADK / Agent Builder adapter."""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts import StoryPlan
from app.edit import CandidateEditPlan

from .google_config import GoogleCloudRuntimeSettings


@dataclass(frozen=True)
class AdkHandoff:
    schema_version: str
    runtime_status: str
    task: str
    payload: dict[str, object]
    required_configuration: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "runtime_status": self.runtime_status,
            "task": self.task,
            "payload": self.payload,
            "required_configuration": list(self.required_configuration),
        }


def build_adk_handoff(story_plan: StoryPlan, candidates: CandidateEditPlan) -> AdkHandoff:
    """Build data for an adapter without importing ADK or cloud credentials locally."""
    settings = GoogleCloudRuntimeSettings.from_environment()
    return AdkHandoff(
        schema_version="adk-handoff-v1",
        runtime_status=settings.status,
        task="ride_storyteller_edit_review",
        payload={
            "story_plan": story_plan.to_dict(),
            "candidate_edit_plan": candidates.to_dict(),
            "google_cloud_configuration": settings.to_dict(),
        },
        required_configuration=settings.missing_configuration
        + (
            "Google Cloud authentication",
            "Agent Builder / ADK runtime selection",
            "authenticated deployment target",
        ),
    )
