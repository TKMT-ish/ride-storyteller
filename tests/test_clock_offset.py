"""Synthetic-fixture tests for proposing the camera-to-GPS clock offset."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.clock_offset import (
    CLOCK_OFFSET_SCHEMA_VERSION,
    ClockOffsetCandidate,
    ClockOffsetError,
    propose_clock_offset,
)
from app.video import LocalVideoMetadata

_RIDE_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
_RIDE_S = 4 * 3600.0
# The camera believes it is thirteen hours later than the GPS does.
_CAMERA_ERROR_S = 13 * 3600.0
# Footage from near both ends of the ride. This is what makes one shift fit
# and the rest not: shift by an hour and an end recording falls outside.
_SPANNING_RIDE = (300.0, 7_200.0, 13_500.0)


def _gpx(path: Path, *, point_count: int = 40, span_s: float = _RIDE_S) -> Path:
    step = span_s / (point_count - 1)
    points = [
        '<trkpt lat="{lat:.6f}" lon="{lon:.6f}"><ele>{ele:.1f}</ele>'
        "<time>{time}</time></trkpt>".format(
            lat=35.0 + 0.001 * index,
            lon=139.0 + 0.002 * index,
            ele=100.0 + index,
            time=(_RIDE_START + timedelta(seconds=step * index)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        for index in range(point_count)
    ]
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        "<trk><trkseg>" + "".join(points) + "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    return path


def _videos(
    root: Path,
    *,
    starts_s: tuple[float, ...],
    duration_s: float = 600.0,
    error_s: float = _CAMERA_ERROR_S,
) -> dict[Path, LocalVideoMetadata]:
    """Recordings stamped with the camera's own (wrong) clock."""
    root.mkdir(parents=True, exist_ok=True)
    catalogue: dict[Path, LocalVideoMetadata] = {}
    for index, offset_s in enumerate(starts_s):
        path = root / f"GX{index + 1:04d}.mp4"
        path.write_bytes(b"synthetic video")
        catalogue[path] = LocalVideoMetadata(
            file_name=path.name,
            duration_s=duration_s,
            recorded_start_time=_RIDE_START + timedelta(seconds=offset_s + error_s),
            video_codec="h264",
            width=1920,
            height=1080,
            frames_per_second=30.0,
            has_audio=True,
        )
    return catalogue


def _probe(catalogue: dict[Path, LocalVideoMetadata]):
    def probe(path: Path) -> LocalVideoMetadata:
        return catalogue[path]

    return probe


def _fixture(tmp_path: Path, **kwargs):
    gpx = _gpx(tmp_path / "ride.gpx")
    catalogue = _videos(tmp_path / "video", **kwargs)
    return gpx, tmp_path / "video", _probe(catalogue)


def test_the_camera_error_is_recovered(tmp_path: Path) -> None:
    gpx, video_root, probe = _fixture(tmp_path, starts_s=_SPANNING_RIDE)

    proposal = propose_clock_offset(gpx, video_root, probe=probe)

    assert proposal.best.offset_s == -int(_CAMERA_ERROR_S)


def test_the_proposal_shows_why_it_is_proposed(tmp_path: Path) -> None:
    gpx, video_root, probe = _fixture(tmp_path, starts_s=_SPANNING_RIDE)

    best = propose_clock_offset(gpx, video_root, probe=probe).best

    assert best.recordings_inside == 3
    assert best.recordings_clipped == 0
    assert best.recordings_total == 3
    assert best.inside_ratio == pytest.approx(1.0)
    # Three ten-minute recordings inside a four-hour ride.
    assert best.covered_ride_s == pytest.approx(1_800.0)
    assert best.covered_ratio == pytest.approx(1_800.0 / _RIDE_S)
    assert best.lead_in_s == pytest.approx(300.0)
    assert best.lead_out_s == pytest.approx(_RIDE_S - 14_100.0)
    assert best.ride_duration_s == pytest.approx(_RIDE_S)


def test_a_camera_that_was_right_needs_no_shift(tmp_path: Path) -> None:
    gpx, video_root, probe = _fixture(tmp_path, starts_s=_SPANNING_RIDE, error_s=0.0)

    assert propose_clock_offset(gpx, video_root, probe=probe).best.offset_s == 0


def test_a_half_hour_time_zone_is_recovered(tmp_path: Path) -> None:
    gpx, video_root, probe = _fixture(tmp_path, starts_s=_SPANNING_RIDE, error_s=5.5 * 3600.0)

    assert propose_clock_offset(gpx, video_root, probe=probe).best.offset_s == -int(5.5 * 3600)


def test_a_clear_answer_is_reported_as_unambiguous(tmp_path: Path) -> None:
    gpx, video_root, probe = _fixture(tmp_path, starts_s=_SPANNING_RIDE)

    proposal = propose_clock_offset(gpx, video_root, probe=probe)

    assert proposal.is_unambiguous
    assert proposal.runners_up


def test_a_tie_is_reported_rather_than_hidden(tmp_path: Path) -> None:
    """One short recording fits under several shifts; a person must decide."""
    gpx, video_root, probe = _fixture(tmp_path, starts_s=(7_200.0,), duration_s=60.0)

    proposal = propose_clock_offset(gpx, video_root, probe=probe)

    assert not proposal.is_unambiguous


def test_footage_from_another_day_is_refused(tmp_path: Path) -> None:
    """No shift within a day places it inside the ride, so none is offered."""
    gpx, video_root, probe = _fixture(tmp_path, starts_s=(600.0,), error_s=40 * 3600.0)

    with pytest.raises(ClockOffsetError, match="no whole- or half-hour shift"):
        propose_clock_offset(gpx, video_root, probe=probe)


def test_an_unreadable_recording_does_not_stop_the_others(tmp_path: Path) -> None:
    gpx = _gpx(tmp_path / "ride.gpx")
    video_root = tmp_path / "video"
    catalogue = _videos(video_root, starts_s=_SPANNING_RIDE)
    (video_root / "broken.mp4").write_bytes(b"not a video")

    def probe(path: Path) -> LocalVideoMetadata:
        if path.name == "broken.mp4":
            raise ValueError("unreadable")
        return catalogue[path]

    proposal = propose_clock_offset(gpx, video_root, probe=probe)

    assert proposal.best.recordings_total == len(_SPANNING_RIDE)


def test_a_directory_with_no_recordings_is_reported(tmp_path: Path) -> None:
    gpx = _gpx(tmp_path / "ride.gpx")
    (tmp_path / "video").mkdir()

    with pytest.raises(ClockOffsetError, match="no readable recording"):
        propose_clock_offset(gpx, tmp_path / "video", probe=lambda path: None)


def test_a_missing_video_directory_is_reported(tmp_path: Path) -> None:
    gpx = _gpx(tmp_path / "ride.gpx")

    with pytest.raises(ClockOffsetError, match="video directory is unavailable"):
        propose_clock_offset(gpx, tmp_path / "absent", probe=lambda path: None)


def test_the_report_carries_no_file_name_or_capture_time(tmp_path: Path) -> None:
    gpx, video_root, probe = _fixture(tmp_path, starts_s=_SPANNING_RIDE)

    payload = propose_clock_offset(gpx, video_root, probe=probe).to_dict()
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["schema_version"] == CLOCK_OFFSET_SCHEMA_VERSION
    assert payload["external_data_sent"] is False
    for forbidden in ("GX0001", ".mp4", "2026-05-01", str(tmp_path), "latitude"):
        assert forbidden not in serialized


def test_the_proposed_offset_is_reported_in_hours_a_person_can_read(tmp_path: Path) -> None:
    gpx, video_root, probe = _fixture(tmp_path, starts_s=_SPANNING_RIDE)

    payload = propose_clock_offset(gpx, video_root, probe=probe).to_dict()

    assert payload["proposed"]["offset_hours"] == pytest.approx(-13.0)


def test_a_ride_track_with_no_duration_is_refused(tmp_path: Path) -> None:
    """A single trackpoint parses fine but covers no time -- nothing to align."""
    gpx = tmp_path / "ride.gpx"
    gpx.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        '<trk><trkseg><trkpt lat="35.0" lon="139.0"><ele>100.0</ele>'
        "<time>2026-05-01T09:00:00Z</time></trkpt></trkseg></trk></gpx>",
        encoding="utf-8",
    )
    (tmp_path / "video").mkdir()

    with pytest.raises(ClockOffsetError, match="covers no time"):
        propose_clock_offset(gpx, tmp_path / "video", probe=lambda path: None)


def test_a_symlinked_video_directory_is_refused(tmp_path: Path) -> None:
    gpx = _gpx(tmp_path / "ride.gpx")
    real_root = tmp_path / "video"
    _videos(real_root, starts_s=_SPANNING_RIDE)
    link_root = tmp_path / "video-link"
    link_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(ClockOffsetError, match="video directory is unavailable"):
        propose_clock_offset(gpx, link_root, probe=lambda path: None)


def test_a_symlinked_recording_is_not_counted(tmp_path: Path) -> None:
    gpx, video_root, probe = _fixture(tmp_path, starts_s=_SPANNING_RIDE)
    real_file = next(iter(video_root.glob("*.mp4")))
    link = video_root / "GXLINK.mp4"
    link.symlink_to(real_file)

    proposal = propose_clock_offset(gpx, video_root, probe=probe)

    assert proposal.best.recordings_total == len(_SPANNING_RIDE)


def test_a_non_video_suffix_is_never_probed(tmp_path: Path) -> None:
    gpx, video_root, probe = _fixture(tmp_path, starts_s=_SPANNING_RIDE)
    (video_root / "notes.txt").write_text("not a recording")

    proposal = propose_clock_offset(gpx, video_root, probe=probe)

    # `probe` is a dict lookup with no entry for notes.txt; had it been
    # probed this call would already have raised KeyError.
    assert proposal.best.recordings_total == len(_SPANNING_RIDE)


def test_the_video_suffix_match_is_case_insensitive(tmp_path: Path) -> None:
    gpx = _gpx(tmp_path / "ride.gpx")
    video_root = tmp_path / "video"
    catalogue = _videos(video_root, starts_s=_SPANNING_RIDE)
    upper = {path.with_suffix(".MP4"): metadata for path, metadata in catalogue.items()}
    for old_path, new_path in zip(catalogue, upper, strict=True):
        old_path.rename(new_path)

    proposal = propose_clock_offset(gpx, video_root, probe=_probe(upper))

    assert proposal.best.recordings_total == len(_SPANNING_RIDE)


def test_a_recording_missing_its_start_time_is_skipped(tmp_path: Path) -> None:
    gpx, video_root, probe = _fixture(tmp_path, starts_s=_SPANNING_RIDE)
    undated_path = video_root / "GX9999.mp4"
    undated_path.write_bytes(b"synthetic video")
    catalogue_probe = probe

    def probe_with_undated(path: Path) -> LocalVideoMetadata:
        if path == undated_path:
            return LocalVideoMetadata(
                file_name=path.name,
                duration_s=60.0,
                recorded_start_time=None,
                video_codec="h264",
                width=1920,
                height=1080,
                frames_per_second=30.0,
                has_audio=True,
            )
        return catalogue_probe(path)

    proposal = propose_clock_offset(gpx, video_root, probe=probe_with_undated)

    assert proposal.best.recordings_total == len(_SPANNING_RIDE)


def test_a_recording_with_no_duration_is_skipped(tmp_path: Path) -> None:
    """A malformed probe result (zero duration) must not be counted or crash."""
    gpx, video_root, probe = _fixture(tmp_path, starts_s=_SPANNING_RIDE)
    zero_length_path = video_root / "GX9999.mp4"
    zero_length_path.write_bytes(b"synthetic video")
    catalogue_probe = probe

    def probe_with_zero_length(path: Path):
        if path == zero_length_path:
            return SimpleNamespace(recorded_start_time=_RIDE_START, duration_s=0.0)
        return catalogue_probe(path)

    proposal = propose_clock_offset(gpx, video_root, probe=probe_with_zero_length)

    assert proposal.best.recordings_total == len(_SPANNING_RIDE)


def test_overlapping_recordings_do_not_double_count_covered_time(tmp_path: Path) -> None:
    gpx, video_root, probe = _fixture(
        tmp_path, starts_s=(0.0, 200.0), duration_s=600.0, error_s=0.0
    )

    proposal = propose_clock_offset(gpx, video_root, probe=probe)

    assert proposal.best.offset_s == 0
    assert proposal.best.recordings_inside == 2
    # 0..600 and 200..800 overlap; the merged span is 0..800, not 1200.
    assert proposal.best.covered_ride_s == pytest.approx(800.0)


def test_a_tie_prefers_the_smallest_shift(tmp_path: Path) -> None:
    gpx, video_root, probe = _fixture(tmp_path, starts_s=(7_200.0,), duration_s=60.0)

    proposal = propose_clock_offset(gpx, video_root, probe=probe)

    tied = [
        candidate
        for candidate in (proposal.best, *proposal.runners_up)
        if candidate.recordings_inside == proposal.best.recordings_inside
        and candidate.recordings_clipped == proposal.best.recordings_clipped
        and candidate.covered_ride_s == proposal.best.covered_ride_s
    ]
    assert abs(proposal.best.offset_s) == min(abs(candidate.offset_s) for candidate in tied)


def test_a_restricted_offset_search_only_tries_what_it_is_given(tmp_path: Path) -> None:
    gpx, video_root, probe = _fixture(tmp_path, starts_s=_SPANNING_RIDE, error_s=0.0)

    proposal = propose_clock_offset(gpx, video_root, probe=probe, candidate_offsets_s=(0,))

    assert proposal.best.offset_s == 0
    assert proposal.runners_up == ()


def test_keep_runners_up_zero_reports_only_the_best(tmp_path: Path) -> None:
    """A tie this call chooses not to keep cannot be reported as ambiguous."""
    gpx, video_root, probe = _fixture(tmp_path, starts_s=(7_200.0,), duration_s=60.0)

    proposal = propose_clock_offset(gpx, video_root, probe=probe, keep_runners_up=0)

    assert proposal.runners_up == ()
    assert proposal.is_unambiguous


def test_candidate_ratios_are_zero_rather_than_dividing_by_zero() -> None:
    candidate = ClockOffsetCandidate(
        offset_s=0,
        recordings_inside=0,
        recordings_clipped=0,
        recordings_total=0,
        covered_ride_s=0.0,
        ride_duration_s=0.0,
        lead_in_s=0.0,
        lead_out_s=0.0,
    )

    assert candidate.inside_ratio == 0.0
    assert candidate.covered_ratio == 0.0
