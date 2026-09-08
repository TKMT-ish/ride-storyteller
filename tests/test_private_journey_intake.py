"""Synthetic-fixture tests for bringing a new day's footage in from the console.

What is held is the two guards: a browser may only point the server at
paths inside the intake root, and the clock offset confirmed is one that
was proposed. Package creation is exercised with the probe swapped for a
stub, so no video is decoded.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.clock_offset import ClockOffsetCandidate, ClockOffsetProposal
from app.web.private_journey_intake import (
    REASON_GPX_NOT_A_FILE,
    REASON_NAME_UNSAFE,
    REASON_NO_RECORDING_IN_RIDE,
    REASON_OFFSET_NOT_PROPOSED,
    REASON_PACKAGE_EXISTS,
    REASON_PATH_OUTSIDE_INTAKE,
    REASON_PATH_UNSAFE,
    REASON_TARGET_DURATION_INVALID,
    REASON_VIDEO_NOT_A_DIRECTORY,
    IntakeRefused,
    IntakeRoots,
    check_package_name,
    check_sources,
    confirm_offset,
    create_package,
    propose,
)

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


@pytest.fixture
def roots(tmp_path: Path) -> IntakeRoots:
    intake = tmp_path / "input"
    work = tmp_path / "work"
    intake.mkdir()
    work.mkdir()
    return IntakeRoots(intake_root=intake.resolve(), work_root=work.resolve())


@pytest.fixture
def day(roots: IntakeRoots) -> tuple[Path, Path]:
    """One day's GPX and a footage directory, inside the intake root."""
    folder = roots.intake_root / "day-two"
    folder.mkdir()
    gpx = _gpx(folder / "ride.gpx")
    videos = folder / "videos"
    videos.mkdir()
    (videos / "GH010001.MP4").write_bytes(b"a recording")
    return gpx, videos


# --- a browser may only point at the intake root -------------------------------


def test_sources_inside_the_intake_root_are_accepted(roots: IntakeRoots, day) -> None:
    gpx, videos = day

    accepted_gpx, accepted_videos = check_sources(roots, gpx=str(gpx), video_root=str(videos))

    assert accepted_gpx == gpx.resolve()
    assert accepted_videos == videos.resolve()


def test_relative_paths_are_taken_from_the_intake_root(roots: IntakeRoots, day) -> None:
    accepted_gpx, _ = check_sources(roots, gpx="day-two/ride.gpx", video_root="day-two/videos")

    assert accepted_gpx == day[0].resolve()


def test_a_path_outside_the_intake_root_is_refused(roots: IntakeRoots, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "ride.gpx").write_text("x", encoding="utf-8")

    for raw in (str(elsewhere / "ride.gpx"), "../elsewhere/ride.gpx", "/etc/hosts"):
        with pytest.raises(IntakeRefused) as refused:
            check_sources(roots, gpx=raw, video_root="day-two/videos")
        assert refused.value.reason in {REASON_PATH_OUTSIDE_INTAKE, REASON_PATH_UNSAFE}


def test_a_symlink_on_the_way_is_refused_even_if_it_lands_inside(
    roots: IntakeRoots, day, tmp_path: Path
) -> None:
    gpx, videos = day
    link = roots.intake_root / "link"
    link.symlink_to(gpx.parent, target_is_directory=True)

    with pytest.raises(IntakeRefused) as refused:
        check_sources(roots, gpx="link/ride.gpx", video_root=str(videos))
    assert refused.value.reason == REASON_PATH_UNSAFE


def test_a_symlink_that_escapes_the_root_is_refused(
    roots: IntakeRoots, day, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.gpx"
    outside.write_text("x", encoding="utf-8")
    link = roots.intake_root / "escape.gpx"
    link.symlink_to(outside)

    with pytest.raises(IntakeRefused) as refused:
        check_sources(roots, gpx="escape.gpx", video_root=str(day[1]))
    # The link itself is refused before anyone looks at where it points.
    assert refused.value.reason in {REASON_PATH_UNSAFE, REASON_PATH_OUTSIDE_INTAKE}


def test_the_gpx_must_be_a_file_and_the_footage_a_directory(roots: IntakeRoots, day) -> None:
    gpx, videos = day
    with pytest.raises(IntakeRefused) as refused:
        check_sources(roots, gpx=str(videos), video_root=str(videos))
    assert refused.value.reason == REASON_GPX_NOT_A_FILE

    with pytest.raises(IntakeRefused) as refused:
        check_sources(roots, gpx=str(gpx), video_root=str(gpx))
    assert refused.value.reason == REASON_VIDEO_NOT_A_DIRECTORY


def test_missing_and_empty_paths_are_refused(roots: IntakeRoots, day) -> None:
    for raw in ("", None, "day-two/nowhere.gpx"):
        with pytest.raises(IntakeRefused) as refused:
            check_sources(roots, gpx=raw, video_root=str(day[1]))
        assert refused.value.reason == REASON_PATH_UNSAFE


# --- a package is a plain word under the work root ------------------------------


def test_a_package_name_is_a_plain_word(roots: IntakeRoots) -> None:
    assert check_package_name(roots, "day-two_v1") == roots.work_root / "day-two_v1"
    for bad in ("", "../x", "a/b", ".hidden", "with space", "x" * 65, None):
        with pytest.raises(IntakeRefused) as refused:
            check_package_name(roots, bad)
        assert refused.value.reason == REASON_NAME_UNSAFE


def test_an_existing_package_is_not_overwritten(roots: IntakeRoots) -> None:
    (roots.work_root / "taken").mkdir()

    with pytest.raises(IntakeRefused) as refused:
        check_package_name(roots, "taken")
    assert refused.value.reason == REASON_PACKAGE_EXISTS


# --- the offset confirmed is one that was proposed ---------------------------------


def _candidate(offset_s: float, inside: int) -> ClockOffsetCandidate:
    return ClockOffsetCandidate(
        offset_s=offset_s,
        recordings_inside=inside,
        recordings_clipped=0,
        recordings_total=10,
        covered_ride_s=600.0,
        ride_duration_s=3600.0,
        lead_in_s=0.0,
        lead_out_s=0.0,
    )


def test_the_proposed_offset_is_confirmed_as_a_number_that_was_offered() -> None:
    proposal = ClockOffsetProposal(
        best=_candidate(-46_800.0, 14), runners_up=(_candidate(-45_000.0, 9),)
    )

    assert confirm_offset(proposal, "-46800") == -46_800.0
    assert confirm_offset(proposal, -45_000) == -45_000.0


def test_an_offset_that_was_never_proposed_is_not_a_confirmation() -> None:
    proposal = ClockOffsetProposal(best=_candidate(-46_800.0, 14), runners_up=())

    for offered in ("0", "-46801", "", None, "thirteen hours", -43_200):
        with pytest.raises(IntakeRefused) as refused:
            confirm_offset(proposal, offered)
        assert refused.value.reason == REASON_OFFSET_NOT_PROPOSED


# --- proposing and creating ------------------------------------------------------------


def test_proposing_reports_evidence_without_a_path(roots: IntakeRoots, day, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.web.private_journey_intake.propose_clock_offset",
        lambda gpx, videos: ClockOffsetProposal(best=_candidate(0.0, 1), runners_up=()),
    )

    payload = propose(roots, gpx="day-two/ride.gpx", video_root="day-two/videos")

    assert payload["is_unambiguous"] is True
    assert payload["proposed"]["offset_s"] == 0.0
    assert payload["local_only"] is True
    assert "day-two" not in str(payload)


def test_footage_from_another_day_is_a_named_refusal(roots: IntakeRoots, day, monkeypatch) -> None:
    from app.clock_offset import ClockOffsetError

    def nothing_inside(gpx, videos):
        raise ClockOffsetError("no whole- or half-hour shift places any recording inside")

    monkeypatch.setattr("app.web.private_journey_intake.propose_clock_offset", nothing_inside)

    with pytest.raises(IntakeRefused) as refused:
        propose(roots, gpx="day-two/ride.gpx", video_root="day-two/videos")
    assert refused.value.reason == REASON_NO_RECORDING_IN_RIDE


def test_creating_rechecks_the_offset_against_the_evidence(
    roots: IntakeRoots, day, monkeypatch
) -> None:
    """A page's remembered number is not trusted; the evidence is asked again."""
    monkeypatch.setattr(
        "app.web.private_journey_intake.propose_clock_offset",
        lambda gpx, videos: ClockOffsetProposal(best=_candidate(-46_800.0, 14), runners_up=()),
    )
    built: dict = {}

    def fake_prepare(gpx, videos, destination, **kwargs):
        built.update(kwargs, destination=destination)

    monkeypatch.setattr("app.web.private_journey_intake.prepare_local_review_package", fake_prepare)

    with pytest.raises(IntakeRefused):
        create_package(
            roots, gpx="day-two/ride.gpx", video_root="day-two/videos", name="day-two", offset_s="0"
        )
    assert built == {}

    destination = create_package(
        roots,
        gpx="day-two/ride.gpx",
        video_root="day-two/videos",
        name="day-two",
        offset_s="-46800",
    )

    assert destination == roots.work_root / "day-two"
    assert built["video_to_gps_offset_s"] == -46_800.0
    assert built["clock_offset_confirmed"] is True
    assert built["extract_reviews"] is False
    assert built["target_duration_s"] == 300.0


def test_the_target_duration_is_bounded(roots: IntakeRoots, day, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.web.private_journey_intake.propose_clock_offset",
        lambda gpx, videos: ClockOffsetProposal(best=_candidate(0.0, 1), runners_up=()),
    )
    for bad in ("0", "-5", "99999", "long", None):
        with pytest.raises(IntakeRefused) as refused:
            create_package(
                roots,
                gpx="day-two/ride.gpx",
                video_root="day-two/videos",
                name="day-two",
                offset_s="0",
                target_duration_s=bad,
            )
        assert refused.value.reason == REASON_TARGET_DURATION_INVALID


def test_roots_come_from_the_environment_with_a_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("RIDE_PRIVATE_INTAKE_ROOT", raising=False)
    monkeypatch.delenv("RIDE_PRIVATE_WORK_ROOT", raising=False)
    assert IntakeRoots.from_environment().intake_root.name == "input"

    monkeypatch.setenv("RIDE_PRIVATE_INTAKE_ROOT", str(tmp_path / "in"))
    monkeypatch.setenv("RIDE_PRIVATE_WORK_ROOT", str(tmp_path / "out"))
    roots = IntakeRoots.from_environment()
    assert roots.intake_root == (tmp_path / "in").resolve()
    assert roots.work_root == (tmp_path / "out").resolve()


def test_only_directories_the_console_can_read_are_listed(roots: IntakeRoots) -> None:
    """The work root also holds research runs and review clips; those are not rides."""
    from app.web.private_journey_intake import list_packages

    ride = roots.work_root / "ride-one"
    ride.mkdir()
    (ride / "local-pipeline-inputs.json").write_text("{}", encoding="utf-8")
    (ride / "local-video-catalog.json").write_text("{}", encoding="utf-8")
    (roots.work_root / "review-clips").mkdir()
    (roots.work_root / "research-v3").mkdir()
    (roots.work_root / "research-v3" / "local-video-catalog.json").write_text(
        "{}", encoding="utf-8"
    )

    assert list_packages(roots) == ["ride-one"]
