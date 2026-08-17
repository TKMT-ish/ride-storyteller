"""Private, local-only configuration for the browser Google Maps loader."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlencode

from app.config import load_local_environment


@dataclass(frozen=True)
class GoogleMapsSettings:
    api_key: str

    @classmethod
    def from_environment(cls) -> "GoogleMapsSettings":
        local_values = load_local_environment()
        return cls(
            api_key=os.environ.get(
                "GOOGLE_MAPS_API_KEY", local_values.get("GOOGLE_MAPS_API_KEY", "")
            ).strip()
        )

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def javascript_url(self, *, language: str = "ja") -> str:
        if not self.enabled:
            raise ValueError("GOOGLE_MAPS_API_KEY is not configured")
        if language not in {"ja", "en"}:
            raise ValueError("Google Maps language must be ja or en")
        return "https://maps.googleapis.com/maps/api/js?" + urlencode(
            {
                "key": self.api_key,
                "callback": "initRideMap",
                "v": "weekly",
                "language": language,
            }
        )
