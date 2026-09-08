"""Synthetic-fixture tests for keeping what the model said about a ride."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.analysis_record import (
    VIDEO_ANALYSIS_RECORD_SCHEMA_VERSION,
    AnalysedEvent,
    VideoAnalysisRecord,
    VideoAnalysisRecordError,
    load_video_analysis_record,
    write_video_analysis_record,
)
from app.contracts import VideoAnalysis


def _analysis(*, interest: float = 0.8) -> VideoAnalysis:
    return VideoAnalysis(
        asset_id="asset-synthetic-1",
        start_offset_s=1_800.0,
        end_offset_s=1_812.0,
        visual_description="A road climbing through trees",
        road_type="mountain road",
        scenery_tags=("trees", "sky"),
        weather_visible="clear",
        visual_interest_score=interest,
        story_relevance_score=0.7,
        confidence=0.9,
        analysis_provider="gemini",
    )


def _record() -> VideoAnalysisRecord:
    return VideoAnalysisRecord(
        (
            AnalysedEvent(event_id="evt_0", analysis=_analysis()),
            AnalysedEvent(event_id="evt_1", analysis=_analysis(interest=0.4)),
        )
    )


def test_a_record_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "gemini-video-analysis.json"

    write_video_analysis_record(path, _record())

    assert load_video_analysis_record(path) == _record()


def test_a_record_keeps_what_the_model_said_not_just_the_verdict(tmp_path: Path) -> None:
    """A selection can only be argued with if its evidence can be read back."""
    path = tmp_path / "record.json"
    write_video_analysis_record(path, _record())

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == VIDEO_ANALYSIS_RECORD_SCHEMA_VERSION
    assert payload["analysed_count"] == 2
    first = payload["analysed"][0]
    assert first["visual_description"] == "A road climbing through trees"
    assert first["visual_interest_score"] == pytest.approx(0.8)
    assert first["confidence"] == pytest.approx(0.9)


def test_a_record_finds_one_event_and_admits_when_it_has_none() -> None:
    record = _record()

    assert record.analysis_for("evt_0") is not None
    assert record.analysis_for("evt_missing") is None


def test_a_record_must_not_judge_one_event_twice() -> None:
    with pytest.raises(ValueError, match="judge one event twice"):
        VideoAnalysisRecord(
            (
                AnalysedEvent(event_id="evt_0", analysis=_analysis()),
                AnalysedEvent(event_id="evt_0", analysis=_analysis()),
            )
        )


def test_an_analysed_event_needs_its_event() -> None:
    with pytest.raises(ValueError, match="needs its event"):
        AnalysedEvent(event_id="", analysis=_analysis())


def test_a_missing_or_malformed_record_is_refused(tmp_path: Path) -> None:
    with pytest.raises(VideoAnalysisRecordError, match="unavailable"):
        load_video_analysis_record(tmp_path / "absent.json")

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(VideoAnalysisRecordError, match="unreadable"):
        load_video_analysis_record(broken)

    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"schema_version": "v0", "analysed": []}), encoding="utf-8")
    with pytest.raises(VideoAnalysisRecordError, match="unsupported"):
        load_video_analysis_record(wrong)

    partial = tmp_path / "partial.json"
    partial.write_text(
        json.dumps(
            {
                "schema_version": VIDEO_ANALYSIS_RECORD_SCHEMA_VERSION,
                "analysed": [{"event_id": "evt_0"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(VideoAnalysisRecordError, match="malformed"):
        load_video_analysis_record(partial)


def test_a_symlinked_record_is_refused_for_reading_and_writing(tmp_path: Path) -> None:
    real = tmp_path / "record.json"
    write_video_analysis_record(real, _record())
    link = tmp_path / "link.json"
    link.symlink_to(real)

    with pytest.raises(VideoAnalysisRecordError, match="unavailable"):
        load_video_analysis_record(link)
    with pytest.raises(VideoAnalysisRecordError, match="unsafe"):
        write_video_analysis_record(link, _record())


def test_writing_over_a_record_needs_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    write_video_analysis_record(path, _record())

    with pytest.raises(FileExistsError):
        write_video_analysis_record(path, _record(), overwrite=False)


def test_a_failed_write_leaves_no_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "record.json"

    class Unserialisable:
        pass

    record = _record()
    object.__setattr__(record, "analysed", Unserialisable())
    with pytest.raises(Exception):
        write_video_analysis_record(path, record)

    assert list(tmp_path.iterdir()) == []


def test_a_record_bought_before_the_rider_question_loads_as_unknown(tmp_path: Path) -> None:
    """The twelve days judged before 2026-09-06 have no rider_visible field."""
    from dataclasses import replace

    path = tmp_path / "record.json"
    write_video_analysis_record(path, _record())
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload["analysed"]:
        del item["rider_visible"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_video_analysis_record(path)

    assert all(item.analysis.rider_visible == "unknown" for item in loaded.analysed)

    asked = VideoAnalysisRecord(
        (AnalysedEvent(event_id="evt_0", analysis=replace(_analysis(), rider_visible="large")),)
    )
    write_video_analysis_record(path, asked)
    assert load_video_analysis_record(path).analysed[0].analysis.rider_visible == "large"
