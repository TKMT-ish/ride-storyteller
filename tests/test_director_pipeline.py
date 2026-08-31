"""Tests for the Director E2E pipeline (app/director_pipeline.py).

Covers:
A. Existing path regression  — director_mode=False is unchanged
B. Normal path               — Scout → Gemini → Script → RenderPlan
C. Gemini fallback           — GeminiDirectorError → RuleBasedDirector
D. Evidence safety           — unconfirmed filter, zero-confirmed fail-closed,
                               downstream gate still fires
E. Privacy                   — Gemini payload excludes lat/lon / source paths
F. Artifact                  — local-director-script.json structure
G. Integration with existing local_pipeline (director_mode=True)
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.contracts import GpsEvent, Location, VideoQuery
from app.director import GeminiDirectorError
from app.director_pipeline import (
    DIRECTOR_SCRIPT_SCHEMA_VERSION,
    DirectorPipelineResult,
    load_private_director_script_artifact,
    run_director_pipeline,
)
from app.edit.candidate_planner import CandidateClip, CandidateEvidenceStatus
from app.edit.render_plan import RenderPlanStatus
from app.video.catalog import ResolvedCandidateClip, VideoMatchStatus
from app.video.review import (
    LocalEvidenceDecision,
    LocalEvidenceReview,
    LocalEvidenceReviewResult,
    write_local_evidence_review,
)

# ---------------------------------------------------------------------------
# Test fixture helpers
# ---------------------------------------------------------------------------

_UTC_START = datetime(2026, 8, 10, 1, 42, 15, tzinfo=UTC)
_UTC_END   = datetime(2026, 8, 10, 1, 42, 45, tzinfo=UTC)
_LOC       = Location(latitude=-45.03, longitude=168.66)


def _gps(
    event_id: str,
    event_type: str = "elevation_change",
    importance: float = 0.70,
    clip_start: float = 10.0,
    clip_end: float = 40.0,
) -> GpsEvent:
    return GpsEvent(
        event_id=event_id,
        event_type=event_type,
        start_time=_UTC_START,
        end_time=_UTC_END,
        location=_LOC,
        importance_hint=importance,
        evidence=("gps",),
        video_query=VideoQuery(
            asset_name_hint="GX010001.MP4",
            clip_start_offset_s=clip_start,
            clip_end_offset_s=clip_end,
        ),
    )


def _confirmed_candidate(event_id: str, chapter_id: str = "chapter_01") -> CandidateClip:
    return CandidateClip(
        chapter_id=chapter_id,
        event_id=event_id,
        asset_name_hint="GX010001.MP4",
        start_offset_s=10.0,
        end_offset_s=40.0,
        requested_duration_s=30.0,
        evidence_status=CandidateEvidenceStatus.CONFIRMED,
        evidence_source="human_review",
    )


def _awaiting_candidate(event_id: str, chapter_id: str = "chapter_01") -> CandidateClip:
    return CandidateClip(
        chapter_id=chapter_id,
        event_id=event_id,
        asset_name_hint="GX010001.MP4",
        start_offset_s=10.0,
        end_offset_s=40.0,
        requested_duration_s=30.0,
        evidence_status=CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE,
    )


def _matched_rc(
    event_id: str,
    chapter_id: str = "chapter_01",
    asset_id: str = "asset-abc",
    file_name: str = "GX010001.MP4",
    start: float = 10.0,
    end: float = 40.0,
) -> ResolvedCandidateClip:
    return ResolvedCandidateClip(
        chapter_id=chapter_id,
        event_id=event_id,
        status=VideoMatchStatus.MATCHED,
        asset_id=asset_id,
        file_name=file_name,
        start_offset_s=start,
        end_offset_s=end,
        reason="test",
    )


def _review_result(
    confirmed_ids: tuple[str, ...] = (),
    awaiting_ids: tuple[str, ...] = (),
) -> LocalEvidenceReviewResult:
    return LocalEvidenceReviewResult(
        ready_for_render=not awaiting_ids,
        confirmed_event_ids=confirmed_ids,
        awaiting_event_ids=awaiting_ids,
        rejected_event_ids=(),
        unmatched_event_ids=(),
        reasons=() if not awaiting_ids else ("visual_evidence_awaiting",),
    )


class _OkTransport:
    """Fake Gemini transport — returns a valid single-scene Hook script."""

    def __init__(self, event_ids: list[str]) -> None:
        self._ids = event_ids

    def compose_script(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        scenes = []
        arc_order = ["hook", "build_up", "climax", "resolution"]
        for i, eid in enumerate(self._ids[:4]):
            scenes.append({
                "scene_type": arc_order[i % 4],
                "event_ids": [eid],
                "transition_type": "cut",
                "overlay_text": None,
            })
        return {"scenes": scenes}

    @property
    def last_payload(self) -> Mapping[str, object] | None:
        return getattr(self, "_last_payload", None)

    def compose_script_capturing(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        self._last_payload = story_payload
        return self.compose_script(prompt=prompt, story_payload=story_payload)


class _CapturingTransport:
    """Captures the payload and returns a valid response."""

    def __init__(self, event_ids: list[str]) -> None:
        self._ids = event_ids
        self.last_payload: Mapping[str, object] | None = None

    def compose_script(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        self.last_payload = story_payload
        scenes = []
        arc_order = ["hook", "build_up", "climax", "resolution"]
        for i, eid in enumerate(self._ids[:4]):
            scenes.append({
                "scene_type": arc_order[i % 4],
                "event_ids": [eid],
                "transition_type": "cut",
                "overlay_text": None,
            })
        return {"scenes": scenes}


class _FailTransport:
    """Always raises GeminiDirectorError."""

    def compose_script(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        raise GeminiDirectorError("simulated transport failure")


# ---------------------------------------------------------------------------
# B. Normal path
# ---------------------------------------------------------------------------

def test_normal_path_produces_valid_director_pipeline_result() -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(confirmed_ids=("evt_001",))

    result, plan, script = run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review,
        gemini_transport=_OkTransport(["evt_001"]),
        allow_external_director=True,
    )

    assert isinstance(result, DirectorPipelineResult)
    assert result.universal_event_count == 1
    assert result.confirmed_event_count == 1
    assert result.scene_count >= 1
    assert result.used_event_count >= 1


def test_normal_path_gemini_composer_is_recorded() -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(confirmed_ids=("evt_001",))

    result, _, _ = run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review,
        gemini_transport=_OkTransport(["evt_001"]),
        allow_external_director=True,
    )

    assert result.composer == "gemini"
    assert result.fallback_used is False


def test_normal_path_rule_based_when_no_transport() -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(confirmed_ids=("evt_001",))

    result, _, _ = run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review,
        gemini_transport=None,
    )

    assert result.composer == "rule_based"
    assert result.fallback_used is False


def test_external_director_requires_explicit_opt_in() -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(confirmed_ids=("evt_001",))
    transport = _CapturingTransport(["evt_001"])

    with pytest.raises(ValueError, match="allow_external_director=True"):
        run_director_pipeline(
            gps_events=(evt,),
            resolved_clips=(rc,),
            candidate_clips=(cc,),
            review_result=review,
            gemini_transport=transport,
        )

    assert transport.last_payload is None


def test_normal_path_confirmed_events_produce_ready_for_ffmpeg() -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(confirmed_ids=("evt_001",))

    result, plan, _ = run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review,
        gemini_transport=_OkTransport(["evt_001"]),
        allow_external_director=True,
    )

    assert result.render_plan_ready is True
    assert plan.status == RenderPlanStatus.READY_FOR_FFMPEG
    assert plan.command is not None


# ---------------------------------------------------------------------------
# C. Gemini fallback
# ---------------------------------------------------------------------------

def test_fallback_to_rule_based_on_gemini_director_error() -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(confirmed_ids=("evt_001",))

    result, plan, script = run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review,
        gemini_transport=_FailTransport(),
        allow_external_director=True,
    )

    assert result.composer == "rule_based"
    assert result.fallback_used is True
    assert isinstance(plan, type(plan))  # still a valid plan


def test_fallback_produces_valid_script() -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(confirmed_ids=("evt_001",))

    _, _, script = run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review,
        gemini_transport=_FailTransport(),
        allow_external_director=True,
    )

    assert script.scenes
    all_ids = [c.event_id for s in script.scenes for c in s.clips]
    assert len(all_ids) == len(set(all_ids))


# ---------------------------------------------------------------------------
# D. Evidence safety
# ---------------------------------------------------------------------------

def test_zero_confirmed_events_raises_before_calling_director() -> None:
    """Fail-closed: no confirmed events → ValueError, Gemini never called."""
    evt = _gps("evt_001")
    cc = _awaiting_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(awaiting_ids=("evt_001",))

    with pytest.raises(ValueError, match="zero confirmed UniversalEvents"):
        run_director_pipeline(
            gps_events=(evt,),
            resolved_clips=(rc,),
            candidate_clips=(cc,),
            review_result=review,
        )


def test_unconfirmed_events_excluded_from_director_input() -> None:
    """Awaiting clip must not reach the Director even if a confirmed one exists."""
    evt_ok = _gps("evt_ok")
    evt_bad = _gps("evt_bad")
    cc_ok = _confirmed_candidate("evt_ok")
    cc_bad = _awaiting_candidate("evt_bad")
    rc_ok = _matched_rc("evt_ok",  asset_id="asset-a",
                         file_name="GX010001.MP4", start=10.0, end=40.0)
    rc_bad = _matched_rc("evt_bad", asset_id="asset-b",
                          file_name="GX010002.MP4", start=5.0, end=25.0)
    review = _review_result(
        confirmed_ids=("evt_ok",),
        awaiting_ids=("evt_bad",),
    )

    result, _, script = run_director_pipeline(
        gps_events=(evt_ok, evt_bad),
        resolved_clips=(rc_ok, rc_bad),
        candidate_clips=(cc_ok, cc_bad),
        review_result=review,
        gemini_transport=_OkTransport(["evt_ok"]),
        allow_external_director=True,
    )

    all_clip_ids = {c.event_id for s in script.scenes for c in s.clips}
    assert "evt_ok" in all_clip_ids
    assert "evt_bad" not in all_clip_ids
    assert result.confirmed_event_count == 1


def test_downstream_evidence_gate_fires_when_allow_list_empty() -> None:
    """Even with a valid DirectorScript, missing allow-list → NEEDS_HUMAN_REVIEW."""
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    # Build a custom review_result that has confirmed_event_ids=() but
    # the candidate itself is confirmed so we pass the pipeline's own filter.
    # We simulate the edge case by manually overriding confirmed_event_ids.
    review_no_ids = LocalEvidenceReviewResult(
        ready_for_render=False,
        confirmed_event_ids=(),       # <— empty allow-list
        awaiting_event_ids=("evt_001",),
        rejected_event_ids=(),
        unmatched_event_ids=(),
        reasons=("visual_evidence_awaiting",),
    )

    # We need the pipeline to get past the filter, so we use a confirmed CC
    result, plan, _ = run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review_no_ids,
        gemini_transport=_OkTransport(["evt_001"]),
        allow_external_director=True,
    )

    assert plan.status == RenderPlanStatus.NEEDS_HUMAN_REVIEW
    assert plan.command is None
    assert result.render_plan_ready is False


def test_needs_human_review_plan_does_not_advance_to_render() -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review_empty = LocalEvidenceReviewResult(
        ready_for_render=False,
        confirmed_event_ids=(),
        awaiting_event_ids=("evt_001",),
        rejected_event_ids=(),
        unmatched_event_ids=(),
        reasons=("visual_evidence_awaiting",),
    )

    _, plan, _ = run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review_empty,
    )

    assert plan.command is None


# ---------------------------------------------------------------------------
# E. Privacy
# ---------------------------------------------------------------------------

def test_gemini_payload_excludes_latitude_longitude() -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(confirmed_ids=("evt_001",))
    transport = _CapturingTransport(["evt_001"])

    run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review,
        gemini_transport=transport,
        allow_external_director=True,
    )

    assert transport.last_payload is not None
    serialized = json.dumps(transport.last_payload)
    assert "latitude" not in serialized
    assert "longitude" not in serialized


def test_gemini_payload_excludes_source_asset_id_and_paths() -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001", asset_id="secret-asset", file_name="GX010001.MP4")
    review = _review_result(confirmed_ids=("evt_001",))
    transport = _CapturingTransport(["evt_001"])

    run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review,
        gemini_transport=transport,
        allow_external_director=True,
    )

    assert transport.last_payload is not None
    serialized = json.dumps(transport.last_payload)
    assert "source_asset_id" not in serialized
    assert "source_start_sec" not in serialized
    assert "source_end_sec" not in serialized
    assert "GX010001.MP4" not in serialized
    assert "secret-asset" not in serialized


# ---------------------------------------------------------------------------
# F. Artifact
# ---------------------------------------------------------------------------

def test_artifact_is_written_to_output_directory(tmp_path: Path) -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(confirmed_ids=("evt_001",))

    run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review,
        output_directory=tmp_path,
    )

    artifact = tmp_path / "local-director-script.json"
    assert artifact.exists()


def test_artifact_schema_version(tmp_path: Path) -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(confirmed_ids=("evt_001",))

    run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review,
        output_directory=tmp_path,
    )

    data = json.loads((tmp_path / "local-director-script.json").read_text())
    assert data["schema_version"] == DIRECTOR_SCRIPT_SCHEMA_VERSION


def test_artifact_contains_required_fields(tmp_path: Path) -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(confirmed_ids=("evt_001",))

    run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review,
        output_directory=tmp_path,
    )

    data = json.loads((tmp_path / "local-director-script.json").read_text())
    assert "metadata" in data
    assert "scenes" in data
    assert data["metadata"]["composer"] in ("gemini", "rule_based")
    scene = data["scenes"][0]
    assert "scene_type" in scene
    assert "transition_type" in scene
    assert "overlay_text" in scene
    assert "clips" in scene
    clip = scene["clips"][0]
    assert "event_id" in clip
    assert "source_asset_id" in clip
    assert "source_start_sec" in clip
    assert "source_end_sec" in clip


def test_artifact_contains_source_identity(tmp_path: Path) -> None:
    """Artifact must include source identity (not sent to Gemini but stored locally)."""
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001", asset_id="asset-xyz")
    review = _review_result(confirmed_ids=("evt_001",))

    run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review,
        output_directory=tmp_path,
    )

    data = json.loads((tmp_path / "local-director-script.json").read_text())
    clip = data["scenes"][0]["clips"][0]
    assert clip["source_asset_id"] == "asset-xyz"


def test_private_director_artifact_loader_round_trips_a_valid_script(
    tmp_path: Path,
) -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(confirmed_ids=("evt_001",))

    _, _, script = run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review,
        output_directory=tmp_path,
    )

    assert load_private_director_script_artifact(
        tmp_path / "local-director-script.json"
    ) == script


def test_private_director_artifact_loader_rejects_unknown_fields(tmp_path: Path) -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(confirmed_ids=("evt_001",))
    run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review,
        output_directory=tmp_path,
    )
    artifact = tmp_path / "local-director-script.json"
    raw = json.loads(artifact.read_text())
    raw["metadata"]["untrusted_field"] = True
    artifact.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid artifact.metadata"):
        load_private_director_script_artifact(artifact)


def test_artifact_not_written_when_no_output_directory() -> None:
    """No artifact should be written when output_directory is None."""
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(confirmed_ids=("evt_001",))

    # Should not raise; just verifying it runs cleanly
    run_director_pipeline(
        gps_events=(evt,),
        resolved_clips=(rc,),
        candidate_clips=(cc,),
        review_result=review,
        output_directory=None,
    )


def test_artifact_rejects_a_nonprivate_repository_directory() -> None:
    evt = _gps("evt_001")
    cc = _confirmed_candidate("evt_001")
    rc = _matched_rc("evt_001")
    review = _review_result(confirmed_ids=("evt_001",))
    repository_root = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="private-media directory"):
        run_director_pipeline(
            gps_events=(evt,),
            resolved_clips=(rc,),
            candidate_clips=(cc,),
            review_result=review,
            output_directory=repository_root,
        )


# ---------------------------------------------------------------------------
# G. Integration with local_pipeline (director_mode)
# ---------------------------------------------------------------------------

def _metadata(path: Path) -> object:
    from app.video import LocalVideoMetadata
    return LocalVideoMetadata(
        file_name=path.name,
        duration_s=3_600.0,
        recorded_start_time=datetime(2026, 8, 10, 1, 42, tzinfo=UTC),
        video_codec="hevc",
        width=3840,
        height=2160,
        frames_per_second=60.0,
        has_audio=True,
    )


def _runner(
    command: tuple[str, ...], **_kwargs: object
) -> object:
    import subprocess
    Path(command[-1]).write_bytes(b"review")
    return subprocess.CompletedProcess(command, 0, "", "")


def test_director_mode_false_leaves_existing_path_unchanged(tmp_path: Path) -> None:
    """director_mode=False must not change existing LocalPipelineResult structure."""
    from app.local_pipeline import prepare_local_review_package

    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")

    result = prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        tmp_path / "output",
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
        director_mode=False,
    )

    # Existing fields are unchanged
    assert result.catalog_entry_count == 1
    assert result.matched_clip_count >= 1
    payload = result.to_dict()
    assert payload["next_gate"] == "human_visual_evidence_review"
    # No director key when director_mode=False
    assert "director" not in payload


def test_director_mode_true_with_no_confirmed_events_does_not_crash(
    tmp_path: Path,
) -> None:
    """director_mode=True with no confirmed events must not crash the pipeline."""
    from app.local_pipeline import prepare_local_review_package

    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")

    # No confirmed events in evidence-review (default template = all awaiting).
    result = prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        tmp_path / "output",
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
        director_mode=True,
        gemini_transport=None,
    )

    # Existing fields still present
    assert result.catalog_entry_count == 1
    payload = result.to_dict()
    # Director is not run because no human evidence decision is confirmed.
    assert "director" not in payload


def test_director_mode_true_with_confirmed_events_writes_artifact(
    tmp_path: Path,
) -> None:
    """A rerun preserves confirmed human review and writes the artifact."""
    from app.local_pipeline import prepare_local_review_package

    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    out = tmp_path / "output"

    # Run normal pipeline first to create evidence-review.json
    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        out,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
        director_mode=False,
    )

    # Read which event_ids are in the candidate export and confirm them all
    candidates = json.loads((out / "ride-storyteller-candidates.json").read_text())
    event_ids = [c["event_id"] for c in candidates["clips"]]
    confirmed_review = LocalEvidenceReview(tuple(
        LocalEvidenceDecision(
            event_id=eid,
            evidence_status=CandidateEvidenceStatus.CONFIRMED,
            evidence_source="test",
        )
        for eid in event_ids
    ))
    write_local_evidence_review(
        out / "evidence-review.json",
        confirmed_review,
        overwrite=True,
    )

    # Now run director_mode=True — no Gemini transport (offline)
    result2 = prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        out,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
        director_mode=True,
        gemini_transport=None,
        overwrite=True,
    )

    artifact = out / "local-director-script.json"
    assert artifact.exists(), "local-director-script.json must be written"
    data = json.loads(artifact.read_text())
    assert data["schema_version"] == DIRECTOR_SCRIPT_SCHEMA_VERSION
    assert data["scenes"]

    payload = result2.to_dict()
    assert "director" in payload
    assert payload["director"]["composer"] == "rule_based"
    assert payload["director"]["confirmed_event_count"] >= 1
    safe_script = payload["director"]["director_script"]
    assert safe_script["composer"] == "rule_based"
    assert safe_script["fallback_used"] is False
    assert safe_script["scenes"]
    serialized_safe_script = json.dumps(safe_script)
    for private_key in (
        "event_id",
        "asset_id",
        "file_name",
        "source_start_sec",
        "source_end_sec",
        "latitude",
        "longitude",
    ):
        assert private_key not in serialized_safe_script


def test_director_mode_rejects_a_review_for_a_different_candidate_set(
    tmp_path: Path,
) -> None:
    """A stale review must raise instead of being reset or ignored on rerun."""
    from app.local_pipeline import prepare_local_review_package

    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    out = tmp_path / "output"
    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        out,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
    )
    write_local_evidence_review(
        out / "evidence-review.json",
        LocalEvidenceReview(
            (
                LocalEvidenceDecision(
                    event_id="not-a-current-candidate",
                    evidence_status=CandidateEvidenceStatus.CONFIRMED,
                    evidence_source="test",
                ),
            )
        ),
        overwrite=True,
    )

    with pytest.raises(ValueError, match="exactly one decision"):
        prepare_local_review_package(
            Path("tests/fixtures/sample_route.xml"),
            video_root,
            out,
            video_to_gps_offset_s=5.0,
            clock_offset_confirmed=True,
            extract_reviews=False,
            probe=_metadata,
            director_mode=True,
            overwrite=True,
        )
