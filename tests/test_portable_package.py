"""Synthetic-fixture tests for the package that can be cut on another machine."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.portable_package import (
    FILM_SOURCES_FILE_NAME,
    FILM_SOURCES_SCHEMA_VERSION,
    PortablePackageError,
    PortableSource,
    build_portable_sources,
    film_sources_or_none,
    load_film_sources,
    trim_command,
    write_film_sources,
)


def _runner(returncode: int = 0, stdout: str = ""):
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(list(command))
        if returncode == 0 and command[0] != "ffprobe":
            Path(command[-1]).write_bytes(b"clip")
        return subprocess.CompletedProcess(command, returncode, stdout, "")

    run.calls = calls  # type: ignore[attr-defined]
    return run


# --- the map -------------------------------------------------------------------


def test_the_map_is_written_and_read_back(tmp_path: Path) -> None:
    sources = (
        PortableSource(event_id="b", file_name="b.mp4"),
        PortableSource(event_id="a", file_name="a.mp4", start_s=1.5),
    )
    path = tmp_path / FILM_SOURCES_FILE_NAME

    write_film_sources(path, sources)

    assert json.loads(path.read_text())["schema_version"] == FILM_SOURCES_SCHEMA_VERSION
    read = load_film_sources(path)
    assert [source.event_id for source in read] == ["a", "b"]
    assert read[0].start_s == pytest.approx(1.5)
    assert not list(tmp_path.glob("*.part*"))


def test_a_map_of_another_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / FILM_SOURCES_FILE_NAME
    path.write_text(json.dumps({"schema_version": "film-sources-v99", "sources": {}}))

    with pytest.raises(PortablePackageError):
        load_film_sources(path)


def test_a_malformed_map_is_refused(tmp_path: Path) -> None:
    path = tmp_path / FILM_SOURCES_FILE_NAME
    path.write_text(json.dumps({"schema_version": FILM_SOURCES_SCHEMA_VERSION, "sources": []}))
    with pytest.raises(PortablePackageError):
        load_film_sources(path)

    path.write_text(
        json.dumps({"schema_version": FILM_SOURCES_SCHEMA_VERSION, "sources": {"a": {}}})
    )
    with pytest.raises(PortablePackageError):
        load_film_sources(path)


def test_a_source_naming_a_path_is_refused() -> None:
    """A clip name that walks out of the package is a clip from somewhere else."""
    with pytest.raises(PortablePackageError):
        PortableSource(event_id="a", file_name="../elsewhere.mp4")


def test_a_package_without_a_map_carries_the_recordings(tmp_path: Path) -> None:
    assert film_sources_or_none(tmp_path) is None


def test_a_package_with_a_map_reports_it(tmp_path: Path) -> None:
    write_film_sources(
        tmp_path / FILM_SOURCES_FILE_NAME, (PortableSource(event_id="a", file_name="a.mp4"),)
    )

    found = film_sources_or_none(tmp_path)

    assert found is not None and found[0].file_name == "a.mp4"


# --- cutting the clips -----------------------------------------------------------


def test_a_clip_is_cut_at_the_height_the_film_is_cut_at() -> None:
    command = trim_command(Path("in.mp4"), Path("out.mp4"), start_s=12.5, duration_s=12.0)

    assert "-ss" in command and "12.500" in command
    assert "-t" in command and "12.000" in command
    assert "scale=-2:1080" in command
    assert "-an" in command


def test_a_clip_of_no_length_is_refused() -> None:
    with pytest.raises(PortablePackageError):
        trim_command(Path("in.mp4"), Path("out.mp4"), start_s=0.0, duration_s=0.0)


def test_every_window_becomes_one_clip_starting_at_zero(tmp_path: Path) -> None:
    recording = tmp_path / "GX01.MP4"
    recording.write_bytes(b"x")
    run = _runner()

    built = build_portable_sources(
        [("evt-1", recording, 30.0, 12.0), ("evt-2", recording, 60.0, 12.0)],
        tmp_path / "film-sources",
        probe_path=tmp_path / "probe",
        work=tmp_path / "work",
        blur=False,
        runner=run,
    )

    assert [source.event_id for source in built] == ["evt-1", "evt-2"]
    assert all(source.start_s == 0.0 for source in built)
    assert (tmp_path / "film-sources" / "evt-1.mp4").is_file()
    assert len(run.calls) == 2  # type: ignore[attr-defined]


def test_a_window_whose_recording_is_gone_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PortablePackageError):
        build_portable_sources(
            [("evt-1", tmp_path / "absent.MP4", 0.0, 12.0)],
            tmp_path / "out",
            probe_path=tmp_path / "probe",
            work=tmp_path / "work",
            blur=False,
        )


def test_a_cut_that_fails_stops_the_build(tmp_path: Path) -> None:
    recording = tmp_path / "GX01.MP4"
    recording.write_bytes(b"x")

    with pytest.raises(PortablePackageError):
        build_portable_sources(
            [("evt-1", recording, 0.0, 12.0)],
            tmp_path / "out",
            probe_path=tmp_path / "probe",
            work=tmp_path / "work",
            blur=False,
            runner=_runner(returncode=1),
        )


def test_the_one_track_the_package_is_scored_with_travels_with_it(tmp_path: Path) -> None:
    """The tracks are CC BY 4.0, so they may travel as long as the credit does."""
    from app.portable_package import copy_music

    music = tmp_path / "music"
    music.mkdir()
    (music / "Rising Tide.mp3").write_bytes(b"sound")
    (music / "Other.mp3").write_bytes(b"sound")
    (music / "music-catalogue.json").write_text(
        json.dumps(
            {
                "schema_version": "music-catalogue-v1",
                "track_count": 2,
                "tracks": [
                    {"track_id": "rising-tide", "file_name": "Rising Tide.mp3", "artist": "K"},
                    {"track_id": "other", "file_name": "Other.mp3", "artist": "K"},
                ],
            }
        )
    )
    out = tmp_path / "portable"
    out.mkdir()

    copy_music(out, music_directory=music, track_id="rising-tide")

    assert (out / "music" / "Rising Tide.mp3").is_file()
    assert not (out / "music" / "Other.mp3").exists()
    carried = json.loads((out / "music" / "music-catalogue.json").read_text())
    assert carried["track_count"] == 1
    assert [track["track_id"] for track in carried["tracks"]] == ["rising-tide"]


def test_a_track_the_catalogue_does_not_have_is_refused(tmp_path: Path) -> None:
    from app.portable_package import copy_music

    music = tmp_path / "music"
    music.mkdir()
    (music / "music-catalogue.json").write_text(json.dumps({"tracks": []}))

    with pytest.raises(PortablePackageError):
        copy_music(tmp_path / "out", music_directory=music, track_id="rising-tide")


def test_no_track_asked_for_carries_no_music(tmp_path: Path) -> None:
    from app.portable_package import copy_music

    copy_music(tmp_path / "out", music_directory=tmp_path / "absent", track_id=None)

    assert not (tmp_path / "out" / "music").exists()


def _portable(tmp_path: Path) -> Path:
    package = tmp_path / "day-x"
    (package / "film-sources").mkdir(parents=True)
    (package / "film-sources" / "a.mp4").write_bytes(b"clip")
    (package / "ride.gpx").write_bytes(b"<gpx/>")
    write_film_sources(
        package / FILM_SOURCES_FILE_NAME, (PortableSource(event_id="a", file_name="a.mp4"),)
    )
    (package / "local-pipeline-inputs.json").write_text(
        json.dumps(
            {
                "schema_version": "local-pipeline-input-manifest-v1",
                "gpx_path": "/somewhere/else/ride.gpx",
                "video_root": "/somewhere/else/videos",
                "video_to_gps_offset_s": -46831.551,
                "target_duration_s": 300.0,
                "output_language": "ja",
            }
        )
    )
    return package


def test_a_package_is_pointed_at_wherever_it_now_sits(tmp_path: Path) -> None:
    """The machine that built the package is not the machine that will cut it."""
    from app.portable_package import settle_package

    package = _portable(tmp_path)

    settle_package(package)

    payload = json.loads((package / "local-pipeline-inputs.json").read_text())
    assert payload["gpx_path"] == str((package / "ride.gpx").resolve())
    assert payload["video_root"] == str((package / "film-sources").resolve())


def test_a_directory_that_is_not_a_portable_package_is_refused(tmp_path: Path) -> None:
    from app.portable_package import settle_package

    with pytest.raises(PortablePackageError):
        settle_package(tmp_path)

    package = _portable(tmp_path)
    (package / FILM_SOURCES_FILE_NAME).unlink()
    with pytest.raises(PortablePackageError):
        settle_package(package)


def test_a_package_without_its_track_is_refused(tmp_path: Path) -> None:
    from app.portable_package import settle_package

    package = _portable(tmp_path)
    (package / "ride.gpx").unlink()

    with pytest.raises(PortablePackageError):
        settle_package(package)


def test_a_clip_with_a_face_is_dropped_and_one_with_a_plate_is_blurred(tmp_path: Path) -> None:
    """Encoding changes pixels, so a package is finished when a pass finds
    nothing, not when it is built. A face is removed, not blurred."""
    import app.portable_package as module
    from app.plate_blur import Region

    package = _portable(tmp_path)
    clips = package / "film-sources"
    for name in ("b.mp4", "c.mp4"):
        (clips / name).write_bytes(b"clip")
    write_film_sources(
        package / FILM_SOURCES_FILE_NAME,
        (
            PortableSource(event_id="a", file_name="a.mp4"),
            PortableSource(event_id="b", file_name="b.mp4"),
            PortableSource(event_id="c", file_name="c.mp4"),
        ),
    )
    (package / "gemini-video-analysis.json").write_text(
        json.dumps({"analysed": [{"event_id": name} for name in ("a", "b", "c")]})
    )
    looks = {
        "a.mp4": ((), ()),
        "b.mp4": ((Region(start_s=0.0, end_s=1.0, x=0, y=0, width=40, height=20),), ()),
        "c.mp4": ((), (1.0,)),
    }
    blurred: list[str] = []

    def inspect(clip, **kwargs):
        return looks[Path(clip).name]

    def blur(source, output, **kwargs):
        blurred.append(Path(source).name)
        looks[Path(source).name] = ((), ())
        return output

    import app.plate_blur as plate

    plate_inspect, module_blur = plate.inspect_footage, module.blur_until_clean
    plate.inspect_footage = inspect  # type: ignore[assignment]
    module.blur_until_clean = blur  # type: ignore[assignment]
    try:
        result = module.harden_package(
            package, probe_path=tmp_path / "probe", work=tmp_path / "work"
        )
    finally:
        plate.inspect_footage, module.blur_until_clean = plate_inspect, module_blur

    assert result.dropped == ("c",)
    assert result.blurred == ("b",)
    assert not (clips / "c.mp4").exists()
    assert blurred == ["b.mp4"]
    kept = {source.event_id for source in load_film_sources(package / FILM_SOURCES_FILE_NAME)}
    assert kept == {"a", "b"}
    record = json.loads((package / "gemini-video-analysis.json").read_text())
    assert {item["event_id"] for item in record["analysed"]} == {"a", "b"}


def test_a_package_whose_every_clip_is_dropped_is_refused(tmp_path: Path) -> None:
    import app.plate_blur as plate
    import app.portable_package as module

    package = _portable(tmp_path)
    plate_inspect = plate.inspect_footage
    plate.inspect_footage = lambda clip, **kwargs: ((), (1.0,))  # type: ignore[assignment]
    try:
        with pytest.raises(PortablePackageError):
            module.harden_package(package, probe_path=tmp_path / "p", work=tmp_path / "w")
    finally:
        plate.inspect_footage = plate_inspect


def test_what_the_film_shows_is_blurred_in_the_clip_it_came_from(tmp_path: Path) -> None:
    """A clip and the film cut from it are different encodes: clips clean at
    every frame still produced a legible plate once cut."""
    import app.plate_blur as plate
    import app.portable_package as module
    from app.plate_blur import Region

    package = _portable(tmp_path)
    (package / "journey-story-plan.json").write_text(
        json.dumps(
            {
                "beats": [
                    {"screen_duration_s": 6.0, "event_id": None},
                    {"screen_duration_s": 8.0, "event_id": "a"},
                ]
            }
        )
    )
    seen = (Region(start_s=9.0, end_s=10.0, x=100, y=200, width=60, height=40),)
    applied: list[tuple[str, tuple]] = []

    def blur(source, output, regions, **kwargs):
        applied.append((Path(source).name, tuple(regions)))
        return output

    plate_inspect, plate_blur_plates = plate.inspect_footage, plate.blur_plates
    plate.inspect_footage = lambda *a, **k: (seen, ())  # type: ignore[assignment]
    plate.blur_plates = blur  # type: ignore[assignment]
    try:
        changed = module.harden_from_film(
            package,
            tmp_path / "film.mp4",
            probe_path=tmp_path / "p",
            work=tmp_path / "w",
            runner=_runner(stdout="12.0\n"),
        )
    finally:
        plate.inspect_footage, plate.blur_plates = plate_inspect, plate_blur_plates

    assert changed == ("a",)
    name, regions = applied[0]
    assert name == "a.mp4"
    # The box is kept; the time is widened to the whole clip.
    assert regions[0].x == 100 and regions[0].width == 60
    assert regions[0].start_s == 0.0 and regions[0].end_s > 0.0


def test_a_film_that_shows_nothing_changes_no_clip(tmp_path: Path) -> None:
    import app.plate_blur as plate
    import app.portable_package as module

    package = _portable(tmp_path)
    (package / "journey-story-plan.json").write_text(json.dumps({"beats": []}))
    plate_inspect = plate.inspect_footage
    plate.inspect_footage = lambda *a, **k: ((), ())  # type: ignore[assignment]
    try:
        assert (
            module.harden_from_film(
                package, tmp_path / "film.mp4", probe_path=tmp_path / "p", work=tmp_path / "w"
            )
            == ()
        )
    finally:
        plate.inspect_footage = plate_inspect
