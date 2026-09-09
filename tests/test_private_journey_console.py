"""Synthetic-fixture tests for the console's view of the judged path.

The console only reads. These hold what it says at each point along the
way -- nothing judged, judgement in progress, judgement bought, judgement
faked -- and that nothing private ever reaches the payload.
"""

from __future__ import annotations

import json
from dataclasses import replace
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
from app.analysis_run import (
    PARTIAL_RECORD_FILE_NAME,
    PROXY_DIRECTORY_NAME,
    plan_analysis_run,
)
from app.contracts import VideoAnalysis
from app.data_handling_disclosure import data_handling_disclosure
from app.local_pipeline import LocalPipelineInputs
from app.video import VideoCatalog, VideoCatalogEntry
from app.web.private_journey_console import (
    ACTION_APPROVE_AND_JUDGE,
    ACTION_PREPARE_COPIES,
    ACTION_RESOLVE_BLOCKING,
    ACTION_WAIT_FOR_JUDGEMENT,
    PRIVATE_JOURNEY_CONSOLE_SCHEMA_VERSION,
    REASON_JUDGEMENT_UNBOUGHT,
    REASON_NO_FOOTAGE_IN_RIDE,
    STAGE_COPIES_PREPARED,
    STAGE_FOOTAGE_JUDGED,
    STAGE_FOOTAGE_PLANNED,
    STATE_BLOCKED,
    STATE_DONE,
    STATE_IN_PROGRESS,
    STATE_PENDING,
    PrivateJourneyConsole,
    PrivateJourneyConsoleError,
)

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


def _package(root: Path, *, recording_s: float = 120.0) -> Path:
    """Inputs and a catalogue: enough to plan, nothing yet judged."""
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
                duration_s=recording_s,
            ),
        ),
        video_to_gps_offset_s=0.0,
    )
    (root / "local-video-catalog.json").write_text(
        json.dumps(catalog.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    return root


def _analysis(candidate, *, provider: str = "gemini") -> VideoAnalysis:
    return VideoAnalysis(
        asset_id=candidate.asset_id,
        start_offset_s=candidate.start_offset_s,
        end_offset_s=candidate.end_offset_s,
        visual_description="a road",
        road_type="highway",
        scenery_tags=("sky",),
        weather_visible="clear",
        visual_interest_score=0.6,
        story_relevance_score=0.7,
        confidence=0.9,
        analysis_provider=provider,
    )


def _write_judgement(package: Path, *, count: int | None = None, provider: str = "gemini") -> None:
    plan = plan_analysis_run(package)
    chosen = plan.watched_candidates[:count] if count is not None else plan.watched_candidates
    record = VideoAnalysisRecord(
        tuple(
            AnalysedEvent(event_id=c.event_id, analysis=_analysis(c, provider=provider))
            for c in chosen
        )
    )
    name = PARTIAL_RECORD_FILE_NAME if count is not None else VIDEO_ANALYSIS_RECORD_FILE_NAME
    write_video_analysis_record(package / name, record, overwrite=True)


def _stages(package: Path) -> dict[str, dict[str, object]]:
    payload = PrivateJourneyConsole.from_directory(package).payload()
    return {str(stage["key"]): stage for stage in payload["stages"]}


def _console(package: Path) -> dict[str, object]:
    return PrivateJourneyConsole.from_directory(package).payload()


# --- the judged path comes first, and costs nothing to read ------------------


def test_the_judged_path_leads_and_the_film_follows(tmp_path: Path) -> None:
    payload = _console(_package(tmp_path / "package"))

    keys = [stage["key"] for stage in payload["stages"]]
    assert keys[:3] == [STAGE_FOOTAGE_PLANNED, STAGE_COPIES_PREPARED, STAGE_FOOTAGE_JUDGED]
    assert len(keys) > 3, "the film's own stages must follow"
    assert payload["schema_version"] == PRIVATE_JOURNEY_CONSOLE_SCHEMA_VERSION
    assert payload["local_only"] is True
    assert payload["external_data_sent"] is False


def test_planning_reports_the_figure_a_person_needs_to_decide(tmp_path: Path) -> None:
    planned = _stages(_package(tmp_path / "package"))[STAGE_FOOTAGE_PLANNED]

    assert planned["state"] == STATE_DONE
    assert planned["candidate_count"] > 0
    assert planned["watched_count"] == planned["candidate_count"]
    assert planned["upload_megabytes"] > 0
    assert planned["cost_jpy"] > 0
    assert planned["within_budget"] is True


def test_reading_the_console_makes_no_copies_and_buys_nothing(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")

    _console(package)

    assert not (package / PROXY_DIRECTORY_NAME).exists()
    assert not (package / VIDEO_ANALYSIS_RECORD_FILE_NAME).exists()


# --- each point along the way says the right thing ---------------------------


def test_nothing_prepared_means_prepare_the_copies_next(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")

    stages = _stages(package)
    assert stages[STAGE_COPIES_PREPARED]["state"] == STATE_PENDING
    assert stages[STAGE_FOOTAGE_JUDGED]["state"] == STATE_PENDING
    assert _console(package)["next_action"] == ACTION_PREPARE_COPIES


def test_some_copies_present_is_in_progress(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)
    proxies = package / PROXY_DIRECTORY_NAME
    proxies.mkdir()
    for candidate in plan.watched_candidates[:2]:
        (proxies / f"{candidate.event_id}.mp4").write_bytes(b"x" * 1000)

    prepared = _stages(package)[STAGE_COPIES_PREPARED]

    assert prepared["state"] == STATE_IN_PROGRESS
    assert prepared["prepared_count"] == 2
    assert prepared["wanted_count"] == plan.watched_count


def test_every_copy_present_means_approve_and_judge_next(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)
    proxies = package / PROXY_DIRECTORY_NAME
    proxies.mkdir()
    for candidate in plan.watched_candidates:
        (proxies / f"{candidate.event_id}.mp4").write_bytes(b"x" * 1000)

    stages = _stages(package)
    assert stages[STAGE_COPIES_PREPARED]["state"] == STATE_DONE
    assert stages[STAGE_COPIES_PREPARED]["measured_megabytes"] == pytest.approx(
        plan.watched_count * 0.001, abs=0.05
    )
    assert _console(package)["next_action"] == ACTION_APPROVE_AND_JUDGE


def test_an_empty_copy_does_not_count_as_prepared(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    plan = plan_analysis_run(package)
    proxies = package / PROXY_DIRECTORY_NAME
    proxies.mkdir()
    (proxies / f"{plan.watched_candidates[0].event_id}.mp4").write_bytes(b"")

    assert _stages(package)[STAGE_COPIES_PREPARED]["prepared_count"] == 0


def test_a_judgement_part_way_through_is_in_progress_and_says_wait(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _write_judgement(package, count=3)

    judged = _stages(package)[STAGE_FOOTAGE_JUDGED]
    assert judged["state"] == STATE_IN_PROGRESS
    assert judged["judged_count"] == 3
    assert _console(package)["next_action"] == ACTION_WAIT_FOR_JUDGEMENT


def test_a_bought_judgement_is_done_and_hands_over_to_the_film(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _write_judgement(package)

    payload = _console(package)
    judged = {s["key"]: s for s in payload["stages"]}[STAGE_FOOTAGE_JUDGED]
    assert judged["state"] == STATE_DONE
    assert judged["judged_count"] == judged["wanted_count"]
    # The film's own status decides from here; its answer is not one of ours.
    assert payload["next_action"] not in {
        ACTION_PREPARE_COPIES,
        ACTION_APPROVE_AND_JUDGE,
        ACTION_WAIT_FOR_JUDGEMENT,
    }


def test_a_judgement_nobody_bought_blocks_the_path(tmp_path: Path) -> None:
    """A stub's record looks exactly like a bought one."""
    package = _package(tmp_path / "package")
    _write_judgement(package, provider="stub-dry-run")

    judged = _stages(package)[STAGE_FOOTAGE_JUDGED]
    assert judged["state"] == STATE_BLOCKED
    assert judged["blocking_reasons"] == [REASON_JUDGEMENT_UNBOUGHT]
    assert _console(package)["next_action"] == ACTION_RESOLVE_BLOCKING


def test_a_ride_the_camera_never_filmed_is_blocked_with_a_reason(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=5.0)

    stages = _stages(package)
    assert stages[STAGE_FOOTAGE_PLANNED]["state"] == STATE_BLOCKED
    assert stages[STAGE_FOOTAGE_PLANNED]["blocking_reasons"] == [REASON_NO_FOOTAGE_IN_RIDE]
    assert stages[STAGE_COPIES_PREPARED]["state"] == STATE_BLOCKED
    assert stages[STAGE_FOOTAGE_JUDGED]["state"] == STATE_BLOCKED
    assert _console(package)["next_action"] == ACTION_RESOLVE_BLOCKING


# --- nothing private reaches the browser --------------------------------------


def test_the_payload_carries_no_path_identifier_or_model_text(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _write_judgement(package)
    plan = plan_analysis_run(package)

    serialized = json.dumps(_console(package), ensure_ascii=False)

    for forbidden in (
        str(tmp_path),
        "synthetic.mp4",
        _ASSET_ID,
        plan.candidates[0].event_id,
        "footage-",
        "a road",
        "highway",
    ):
        assert forbidden not in serialized


def test_a_missing_package_is_an_error_not_a_traceback(tmp_path: Path) -> None:
    with pytest.raises(PrivateJourneyConsoleError):
        PrivateJourneyConsole.from_directory(tmp_path / "nowhere")


def test_a_symlinked_package_is_refused(tmp_path: Path) -> None:
    real = _package(tmp_path / "real")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    with pytest.raises(PrivateJourneyConsoleError):
        PrivateJourneyConsole.from_directory(link)


def test_the_console_is_built_from_the_environment_the_status_page_uses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.web.private_journey_status import PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV

    package = _package(tmp_path / "package")
    monkeypatch.setenv(PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV, str(package))

    console = PrivateJourneyConsole.from_environment()

    assert console.package_directory == package.resolve()
    assert replace(console) == console


# --- what approving would send travels with the payload, the same for every ride


def test_the_payload_carries_the_fixed_data_handling_disclosure(tmp_path: Path) -> None:
    """The figure says what a judgement costs; this says what it sends and keeps."""
    package = _package(tmp_path / "package")

    payload = _console(package)

    assert payload["data_handling"] == data_handling_disclosure()
    assert payload["data_handling"]["sent_only_if_judging_is_approved"] is True
