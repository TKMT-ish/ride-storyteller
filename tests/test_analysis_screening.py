"""Synthetic-fixture tests for reading stillness off the GPS track.

Nothing here opens a video or reaches a network: screening is free by
construction, and these hold it to that. What is held is which windows a
stopped stretch produces, that a gap in the track is never mistaken for a
stop, that a long stop is one stop rather than four, that the report
carries counts and money and no identifier, and -- the point of the
module -- that screening removes nothing from what gets judged.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.agents import StoryOutputLanguage
from app.analysis_cli import command_screen
from app.analysis_run import plan_analysis_run
from app.analysis_screening import (
    AnalysisScreeningError,
    WindowStillness,
    halts,
    measure_stillness,
    screening_report,
    still_windows,
    windows_after_the_first_of_each_stop,
)
from app.local_pipeline import LocalPipelineInputs
from app.video import VideoCatalog, VideoCatalogEntry

_RIDE_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
_RIDE_S = 1_800.0
_STEP_S = 5.0
# The ride stands still here, and the track says nothing at all here.
_STOPPED = (660.0, 780.0)
_SILENT = (900.0, 1_000.0)


def _gpx(path: Path) -> Path:
    """A dense track that moves, then stops, then moves, with one gap."""
    latitude = 35.0
    entries = []
    for step in range(int(_RIDE_S / _STEP_S) + 1):
        second = step * _STEP_S
        if not _STOPPED[0] <= second <= _STOPPED[1]:
            # About 20 m/s: an ordinary road speed at this sampling rate.
            # The ride keeps moving across the gap, so the first point after
            # it reads fast rather than slow.
            latitude += 0.0009
        if _SILENT[0] <= second < _SILENT[1]:
            continue
        entries.append(
            '<trkpt lat="{lat:.6f}" lon="139.000000"><ele>100</ele><time>{t}</time></trkpt>'.format(
                lat=latitude,
                t=(_RIDE_START + timedelta(seconds=second)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="t" '
        'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        + "".join(entries)
        + "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    return path


def _package(root: Path) -> Path:
    """A package whose camera ran from ten minutes in for a quarter hour."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "synthetic.mp4").write_bytes(b"a recording")
    inputs = LocalPipelineInputs(
        gpx_path=_gpx(root / "ride.gpx").resolve(),
        video_root=root.resolve(),
        video_to_gps_offset_s=0.0,
        target_duration_s=300.0,
        output_language=StoryOutputLanguage.JAPANESE,
    )
    (root / "local-pipeline-inputs.json").write_text(json.dumps(inputs.to_dict()), encoding="utf-8")
    catalog = VideoCatalog(
        entries=(
            VideoCatalogEntry(
                asset_id="asset-1",
                file_name="synthetic.mp4",
                recorded_start_time=_RIDE_START + timedelta(seconds=600),
                duration_s=900.0,
            ),
        ),
        video_to_gps_offset_s=0.0,
    )
    (root / "local-video-catalog.json").write_text(json.dumps(catalog.to_dict()), encoding="utf-8")
    return root


# --- what the track says about a window -----------------------------------------


def test_the_stopped_stretch_is_the_only_thing_called_still(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    readings = measure_stillness(package)

    # Windows run from ten minutes in, every thirty seconds; four of them
    # fall wholly inside the two minutes the ride was stopped.
    assert len(readings) == 30
    assert len(still_windows(readings)) == 4


def test_a_window_the_track_says_nothing_about_is_not_a_stop(tmp_path: Path) -> None:
    """Not knowing and standing still are different readings."""
    package = _package(tmp_path / "package")
    readings = measure_stillness(package)

    silent = [reading for reading in readings if reading.fastest_mps is None]
    assert silent, "the fixture's gap should leave at least one window unread"
    assert all(not reading.is_still() for reading in silent)
    assert all(reading.point_count == 0 for reading in silent)


def test_a_reading_without_a_speed_is_never_still() -> None:
    assert not WindowStillness("footage-1", None, 0).is_still()
    assert WindowStillness("footage-1", 0.4, 3).is_still()
    assert not WindowStillness("footage-1", 4.0, 3).is_still()


def test_a_negative_still_speed_is_refused(tmp_path: Path) -> None:
    readings = measure_stillness(_package(tmp_path / "package"))

    with pytest.raises(AnalysisScreeningError, match="negative"):
        still_windows(readings, speed_mps=-1.0)


# --- a long stop is one stop ----------------------------------------------------


def test_one_stop_is_charged_once_not_once_every_window(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    readings = measure_stillness(package)

    still = still_windows(readings)
    after_first = windows_after_the_first_of_each_stop(readings)
    assert len(after_first) == len(still) - 1
    assert still[0] not in after_first
    assert set(after_first) < set(still)


# --- the report -----------------------------------------------------------------


def test_the_report_carries_counts_and_money_and_no_identifier(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    report = screening_report(package)

    assert report["window_count"] == 30
    assert report["still_count"] == 4
    assert report["stop_count"] == 1
    assert report["would_save_jpy"]["dropping_every_still_window"] > 0

    written = json.dumps(report, ensure_ascii=False)
    for event_id in (reading.event_id for reading in measure_stillness(package)):
        assert event_id not in written
    assert "footage-" not in written
    assert str(package) not in written


def test_the_report_says_it_decides_nothing(tmp_path: Path) -> None:
    """The contract of this module, stated where the output is read."""
    assert screening_report(_package(tmp_path / "package"))["drops_nothing"] is True


def test_screening_takes_nothing_away_from_what_would_be_judged(tmp_path: Path) -> None:
    """Measured on real rides, dropping the still windows costs films their
    best moments. So the paying path never sees this reading."""
    package = _package(tmp_path / "package")
    still = set(still_windows(measure_stillness(package)))
    assert still

    priced = {candidate.event_id for candidate in plan_analysis_run(package).candidates}
    assert still <= priced


def test_the_command_reports_without_sending_anything(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")

    assert command_screen(package, speed_mps=1.0) == screening_report(package, speed_mps=1.0)


# --- a halt is one place ---------------------------------------------------------


def test_the_stopped_stretch_is_one_halt_and_the_silent_gap_is_none(tmp_path: Path) -> None:
    """Indoors the track goes quiet; on open road it can too. Only a run
    with a measured reading at walking pace is a place."""
    readings = measure_stillness(_package(tmp_path / "package"))

    numbered = halts(readings)
    assert set(numbered.values()) == {1}
    assert set(numbered) == set(still_windows(readings))
    silent = {reading.event_id for reading in readings if reading.fastest_mps is None}
    assert silent and not silent & set(numbered)


def test_a_quiet_run_anchored_by_one_slow_reading_is_one_halt() -> None:
    readings = (
        WindowStillness("footage-1", 25.0, 3),
        WindowStillness("footage-2", None, 0),
        WindowStillness("footage-3", None, 0),
        WindowStillness("footage-4", 2.0, 2),
        WindowStillness("footage-5", None, 0),
        WindowStillness("footage-6", 24.0, 3),
        WindowStillness("footage-7", 0.0, 3),
    )

    assert halts(readings) == {
        "footage-2": 1,
        "footage-3": 1,
        "footage-4": 1,
        "footage-5": 1,
        "footage-7": 2,
    }


def test_a_negative_halt_speed_is_refused() -> None:
    with pytest.raises(AnalysisScreeningError, match="negative"):
        halts((WindowStillness("footage-1", 0.0, 1),), speed_mps=-1.0)
