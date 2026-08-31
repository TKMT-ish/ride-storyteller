"""Safe loopback preview for a private DirectorScript artifact.

The deterministic Editor needs private source identity in its artifact.  This
module deliberately exposes only a narrative summary to the browser, so a
local user can inspect the story without receiving asset IDs, file names,
source intervals, coordinates, or paths.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import load_local_environment
from app.director import NarrativeArc
from app.director_pipeline import DIRECTOR_SCRIPT_SCHEMA_VERSION

PRIVATE_DIRECTOR_SCRIPT_PATH_ENV = "RIDE_PRIVATE_DIRECTOR_SCRIPT_PATH"
_ALLOWED_TRANSITIONS = frozenset({"cut"})
_ARC_ORDER = tuple(NarrativeArc)


class PrivateDirectorPreviewError(RuntimeError):
    """Raised when the configured private DirectorScript is not safe to preview."""


@dataclass(frozen=True)
class PrivateDirectorPreview:
    """Read a single explicitly configured private artifact as a safe view."""

    script_path: Path

    @classmethod
    def from_environment(cls) -> "PrivateDirectorPreview":
        local_values = load_local_environment()
        raw_path = os.environ.get(
            PRIVATE_DIRECTOR_SCRIPT_PATH_ENV,
            local_values.get(PRIVATE_DIRECTOR_SCRIPT_PATH_ENV, ""),
        ).strip()
        if not raw_path:
            raise PrivateDirectorPreviewError("private DirectorScript is not configured")
        return cls.from_file(Path(raw_path).expanduser())

    @classmethod
    def from_file(cls, script_path: Path) -> "PrivateDirectorPreview":
        if script_path.is_symlink() or not script_path.is_file():
            raise PrivateDirectorPreviewError("private DirectorScript is unavailable")
        return cls(script_path=script_path.resolve())

    def payload(self) -> dict[str, object]:
        """Return only browser-safe narrative structure from the local artifact."""
        try:
            raw = json.loads(self.script_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PrivateDirectorPreviewError("private DirectorScript is unreadable") from error
        if not isinstance(raw, dict) or raw.get("schema_version") != DIRECTOR_SCRIPT_SCHEMA_VERSION:
            raise PrivateDirectorPreviewError("private DirectorScript has an invalid schema")
        metadata = _mapping(raw.get("metadata"))
        composer = _non_empty_string(metadata.get("composer"), "composer")
        event_count_in = _non_negative_int(metadata.get("event_count_in"), "event_count_in")
        event_count_used = _non_negative_int(metadata.get("event_count_used"), "event_count_used")
        if event_count_used > event_count_in:
            raise PrivateDirectorPreviewError("private DirectorScript has invalid event counts")
        raw_scenes = raw.get("scenes")
        if not isinstance(raw_scenes, list) or not raw_scenes:
            raise PrivateDirectorPreviewError("private DirectorScript has no scenes")

        seen_roles: set[NarrativeArc] = set()
        previous_arc_index = -1
        scenes: list[dict[str, object]] = []
        clip_total = 0
        for index, raw_scene in enumerate(raw_scenes):
            scene = _mapping(raw_scene)
            role_raw = _non_empty_string(scene.get("scene_type"), f"scenes[{index}].scene_type")
            try:
                role = NarrativeArc(role_raw)
            except ValueError as error:
                raise PrivateDirectorPreviewError(
                    "private DirectorScript has an invalid scene role"
                ) from error
            arc_index = _ARC_ORDER.index(role)
            if role in seen_roles or arc_index <= previous_arc_index:
                raise PrivateDirectorPreviewError("private DirectorScript has invalid scene order")
            transition_type = _non_empty_string(
                scene.get("transition_type"), f"scenes[{index}].transition_type"
            )
            if transition_type not in _ALLOWED_TRANSITIONS:
                raise PrivateDirectorPreviewError(
                    "private DirectorScript has an invalid transition"
                )
            overlay_text = scene.get("overlay_text")
            if overlay_text is not None and not isinstance(overlay_text, str):
                raise PrivateDirectorPreviewError("private DirectorScript has an invalid overlay")
            raw_clips = scene.get("clips")
            if not isinstance(raw_clips, list) or not raw_clips:
                raise PrivateDirectorPreviewError("private DirectorScript has an empty scene")
            clip_total += len(raw_clips)
            scenes.append(
                {
                    "role": role.value,
                    "event_count": len(raw_clips),
                    "transition_type": transition_type,
                    "overlay_text": overlay_text,
                }
            )
            seen_roles.add(role)
            previous_arc_index = arc_index

        if clip_total != event_count_used:
            raise PrivateDirectorPreviewError(
                "private DirectorScript has inconsistent event counts"
            )
        return {
            "local_only": True,
            "external_data_sent": False,
            "director_script": {
                "composer": composer,
                "event_count_in": event_count_in,
                "event_count_used": event_count_used,
                "scenes": scenes,
            },
        }


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PrivateDirectorPreviewError("private DirectorScript has an invalid structure")
    return value


def _non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PrivateDirectorPreviewError(f"private DirectorScript has an invalid {field_name}")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PrivateDirectorPreviewError(f"private DirectorScript has an invalid {field_name}")
    return value
