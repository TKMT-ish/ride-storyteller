from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contracts import GpsEvent, Location, VideoQuery
from app.demo import build_demo_candidate_edit_plan, build_demo_story_inputs
from app.video import (
    VideoCatalog,
    VideoCatalogEntry,
    export_candidate_csv,
    export_candidate_json,
    load_resolved_candidate_export,
    resolve_candidate_clips,
    select_video_backed_events,
    write_candidate_exports,
)
from app.video.export import export_private_candidates


def _catalog() -> VideoCatalog:
    return VideoCatalog(
        entries=(
            VideoCatalogEntry(
                asset_id="gopro_001",
                file_name="GX010001.MP4",
                recorded_start_time=datetime(2026, 8, 10, 1, 42, tzinfo=UTC),
                duration_s=3_600,
            ),
        ),
        video_to_gps_offset_s=5,
    )


def _event(event_id: str, event_type: str, importance: float, minute: int) -> GpsEvent:
    timestamp = datetime(2026, 8, 10, 1, 42, tzinfo=UTC) + timedelta(minutes=minute)
    return GpsEvent(
        event_id=event_id,
        event_type=event_type,
        start_time=timestamp,
        end_time=timestamp,
        location=Location(-45.0, 168.0),
        importance_hint=importance,
        evidence=(event_type,),
        video_query=VideoQuery("local_catalog", 0, 30),
    )


def test_catalog_maps_event_by_corrected_clock_time() -> None:
    plan, _ = build_demo_candidate_edit_plan()
    _, events = build_demo_story_inputs()

    clips = resolve_candidate_clips(plan, events, _catalog())

    sample = next(clip for clip in clips if clip.event_id == "evt_sample_001")
    assert sample.status.value == "matched"
    assert sample.file_name == "GX010001.MP4"
    assert sample.start_offset_s == 0
    assert sample.end_offset_s == 30


def test_catalog_exports_json_and_csv_to_explicit_directory(tmp_path) -> None:  # type: ignore[no-untyped-def]
    plan, _ = build_demo_candidate_edit_plan()
    _, events = build_demo_story_inputs()
    clips = resolve_candidate_clips(plan, events, _catalog())

    json_path, csv_path = write_candidate_exports(tmp_path, clips)

    assert '"schema_version": "candidate-export-v1"' in export_candidate_json(clips)
    assert "chapter_id,event_id,status" in export_candidate_csv(clips)
    assert json_path.exists()
    assert csv_path.exists()
    assert load_resolved_candidate_export(json_path) == clips


def test_catalog_reports_not_found_without_inventing_a_source() -> None:
    plan, _ = build_demo_candidate_edit_plan()
    _, events = build_demo_story_inputs()
    missing_catalog = VideoCatalog(entries=())

    clips = resolve_candidate_clips(plan, events, missing_catalog)

    assert all(clip.status.value == "not_found" for clip in clips)
    assert all(clip.file_name is None for clip in clips)


def test_private_export_uses_explicit_output_directory(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        '{"entries":[{"asset_id":"gopro_001","file_name":"GX010001.MP4",'
        '"recorded_start_time":"2026-08-10T01:42:00Z","duration_s":3600}]}'
    )

    json_path, csv_path = export_private_candidates(
        Path("tests/fixtures/sample_route.xml"), catalog_path, tmp_path / "exports"
    )

    assert json_path.name == "ride-storyteller-candidates.json"
    assert csv_path.name == "ride-storyteller-candidates.csv"


def test_catalog_uses_half_open_intervals_at_back_to_back_file_boundary() -> None:
    plan, _ = build_demo_candidate_edit_plan()
    _, events = build_demo_story_inputs()
    sample = next(event for event in events if event.event_id == "evt_sample_001")
    boundary = datetime(2026, 8, 10, 2, 42, 5, tzinfo=UTC)
    shifted_events = tuple(
        replace(event, start_time=boundary, end_time=boundary)
        if event.event_id == sample.event_id
        else event
        for event in events
    )
    catalog = VideoCatalog(
        entries=(
            VideoCatalogEntry(
                "first", "GX010001.MP4", datetime(2026, 8, 10, 1, 42, tzinfo=UTC), 3600
            ),
            VideoCatalogEntry(
                "second", "GX010002.MP4", datetime(2026, 8, 10, 2, 42, tzinfo=UTC), 3600
            ),
        ),
        video_to_gps_offset_s=5,
    )

    clips = resolve_candidate_clips(plan, shifted_events, catalog)
    resolved = next(clip for clip in clips if clip.event_id == sample.event_id)

    assert resolved.asset_id == "second"
    assert resolved.start_offset_s == 0


def test_catalog_applies_negative_camera_to_gps_clock_offset() -> None:
    plan, _ = build_demo_candidate_edit_plan()
    _, events = build_demo_story_inputs()
    catalog = VideoCatalog(
        entries=(
            VideoCatalogEntry(
                asset_id="clock-ahead",
                file_name="GX010003.MP4",
                recorded_start_time=datetime(2026, 8, 10, 1, 42, 25, tzinfo=UTC),
                duration_s=60,
            ),
        ),
        video_to_gps_offset_s=-10,
    )

    clips = resolve_candidate_clips(plan, events, catalog)
    resolved = next(clip for clip in clips if clip.event_id == "evt_sample_001")

    assert resolved.asset_id == "clock-ahead"
    assert resolved.start_offset_s == 0
    assert resolved.end_offset_s == 30


def test_catalog_does_not_match_event_after_corrected_end_time() -> None:
    plan, _ = build_demo_candidate_edit_plan()
    _, events = build_demo_story_inputs()
    sample = next(event for event in events if event.event_id == "evt_sample_001")
    after_end = datetime(2026, 8, 10, 1, 43, 6, tzinfo=UTC)
    shifted_events = tuple(
        replace(event, start_time=after_end, end_time=after_end)
        if event.event_id == sample.event_id
        else event
        for event in events
    )
    catalog = VideoCatalog(
        entries=(
            VideoCatalogEntry(
                "short", "GX010004.MP4", datetime(2026, 8, 10, 1, 42, tzinfo=UTC), 60
            ),
        ),
        video_to_gps_offset_s=5,
    )

    clips = resolve_candidate_clips(plan, shifted_events, catalog)
    resolved = next(clip for clip in clips if clip.event_id == sample.event_id)

    assert resolved.status.value == "not_found"


def test_video_backed_selection_prefers_type_diversity_then_fills_duration() -> None:
    events = (
        _event("outside", "arrival_candidate", 1.0, 70),
        _event("speed_weak", "speed_change", 0.4, 10),
        _event("direction", "direction_change", 0.7, 20),
        _event("speed_strong", "speed_change", 0.9, 30),
        _event("stop", "stop", 0.6, 40),
    )

    selected = select_video_backed_events(events, _catalog(), target_duration_s=120)

    assert tuple(event.event_id for event in selected) == (
        "speed_weak",
        "direction",
        "speed_strong",
        "stop",
    )


def test_video_backed_selection_returns_empty_without_timestamp_coverage() -> None:
    selected = select_video_backed_events(
        (_event("outside", "departure", 0.8, 70),),
        _catalog(),
        target_duration_s=300,
    )

    assert selected == ()


def test_video_backed_selection_rejects_nonpositive_target_duration() -> None:
    with pytest.raises(ValueError, match="positive"):
        select_video_backed_events((), _catalog(), target_duration_s=0)
