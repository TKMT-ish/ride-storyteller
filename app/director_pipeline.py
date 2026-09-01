"""Director pipeline: Scout → Director → ScriptExecutor → FfmpegRenderPlan.

This module implements the E2E MVP path that extends the existing local
pipeline with the new Director layer.  It is an opt-in addition; the
existing ``prepare_local_review_package`` path is not modified.

Data flow
---------
::

    GPS events + resolved clips + evidence review
        ↓
    Scout  (to_universal_event per matched+confirmed clip)
        ↓
    UniversalEvent[]  — all events with source identity
        ↓
    confirmed filter  (evidence_confirmed=True only)
        ↓
    GeminiDirector  (standard path via FallbackDirector)
        ↓ GeminiDirectorError
    RuleBasedDirector  (automatic fallback)
        ↓
    DirectorScript
        ↓  persisted as local-director-script.json (optional)
    ScriptExecutor.execute(visual_evidence_confirmed_event_ids=…)
        ↓
    FfmpegRenderPlan  (READY_FOR_FFMPEG or NEEDS_HUMAN_REVIEW)

Privacy invariants
------------------
* ``to_universal_event`` never exposes latitude/longitude or file paths in
  the returned ``UniversalEvent``.
* ``GeminiDirector._sanitize_payload`` strips ``source_asset_id``,
  ``source_start_sec``, ``source_end_sec``, and all coordinate fields before
  forwarding to Gemini.
* The JSON artifact ``local-director-script.json`` written to disk retains
  ``source_asset_id`` and offsets for the Editor layer (local only, never
  sent externally).

Fail-closed conditions
----------------------
* Zero confirmed UniversalEvents → ``ValueError`` (Gemini is not called).
* No matching ``ResolvedCandidateClip`` for a scene clip → ``ValueError``.
* Source identity mismatch → ``ValueError``.
* Duplicate event_id in DirectorScript → ``ValueError``.
* ``FfmpegRenderPlan.status == NEEDS_HUMAN_REVIEW`` → pipeline stops and
  returns the plan for human inspection; rendering is not attempted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.director import (
    DirectorMetadata,
    DirectorScript,
    GeminiDirector,
    GeminiDirectorError,
    NarrativeArc,
    RuleBasedDirector,
    Scene,
    SceneClip,
)
from app.edit.render_plan import FfmpegRenderPlan, RenderPlanStatus
from app.executor import ScriptExecutor
from app.scout import UniversalEvent, to_universal_event

if TYPE_CHECKING:
    from app.contracts import GpsEvent
    from app.director import GeminiDirectorTransport
    from app.edit.candidate_planner import CandidateClip
    from app.video.catalog import ResolvedCandidateClip
    from app.video.review import LocalEvidenceReviewResult

DIRECTOR_SCRIPT_SCHEMA_VERSION = "director-script-v1"
_SUPPORTED_DIRECTOR_TRANSITIONS = frozenset({"cut"})
_PRIVATE_REPOSITORY_OUTPUT_ROOTS = (
    Path("private-media"),
    Path("data/private"),
    Path("media/private"),
)


@dataclass(frozen=True)
class DirectorPipelineResult:
    """Summary of a completed Director pipeline run."""

    universal_event_count: int
    confirmed_event_count: int
    composer: str          # "gemini" or "rule_based"
    fallback_used: bool
    scene_count: int
    used_event_count: int
    render_plan_status: str
    render_plan_ready: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "universal_event_count": self.universal_event_count,
            "confirmed_event_count": self.confirmed_event_count,
            "composer": self.composer,
            "fallback_used": self.fallback_used,
            "scene_count": self.scene_count,
            "used_event_count": self.used_event_count,
            "render_plan_status": self.render_plan_status,
            "render_plan_ready": self.render_plan_ready,
        }


def run_director_pipeline(
    gps_events: tuple[GpsEvent, ...],
    resolved_clips: tuple[ResolvedCandidateClip, ...],
    candidate_clips: tuple[CandidateClip, ...],
    review_result: LocalEvidenceReviewResult,
    *,
    gemini_transport: GeminiDirectorTransport | None = None,
    allow_external_director: bool = False,
    output_directory: Path | None = None,
    output_file_name: str = "ride-storyteller-director-film.mp4",
) -> tuple[DirectorPipelineResult, FfmpegRenderPlan, DirectorScript]:
    """Run the full Scout → Director → ScriptExecutor pipeline.

    Parameters
    ----------
    gps_events:
        All GPS events produced by ``extract_events`` / ``consolidate_events``.
    resolved_clips:
        All ``ResolvedCandidateClip`` objects from the existing catalog pass.
        Only MATCHED clips are used as source identity.
    candidate_clips:
        Corresponding ``CandidateClip`` objects used to derive
        ``evidence_status`` for ``to_universal_event``.
    review_result:
        Result of ``evaluate_local_evidence_review``; supplies the
        confirmed event_id allow-list for ``ScriptExecutor``.
    gemini_transport:
        Concrete ``GeminiDirectorTransport``.  When ``None``,
        only ``RuleBasedDirector`` is used (safe offline / test mode).
    allow_external_director:
        Must be ``True`` before a supplied Gemini transport may receive
        private-event-derived data. The default is fail-closed and makes no
        external call.
    output_directory:
        When supplied, ``local-director-script.json`` is written here.
    output_file_name:
        Forwarded to ``ScriptExecutor.execute`` / ``build_ffmpeg_render_plan``.

    Returns
    -------
    tuple of (DirectorPipelineResult, FfmpegRenderPlan, DirectorScript)

    Raises
    ------
    ValueError
        * If zero confirmed UniversalEvents are available.
        * If ScriptExecutor detects a source mismatch or missing clip.
    """
    from app.video.catalog import VideoMatchStatus

    # Input collections are joined by event_id below.  Reject duplicates
    # before building lookup dictionaries so a later item cannot silently
    # overwrite an earlier evidence decision or source identity.
    _require_unique_event_ids(
        "gps_events", tuple(event.event_id for event in gps_events)
    )
    _require_unique_event_ids(
        "resolved_clips", tuple(clip.event_id for clip in resolved_clips)
    )
    _require_unique_event_ids(
        "candidate_clips", tuple(clip.event_id for clip in candidate_clips)
    )

    # ------------------------------------------------------------------
    # 1. Scout: build UniversalEvent for every matched, evidence-decided clip
    # ------------------------------------------------------------------
    candidate_by_event: dict[str, CandidateClip] = {
        cc.event_id: cc for cc in candidate_clips
    }
    resolved_by_event: dict[str, ResolvedCandidateClip] = {
        rc.event_id: rc for rc in resolved_clips
    }
    gps_by_event: dict[str, GpsEvent] = {
        e.event_id: e for e in gps_events
    }

    universal_events: list[UniversalEvent] = []
    for rc in resolved_clips:
        if rc.status is not VideoMatchStatus.MATCHED:
            continue
        cc = candidate_by_event.get(rc.event_id)
        gps = gps_by_event.get(rc.event_id)
        if cc is None or gps is None:
            continue
        evt = to_universal_event(gps, candidate_clip=cc, resolved_clip=rc)
        universal_events.append(evt)

    # ------------------------------------------------------------------
    # 2. Confirmed filter (first line of defence)
    # ------------------------------------------------------------------
    confirmed_events = tuple(e for e in universal_events if e.evidence_confirmed)
    if not confirmed_events:
        raise ValueError(
            "Director pipeline: zero confirmed UniversalEvents — "
            "complete human visual evidence review before running the Director"
        )

    # ------------------------------------------------------------------
    # 3. Director (GeminiDirector → RuleBasedDirector fallback)
    # ------------------------------------------------------------------
    fallback_used = False
    composer: str

    if gemini_transport is not None and not allow_external_director:
        raise ValueError(
            "Director pipeline: external Gemini use requires "
            "allow_external_director=True"
        )
    if gemini_transport is not None:
        gemini_dir = GeminiDirector(gemini_transport)
        try:
            script = gemini_dir.compose(confirmed_events)
            composer = "gemini"
        except GeminiDirectorError:
            fallback_used = True
            script = RuleBasedDirector().compose(confirmed_events)
            composer = "rule_based"
    else:
        script = RuleBasedDirector().compose(confirmed_events)
        composer = "rule_based"

    # ------------------------------------------------------------------
    # 4. Persist DirectorScript artifact (optional)
    # ------------------------------------------------------------------
    if output_directory is not None:
        _validate_private_artifact_directory(output_directory)
        output_directory.mkdir(parents=True, exist_ok=True)
        artifact_path = output_directory / "local-director-script.json"
        artifact_path.write_text(
            json.dumps(
                _script_to_dict(script, resolved_by_event),
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # 5. ScriptExecutor → FfmpegRenderPlan (second line of defence)
    # ------------------------------------------------------------------
    plan = ScriptExecutor().execute(
        script,
        resolved_clips,
        visual_evidence_confirmed_event_ids=review_result.confirmed_event_ids,
        output_file_name=output_file_name,
    )

    result = DirectorPipelineResult(
        universal_event_count=len(universal_events),
        confirmed_event_count=len(confirmed_events),
        composer=composer,
        fallback_used=fallback_used,
        scene_count=len(script.scenes),
        used_event_count=script.metadata.event_count_used,
        render_plan_status=plan.status.value,
        render_plan_ready=(plan.status == RenderPlanStatus.READY_FOR_FFMPEG),
    )
    return result, plan, script


def _require_unique_event_ids(collection_name: str, event_ids: tuple[str, ...]) -> None:
    """Reject ambiguous event joins before any Director or artifact work."""
    if len(event_ids) != len(set(event_ids)):
        raise ValueError(
            f"Director pipeline: {collection_name} contains duplicate event_id values"
        )


def _validate_private_artifact_directory(output_directory: Path) -> None:
    """Forbid source-identifying artifacts under public repository paths."""
    repository_root = Path(__file__).resolve().parents[1]
    resolved_output = output_directory.resolve()
    try:
        relative = resolved_output.relative_to(repository_root)
    except ValueError:
        return
    if not any(
        relative == root or root in relative.parents
        for root in _PRIVATE_REPOSITORY_OUTPUT_ROOTS
    ):
        raise ValueError(
            "director artifacts inside the repository must use an ignored "
            "private-media directory"
        )


# ---------------------------------------------------------------------------
# Artifact serialization
# ---------------------------------------------------------------------------

def _script_to_dict(
    script: DirectorScript,
    resolved_by_event: dict[str, ResolvedCandidateClip],
) -> dict[str, object]:
    """Serialize a DirectorScript to a human-readable JSON artifact.

    Includes ``source_asset_id``, offsets, and ``file_name`` for the Editor
    layer.  This file is local-only and is never sent to Gemini or external
    services.
    """
    scenes_data = []
    for scene in script.scenes:
        clips_data = []
        for clip in scene.clips:
            rc = resolved_by_event.get(clip.event_id)
            clips_data.append({
                "event_id": clip.event_id,
                "source_asset_id": clip.source_asset_id,
                "source_start_sec": clip.source_start_sec,
                "source_end_sec": clip.source_end_sec,
                "file_name": rc.file_name if rc else None,
            })
        scenes_data.append({
            "scene_id": scene.scene_id,
            "scene_type": scene.scene_type.value,
            "transition_type": scene.transition_type,
            "overlay_text": scene.overlay_text,
            "clips": clips_data,
        })
    return {
        "schema_version": DIRECTOR_SCRIPT_SCHEMA_VERSION,
        "metadata": {
            "composer": script.metadata.composer,
            "event_count_in": script.metadata.event_count_in,
            "event_count_used": script.metadata.event_count_used,
            "arc_names": list(script.metadata.arc_names),
            "journey_coverage": script.metadata.journey_coverage.value,
        },
        "scenes": scenes_data,
    }


def load_private_director_script_artifact(path: Path) -> DirectorScript:
    """Load and validate a local-only DirectorScript artifact.

    The artifact retains source identity for the deterministic Editor.  This
    loader is deliberately not a browser-facing interface: its return value
    must stay in the private local execution path and is checked again by
    ``ScriptExecutor`` before rendering.
    """
    if path.is_symlink() or not path.is_file():
        raise ValueError("private DirectorScript artifact is unavailable")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("private DirectorScript artifact is unreadable") from error
    root = _artifact_mapping(raw, "artifact")
    _artifact_exact_keys(root, {"schema_version", "metadata", "scenes"}, "artifact")
    if root["schema_version"] != DIRECTOR_SCRIPT_SCHEMA_VERSION:
        raise ValueError("private DirectorScript artifact has an invalid schema version")

    raw_metadata = _artifact_mapping(root["metadata"], "artifact.metadata")
    metadata_keys = {"composer", "event_count_in", "event_count_used", "arc_names"}
    coverage_key = "journey_coverage"
    if frozenset(raw_metadata) not in (
        frozenset(metadata_keys),
        frozenset(metadata_keys | {coverage_key}),
    ):
        raise ValueError("private DirectorScript artifact has an invalid artifact.metadata")
    arc_names_raw = raw_metadata["arc_names"]
    if not isinstance(arc_names_raw, list) or not all(
        isinstance(value, str) and value for value in arc_names_raw
    ):
        raise ValueError("private DirectorScript artifact has invalid arc_names")
    try:
        from app.director import JourneyCoverage

        journey_coverage = JourneyCoverage(
            raw_metadata.get(coverage_key, JourneyCoverage.MIDDLE_OF_JOURNEY_ONLY.value)
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "private DirectorScript artifact has an invalid journey_coverage"
        ) from error
    metadata = DirectorMetadata(
        composer=_artifact_non_empty_string(raw_metadata["composer"], "composer"),
        event_count_in=_artifact_non_negative_int(
            raw_metadata["event_count_in"], "event_count_in"
        ),
        event_count_used=_artifact_non_negative_int(
            raw_metadata["event_count_used"], "event_count_used"
        ),
        arc_names=tuple(arc_names_raw),
        journey_coverage=journey_coverage,
    )

    raw_scenes = root["scenes"]
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("private DirectorScript artifact has no scenes")
    scenes: list[Scene] = []
    for scene_index, raw_scene in enumerate(raw_scenes):
        scene = _artifact_mapping(raw_scene, f"artifact.scenes[{scene_index}]")
        _artifact_exact_keys(
            scene,
            {"scene_id", "scene_type", "transition_type", "overlay_text", "clips"},
            f"artifact.scenes[{scene_index}]",
        )
        try:
            scene_type = NarrativeArc(
                _artifact_non_empty_string(scene["scene_type"], "scene_type")
            )
        except ValueError as error:
            raise ValueError("private DirectorScript artifact has an invalid scene_type") from error
        overlay_text = scene["overlay_text"]
        if overlay_text is not None and not isinstance(overlay_text, str):
            raise ValueError("private DirectorScript artifact has an invalid overlay_text")
        raw_clips = scene["clips"]
        if not isinstance(raw_clips, list) or not raw_clips:
            raise ValueError("private DirectorScript artifact has an empty scene")
        clips: list[SceneClip] = []
        for clip_index, raw_clip in enumerate(raw_clips):
            clip = _artifact_mapping(
                raw_clip, f"artifact.scenes[{scene_index}].clips[{clip_index}]"
            )
            _artifact_exact_keys(
                clip,
                {
                    "event_id",
                    "source_asset_id",
                    "source_start_sec",
                    "source_end_sec",
                    "file_name",
                },
                f"artifact.scenes[{scene_index}].clips[{clip_index}]",
            )
            file_name = clip["file_name"]
            if file_name is not None and not isinstance(file_name, str):
                raise ValueError("private DirectorScript artifact has an invalid file_name")
            clips.append(
                SceneClip(
                    event_id=_artifact_non_empty_string(clip["event_id"], "event_id"),
                    source_asset_id=_artifact_non_empty_string(
                        clip["source_asset_id"], "source_asset_id"
                    ),
                    source_start_sec=_artifact_non_negative_number(
                        clip["source_start_sec"], "source_start_sec"
                    ),
                    source_end_sec=_artifact_non_negative_number(
                        clip["source_end_sec"], "source_end_sec"
                    ),
                )
            )
        transition_type = _artifact_non_empty_string(
            scene["transition_type"], "transition_type"
        )
        if transition_type not in _SUPPORTED_DIRECTOR_TRANSITIONS:
            raise ValueError("private DirectorScript artifact has an invalid transition_type")
        scenes.append(
            Scene(
                scene_id=_artifact_non_empty_string(scene["scene_id"], "scene_id"),
                scene_type=scene_type,
                clips=tuple(clips),
                transition_type=transition_type,
                overlay_text=overlay_text,
            )
        )
    return DirectorScript(scenes=tuple(scenes), metadata=metadata)


def _artifact_mapping(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"private DirectorScript artifact has an invalid {field_name}")
    return value


def _artifact_exact_keys(
    value: dict[str, object], expected: set[str], field_name: str
) -> None:
    if set(value) != expected:
        raise ValueError(f"private DirectorScript artifact has an invalid {field_name}")


def _artifact_non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"private DirectorScript artifact has an invalid {field_name}")
    return value


def _artifact_non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"private DirectorScript artifact has an invalid {field_name}")
    return value


def _artifact_non_negative_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"private DirectorScript artifact has an invalid {field_name}")
    return float(value)
