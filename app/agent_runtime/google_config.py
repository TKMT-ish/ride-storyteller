"""Non-network Google Cloud configuration contract for the future ADK runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.config import load_local_environment


@dataclass(frozen=True)
class GoogleCloudRuntimeSettings:
    project: str
    location: str
    model: str
    use_vertex_ai: str

    @classmethod
    def from_environment(cls) -> "GoogleCloudRuntimeSettings":
        local_values = load_local_environment()
        return cls(
            project=os.environ.get(
                "GOOGLE_CLOUD_PROJECT", local_values.get("GOOGLE_CLOUD_PROJECT", "")
            ).strip(),
            location=os.environ.get(
                "GOOGLE_CLOUD_LOCATION", local_values.get("GOOGLE_CLOUD_LOCATION", "")
            ).strip(),
            model=os.environ.get("GEMINI_MODEL", local_values.get("GEMINI_MODEL", "")).strip(),
            use_vertex_ai=os.environ.get(
                "GOOGLE_GENAI_USE_VERTEXAI",
                local_values.get("GOOGLE_GENAI_USE_VERTEXAI", ""),
            )
            .strip()
            .lower(),
        )

    @property
    def missing_configuration(self) -> tuple[str, ...]:
        missing: list[str] = []
        if not self.project:
            missing.append("GOOGLE_CLOUD_PROJECT")
        if not self.location:
            missing.append("GOOGLE_CLOUD_LOCATION")
        if not self.model:
            missing.append("GEMINI_MODEL")
        if self.use_vertex_ai != "true":
            missing.append("GOOGLE_GENAI_USE_VERTEXAI=true")
        return tuple(missing)

    @property
    def status(self) -> str:
        """Report configuration presence only; it never represents authentication."""
        return "configuration_present" if not self.missing_configuration else "unconfigured"

    def to_dict(self) -> dict[str, object]:
        """Expose names and state, never credentials or a service-account path."""
        return {
            "status": self.status,
            "project_configured": bool(self.project),
            "location_configured": bool(self.location),
            "model_configured": bool(self.model),
            "vertex_ai_enabled": self.use_vertex_ai == "true",
            "missing_configuration": list(self.missing_configuration),
        }
