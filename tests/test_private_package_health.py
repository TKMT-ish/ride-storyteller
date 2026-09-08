"""Synthetic-fixture tests for the Gate 1 private package health check."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.agents import StoryOutputLanguage
from app.edit import CandidateEvidenceStatus
from app.local_pipeline import LocalPipelineInputs
from app.private_package_health import (
    REASON_CLOCK_OFFSET_MISMATCH,
    REASON_EVIDENCE_AWAITING,
    REASON_EVIDENCE_REJECTED,
    REASON_NO_CONFIRMED_EVIDENCE,
    REASON_UNMATCHED_CLIPS,
    PrivatePackageHealthError,
    check_private_package_health,
)
from app.story_package import (
    JOURNEY_STORY_PLAN_FILE_NAME,
    JOURNEY_STORY_PLAN_SCHEMA_VERSION,
    JourneyStoryPlanError,
)
from app.video import (
    LocalEvidenceDecision,
    LocalEvidenceReview,
    ResolvedCandidateClip,
    VideoCatalog,
    VideoCatalogEntry,
    VideoMatchStatus,
    export_candidate_json,
    write_local_evidence_review,
)

_ASSET_ID = "asset-synthetic-1"
_OFFSET_S = 5.0
_TARGET_S = 60.0


def _clip(
    event_id: str,
    *,
    duration_s: float = 30.0,
    status: VideoMatchStatus = VideoMatchStatus.MATCHED,
) -> ResolvedCandidateClip:
    if status is not VideoMatchStatus.MATCHED:
        return ResolvedCandidateClip(
            chapter_id=f"chapter_{event_id}",
            event_id=event_id,
            status=status,
            asset_id=None,
            file_name=None,
            start_offset_s=None,
            end_offset_s=None,
            reason="synthetic unmatched",
        )
    return ResolvedCandidateClip(
        chapter_id=f"chapter_{event_id}",
        event_id=event_id,
        status=status,
        asset_id=_ASSET_ID,
        file_name="synthetic.mp4",
        start_offset_s=0.0,
        end_offset_s=duration_s,
        reason="synthetic matched",
    )


def _create_package(
    root: Path,
    *,
    clips: tuple[ResolvedCandidateClip, ...],
    statuses: dict[str, CandidateEvidenceStatus],
    catalog_offset_s: float = _OFFSET_S,
    target_duration_s: float = _TARGET_S,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    source_gpx = root / "synthetic.gpx"
    source_gpx.write_text("<gpx/>", encoding="utf-8")
    video_root = root / "videos"
    video_root.mkdir(exist_ok=True)

    inputs = LocalPipelineInputs(
        gpx_path=source_gpx.resolve(),
        video_root=video_root.resolve(),
        video_to_gps_offset_s=_OFFSET_S,
        target_duration_s=target_duration_s,
        output_language=StoryOutputLanguage.JAPANESE,
    )
    (root / "local-pipeline-inputs.json").write_text(
        json.dumps(inputs.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    catalog = VideoCatalog(
        entries=(
            VideoCatalogEntry(
                asset_id=_ASSET_ID,
                file_name="synthetic.mp4",
                recorded_start_time=datetime(2026, 1, 1, tzinfo=UTC),
                duration_s=600.0,
            ),
        ),
        video_to_gps_offset_s=catalog_offset_s,
    )
    (root / "local-video-catalog.json").write_text(
        json.dumps(catalog.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (root / "ride-storyteller-candidates.json").write_text(
        export_candidate_json(clips), encoding="utf-8"
    )
    write_local_evidence_review(
        root / "evidence-review.json",
        LocalEvidenceReview(
            tuple(
                LocalEvidenceDecision(
                    event_id=clip.event_id,
                    evidence_status=statuses[clip.event_id],
                    evidence_source=(
                        None
                        if statuses[clip.event_id]
                        is CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE
                        else "synthetic_decision"
                    ),
                )
                for clip in clips
            )
        ),
        overwrite=True,
    )
    return root


def _healthy_package(root: Path) -> Path:
    clips = (_clip("evt_a", duration_s=30.0), _clip("evt_b", duration_s=30.0))
    return _create_package(
        root,
        clips=clips,
        statuses={
            "evt_a": CandidateEvidenceStatus.CONFIRMED,
            "evt_b": CandidateEvidenceStatus.CONFIRMED,
        },
    )


def test_consistent_package_is_ready_with_no_blocking_reasons(tmp_path: Path) -> None:
    _healthy_package(tmp_path / "package")

    health = check_private_package_health(tmp_path / "package")

    assert health.is_ready is True
    assert health.blocking_reasons == ()
    assert health.clock_offset_confirmed is True
    assert health.confirmed_event_count == 2
    assert health.confirmed_duration_s == pytest.approx(60.0)
    assert health.film_duration_s == pytest.approx(60.0)


def test_summary_carries_counts_only_and_no_private_identifier(tmp_path: Path) -> None:
    _healthy_package(tmp_path / "package")

    payload = check_private_package_health(tmp_path / "package").to_dict()
    serialized = json.dumps(payload)

    assert payload["local_only"] is True
    assert payload["external_data_sent"] is False
    for forbidden in ("evt_a", "evt_b", _ASSET_ID, "synthetic.mp4", "synthetic.gpx", str(tmp_path)):
        assert forbidden not in serialized


def test_awaiting_evidence_blocks_readiness(tmp_path: Path) -> None:
    clips = (_clip("evt_a"), _clip("evt_b"))
    _create_package(
        tmp_path / "package",
        clips=clips,
        statuses={
            "evt_a": CandidateEvidenceStatus.CONFIRMED,
            "evt_b": CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE,
        },
    )

    health = check_private_package_health(tmp_path / "package")

    assert health.is_ready is False
    assert REASON_EVIDENCE_AWAITING in health.blocking_reasons
    assert health.awaiting_event_count == 1


def test_no_confirmed_evidence_blocks_readiness(tmp_path: Path) -> None:
    clips = (_clip("evt_a"),)
    _create_package(
        tmp_path / "package",
        clips=clips,
        statuses={"evt_a": CandidateEvidenceStatus.REJECTED},
    )

    health = check_private_package_health(tmp_path / "package")

    assert health.is_ready is False
    assert REASON_NO_CONFIRMED_EVIDENCE in health.blocking_reasons
    assert REASON_EVIDENCE_REJECTED in health.blocking_reasons


def test_clock_offset_mismatch_between_inputs_and_catalog_blocks_readiness(
    tmp_path: Path,
) -> None:
    clips = (_clip("evt_a", duration_s=60.0),)
    _create_package(
        tmp_path / "package",
        clips=clips,
        statuses={"evt_a": CandidateEvidenceStatus.CONFIRMED},
        catalog_offset_s=_OFFSET_S + 1.0,
    )

    health = check_private_package_health(tmp_path / "package")

    assert health.is_ready is False
    assert health.clock_offset_confirmed is False
    assert REASON_CLOCK_OFFSET_MISMATCH in health.blocking_reasons


def test_unmatched_and_rejected_clips_are_reported_without_blocking(tmp_path: Path) -> None:
    """Per the 2026-09-01 decision, a dropped event is reported, not fatal."""
    clips = (
        _clip("evt_a", duration_s=60.0),
        _clip("evt_b", status=VideoMatchStatus.NOT_FOUND),
        _clip("evt_c", duration_s=10.0),
    )
    _create_package(
        tmp_path / "package",
        clips=clips,
        statuses={
            "evt_a": CandidateEvidenceStatus.CONFIRMED,
            "evt_b": CandidateEvidenceStatus.REJECTED,
            "evt_c": CandidateEvidenceStatus.REJECTED,
        },
    )

    health = check_private_package_health(tmp_path / "package")

    assert health.is_ready is True
    assert REASON_UNMATCHED_CLIPS in health.blocking_reasons
    assert REASON_EVIDENCE_REJECTED in health.blocking_reasons
    assert health.unmatched_clip_count == 1
    assert health.rejected_event_count == 2
    # Only the confirmed, matched clip counts toward usable duration.
    assert health.confirmed_duration_s == pytest.approx(60.0)


def test_missing_package_directory_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(PrivatePackageHealthError, match="unavailable"):
        check_private_package_health(tmp_path / "missing")


def test_missing_required_export_fails_closed(tmp_path: Path) -> None:
    _healthy_package(tmp_path / "package")
    (tmp_path / "package" / "local-video-catalog.json").unlink()

    with pytest.raises(PrivatePackageHealthError, match="unavailable"):
        check_private_package_health(tmp_path / "package")


def test_symlinked_required_export_fails_closed(tmp_path: Path) -> None:
    _healthy_package(tmp_path / "package")
    real = tmp_path / "package" / "ride-storyteller-candidates.json"
    moved = tmp_path / "elsewhere.json"
    real.rename(moved)
    real.symlink_to(moved)

    with pytest.raises(PrivatePackageHealthError, match="unavailable"):
        check_private_package_health(tmp_path / "package")


def _write_story_plan(root: Path, *, total_screen_duration_s: float) -> None:
    """A minimal plan file: Gate 1 reads its totals, not its beats."""
    (root / JOURNEY_STORY_PLAN_FILE_NAME).write_text(
        json.dumps(
            {
                "schema_version": JOURNEY_STORY_PLAN_SCHEMA_VERSION,
                "output_language": StoryOutputLanguage.JAPANESE.value,
                "footage_screen_duration_s": 30.0,
                "total_screen_duration_s": total_screen_duration_s,
                "beats": [
                    {"kind": "footage", "screen_duration_s": 30.0, "event_id": "evt_a"},
                    {
                        "kind": "gap_card",
                        "screen_duration_s": total_screen_duration_s - 30.0,
                        "card": {
                            "kind": "before_first_clip",
                            "character": "departure",
                            "title": "旅の始まり",
                            "body": "15分 · 1.4km",
                            "screen_duration_s": total_screen_duration_s - 30.0,
                        },
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_a_package_without_a_plan_is_judged_on_footage_alone(tmp_path: Path) -> None:
    root = _create_package(
        tmp_path / "package",
        clips=(_clip("evt_a", duration_s=60.0),),
        statuses={"evt_a": CandidateEvidenceStatus.CONFIRMED},
    )

    health = check_private_package_health(root)

    assert health.has_story_plan is False
    assert health.film_duration_s == pytest.approx(health.confirmed_duration_s)
    assert health.to_dict()["duration"]["includes_chapter_cards"] is False


def test_a_corrupt_story_plan_fails_closed(tmp_path: Path) -> None:
    """A plan that cannot be trusted must not silently fall back to footage."""
    root = _healthy_package(tmp_path / "package")
    (root / JOURNEY_STORY_PLAN_FILE_NAME).write_text("{not json", encoding="utf-8")

    with pytest.raises(JourneyStoryPlanError):
        check_private_package_health(root)


def test_a_short_film_is_reported_but_never_blocks(tmp_path: Path) -> None:
    """The film's length follows its material, so a short one is information."""
    root = _create_package(
        tmp_path / "package",
        clips=(_clip("evt_a", duration_s=5.0),),
        statuses={"evt_a": CandidateEvidenceStatus.CONFIRMED},
    )

    health = check_private_package_health(root)

    assert health.is_ready is True
    assert health.blocking_reasons == ()
    assert health.film_duration_s == pytest.approx(5.0)


def test_a_planned_film_is_measured_whole(tmp_path: Path) -> None:
    root = _create_package(
        tmp_path / "package",
        clips=(_clip("evt_a", duration_s=30.0),),
        statuses={"evt_a": CandidateEvidenceStatus.CONFIRMED},
    )
    _write_story_plan(root, total_screen_duration_s=95.0)

    health = check_private_package_health(root)

    assert health.confirmed_duration_s == pytest.approx(30.0)
    assert health.film_duration_s == pytest.approx(95.0)
    assert health.has_story_plan is True
    assert health.to_dict()["duration"]["includes_chapter_cards"] is True
