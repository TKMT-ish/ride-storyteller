"""Synthetic-fixture tests for Gate 1 on a package judged from its footage.

The older package carries a candidate export; the newer one carries a
judgement and need not carry an export at all, which is the shape the cloud
path produces. These hold that the newer shape passes Gate 1 on its own
terms, and that the questions which no longer apply are not asked of it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.agents import StoryOutputLanguage
from app.analysis_record import (
    VIDEO_ANALYSIS_RECORD_FILE_NAME,
    AnalysedEvent,
    VideoAnalysisRecord,
    write_video_analysis_record,
)
from app.analysis_run import plan_analysis_run
from app.contracts import VideoAnalysis
from app.local_pipeline import LocalPipelineInputs
from app.private_package_health import (
    REASON_CLOCK_OFFSET_MISMATCH,
    REASON_JUDGEMENT_UNBOUGHT,
    REASON_NO_JUDGED_FOOTAGE,
    PrivatePackageHealthError,
    check_private_package_health,
)
from app.video import VideoCatalog, VideoCatalogEntry

_ASSET_ID = "asset-synthetic-1"
_RIDE_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _gpx(path: Path, *, span_s: float = 4 * 3600.0, point_count: int = 60) -> Path:
    step = span_s / (point_count - 1)
    points = "".join(
        '<trkpt lat="{lat:.6f}" lon="{lon:.6f}"><ele>100</ele><time>{t}</time></trkpt>'.format(
            lat=35.0 + 0.001 * index,
            lon=139.0 + 0.001 * index,
            t=(_RIDE_START + timedelta(seconds=step * index)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        for index in range(point_count)
    )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="t" '
        'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        + points
        + "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    return path


def _package(root: Path, *, catalog_offset_s: float = 0.0) -> Path:
    """Inputs and a catalogue only: no candidate export, no evidence review."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "synthetic.mp4").write_bytes(b"a recording")
    inputs = LocalPipelineInputs(
        gpx_path=_gpx(root / "ride.gpx").resolve(),
        video_root=root.resolve(),
        video_to_gps_offset_s=0.0,
        target_duration_s=300.0,
        output_language=StoryOutputLanguage.JAPANESE,
    )
    (root / "local-pipeline-inputs.json").write_text(
        json.dumps(inputs.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    catalog = VideoCatalog(
        entries=(
            VideoCatalogEntry(
                asset_id=_ASSET_ID,
                file_name="synthetic.mp4",
                recorded_start_time=_RIDE_START + timedelta(seconds=600),
                duration_s=120.0,
            ),
        ),
        video_to_gps_offset_s=catalog_offset_s,
    )
    (root / "local-video-catalog.json").write_text(
        json.dumps(catalog.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    return root


def _judge(package: Path, *, provider: str = "gemini", count: int | None = None) -> None:
    plan = plan_analysis_run(package)
    chosen = plan.watched_candidates if count is None else plan.watched_candidates[:count]
    write_video_analysis_record(
        package / VIDEO_ANALYSIS_RECORD_FILE_NAME,
        VideoAnalysisRecord(
            tuple(
                AnalysedEvent(
                    event_id=c.event_id,
                    analysis=VideoAnalysis(
                        asset_id=c.asset_id,
                        start_offset_s=c.start_offset_s,
                        end_offset_s=c.end_offset_s,
                        visual_description="a road",
                        road_type="highway",
                        scenery_tags=("sky",),
                        weather_visible="clear",
                        visual_interest_score=0.6,
                        story_relevance_score=0.7,
                        confidence=0.9,
                        analysis_provider=provider,
                    ),
                )
                for c in chosen
            )
        ),
        overwrite=True,
    )


def test_a_package_with_neither_export_nor_judgement_cannot_be_read(tmp_path: Path) -> None:
    with pytest.raises(PrivatePackageHealthError, match="export is unavailable"):
        check_private_package_health(_package(tmp_path / "package"))


def test_a_judged_package_needs_no_export_to_pass_gate_one(tmp_path: Path) -> None:
    """The shape the cloud path produces."""
    package = _package(tmp_path / "package")
    _judge(package)

    health = check_private_package_health(package)

    assert health.is_ready is True
    assert health.blocking_reasons == ()
    assert health.candidate_clip_count == health.confirmed_event_count > 0
    assert health.awaiting_event_count == 0
    assert health.rejected_event_count == 0


def test_the_judged_footage_is_what_is_counted(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _judge(package, count=3)

    health = check_private_package_health(package)

    assert health.candidate_clip_count == 3
    assert health.confirmed_duration_s == pytest.approx(36.0)
    assert health.film_duration_s == pytest.approx(36.0)
    assert health.has_story_plan is False


def test_a_judgement_nobody_bought_blocks_the_gate(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _judge(package, provider="stub-dry-run")

    health = check_private_package_health(package)

    assert health.is_ready is False
    assert health.blocking_reasons == (REASON_JUDGEMENT_UNBOUGHT,)


def test_a_judgement_of_nothing_blocks_the_gate(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _judge(package, count=0)

    health = check_private_package_health(package)

    assert health.is_ready is False
    assert health.blocking_reasons == (REASON_NO_JUDGED_FOOTAGE,)


def test_the_clock_still_has_to_agree(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", catalog_offset_s=30.0)
    _judge(package)

    health = check_private_package_health(package)

    assert health.is_ready is False
    assert REASON_CLOCK_OFFSET_MISMATCH in health.blocking_reasons
    assert health.clock_offset_confirmed is False


def test_an_unreadable_judgement_is_an_error_not_a_pass(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    (package / VIDEO_ANALYSIS_RECORD_FILE_NAME).write_text("not json", encoding="utf-8")

    with pytest.raises(PrivatePackageHealthError, match="judgement is unavailable"):
        check_private_package_health(package)


def test_the_summary_still_carries_no_identifier(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _judge(package)
    plan = plan_analysis_run(package)

    serialized = json.dumps(check_private_package_health(package).to_dict())

    for forbidden in (str(tmp_path), "synthetic.mp4", _ASSET_ID, plan.candidates[0].event_id):
        assert forbidden not in serialized


def test_the_film_command_gate_accepts_a_judged_package(tmp_path: Path) -> None:
    """The gate the film command asks, on the package the cloud path makes."""
    from app.private_journey_film import BLOCKING_REASONS

    package = _package(tmp_path / "package")
    _judge(package)

    health = check_private_package_health(package)

    assert health.is_ready
    assert not (set(health.blocking_reasons) & BLOCKING_REASONS)
