"""Synthetic-fixture tests for cutting the planned film."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.journey_gaps import JourneyGapKind, JourneyGapPlan, JourneyGapSegment
from app.story_film import (
    CARD_RASTER_SIZE,
    HEADLESS_CHROMIUM,
    QUICK_LOOK,
    STORY_FILM_FPS,
    STORY_FILM_HEIGHT,
    STORY_FILM_NORMALIZE_INDEPENDENCE,
    STORY_FILM_NORMALIZE_SMOOTHING,
    STORY_FILM_NORMALIZE_STRENGTH,
    STORY_FILM_WIDTH,
    FootageSource,
    StoryFilmError,
    StoryFilmSegment,
    build_card_raster_command,
    build_story_film_command,
    build_story_film_segments,
    card_raster_path,
    render_story_film,
    write_chapter_cards,
)
from app.story_package import build_journey_story_plan
from app.story_timeline import StoryBeatKind, TimelineFootage, build_story_timeline

_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _at(offset_s: float) -> datetime:
    return _START + timedelta(seconds=offset_s)


def _plan():
    footage = tuple(
        TimelineFootage(
            event_id=f"evt_{index}",
            start_time=_at(3600.0 * (index + 1)),
            end_time=_at(3600.0 * (index + 1) + 30.0),
        )
        for index in range(2)
    )
    gaps = (
        JourneyGapSegment(
            kind=JourneyGapKind.BEFORE_FIRST_CLIP,
            start_time=_at(0.0),
            end_time=_at(3600.0),
            distance_m=42_000.0,
            elevation_gain_m=300.0,
            elevation_loss_m=120.0,
        ),
        JourneyGapSegment(
            kind=JourneyGapKind.AFTER_LAST_CLIP,
            start_time=_at(7230.0),
            end_time=_at(9000.0),
            distance_m=12_000.0,
            elevation_gain_m=20.0,
            elevation_loss_m=180.0,
        ),
    )
    return build_journey_story_plan(
        build_story_timeline(footage, JourneyGapPlan(gaps)),
    )


def _segment(kind: StoryBeatKind, path: Path, duration_s: float = 5.0) -> StoryFilmSegment:
    return StoryFilmSegment(kind=kind, input_path=path, duration_s=duration_s)


def _ok(*_args, **_kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=0, stdout="", stderr="")


def _drawing_runner(directory: Path):
    """Stand in for Quick Look: every page named in the command gets its PNG.

    qlmanage takes any number of pages in one call and writes one image per
    page; a frame sequence relies on exactly that.
    """

    def run(command, check=False, capture_output=True, text=True, timeout=60):
        out_dir = Path(command[command.index("-o") + 1])
        for argument in command:
            if str(argument).endswith(".html"):
                (out_dir / f"{Path(argument).name}.png").write_bytes(b"\x89PNG")
        return subprocess.CompletedProcess(list(command), 0, "", "")

    return run


# --- the command that cuts the film ----------------------------------------


def test_command_holds_each_segment_for_its_planned_length(tmp_path: Path) -> None:
    segments = (
        _segment(StoryBeatKind.GAP_CARD, tmp_path / "card.png", 12.0),
        _segment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4", 30.0),
    )

    command = build_story_film_command(segments, tmp_path / "film.mp4")

    assert "12.000" in command
    assert "30.000" in command


def test_only_a_card_is_looped(tmp_path: Path) -> None:
    """Footage already moves; a card is one image held."""
    command = build_story_film_command(
        (
            _segment(StoryBeatKind.GAP_CARD, tmp_path / "card.png"),
            _segment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4"),
        ),
        tmp_path / "film.mp4",
    )

    assert command.count("-loop") == 1
    assert command[command.index("-loop") + 2] == "-t"


def test_only_a_card_is_cropped_to_the_frame(tmp_path: Path) -> None:
    """The card was drawn square; the clip was already shot wide."""
    command = build_story_film_command(
        (
            _segment(StoryBeatKind.GAP_CARD, tmp_path / "card.png"),
            _segment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4"),
        ),
        tmp_path / "film.mp4",
    )
    graph = command[command.index("-filter_complex") + 1]

    assert graph.count("crop=") == 1
    assert f"crop=iw:iw*{STORY_FILM_HEIGHT}/{STORY_FILM_WIDTH}" in graph


def test_every_segment_is_normalised_before_being_joined(tmp_path: Path) -> None:
    """The concat filter refuses streams that disagree, so none may."""
    segments = tuple(
        _segment(kind, tmp_path / f"{index}.bin")
        for index, kind in enumerate(
            (StoryBeatKind.GAP_CARD, StoryBeatKind.FOOTAGE, StoryBeatKind.GAP_CARD)
        )
    )

    graph = build_story_film_command(segments, tmp_path / "film.mp4")[
        build_story_film_command(segments, tmp_path / "film.mp4").index("-filter_complex") + 1
    ]

    assert graph.count(f"scale={STORY_FILM_WIDTH}:{STORY_FILM_HEIGHT}") == 3
    assert graph.count(f"fps={STORY_FILM_FPS}") == 3
    assert graph.count("format=yuv420p") == 3
    assert graph.count("setsar=1") == 3
    assert "concat=n=3:v=1:a=0[v]" in graph


def test_footage_is_colour_normalised_but_a_card_is_not(tmp_path: Path) -> None:
    """E-6: exposure/contrast is stretched on filmed windows, not on a drawing."""
    segments = (
        _segment(StoryBeatKind.GAP_CARD, tmp_path / "card.png"),
        _segment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4"),
    )

    command = build_story_film_command(segments, tmp_path / "film.mp4")
    graph = command[command.index("-filter_complex") + 1]

    assert graph.count("normalize=") == 1
    expected = (
        "normalize="
        f"independence={STORY_FILM_NORMALIZE_INDEPENDENCE}:"
        f"strength={STORY_FILM_NORMALIZE_STRENGTH}:"
        f"smoothing={STORY_FILM_NORMALIZE_SMOOTHING}"
    )
    assert expected in graph


def test_normalize_runs_before_the_frame_is_scaled_down(tmp_path: Path) -> None:
    """Normalising the shot frame, not a letterboxed one, keeps the stretch honest."""
    command = build_story_film_command(
        (_segment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4"),), tmp_path / "film.mp4"
    )
    graph = command[command.index("-filter_complex") + 1]

    assert graph.index("normalize=") < graph.index(f"scale={STORY_FILM_WIDTH}:{STORY_FILM_HEIGHT}")


def test_the_film_carries_no_audio(tmp_path: Path) -> None:
    """Engine and wind noise are dropped; music is chosen separately."""
    command = build_story_film_command(
        (_segment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4"),), tmp_path / "film.mp4"
    )

    assert "-an" in command
    assert "a=0" in command[command.index("-filter_complex") + 1]


def test_an_empty_film_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StoryFilmError, match="at least one segment"):
        build_story_film_command((), tmp_path / "film.mp4")


def test_a_segment_with_no_duration_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="held on screen"):
        _segment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4", 0.0)


# --- pairing beats with the files that fill them ----------------------------


def test_segments_follow_the_plan_in_order(tmp_path: Path) -> None:
    plan = _plan()
    cards = (tmp_path / "a.png", tmp_path / "b.png")
    sources = {}
    for beat in plan.footage_beats:
        path = tmp_path / f"{beat.event_id}.mp4"
        path.write_bytes(b"clip")
        sources[beat.event_id] = FootageSource(path=path, start_s=1_800.0)

    segments = build_story_film_segments(plan, cards, sources)

    assert [segment.kind for segment in segments] == [beat.kind for beat in plan.beats]
    assert [segment.duration_s for segment in segments] == [
        beat.screen_duration_s for beat in plan.beats
    ]
    assert segments[0].input_path == cards[0]
    # A card is its own file; footage is a window inside a long recording.
    assert segments[0].source_start_s is None
    assert all(
        segment.source_start_s == 1_800.0
        for segment in segments
        if segment.kind is StoryBeatKind.FOOTAGE
    )


def test_a_beat_with_no_confirmed_clip_stops_the_cut(tmp_path: Path) -> None:
    """Dropping it would leave a shorter film that still looked complete."""
    plan = _plan()

    with pytest.raises(StoryFilmError, match="no confirmed clip"):
        build_story_film_segments(plan, (tmp_path / "a.png", tmp_path / "b.png"), {})


def test_a_missing_or_symlinked_clip_stops_the_cut(tmp_path: Path) -> None:
    plan = _plan()
    cards = (tmp_path / "a.png", tmp_path / "b.png")
    absent = {
        beat.event_id: FootageSource(path=tmp_path / "gone.mp4", start_s=0.0)
        for beat in plan.footage_beats
    }
    with pytest.raises(StoryFilmError, match="clip is unavailable"):
        build_story_film_segments(plan, cards, absent)

    real = tmp_path / "real.mp4"
    real.write_bytes(b"clip")
    link = tmp_path / "link.mp4"
    link.symlink_to(real)
    with pytest.raises(StoryFilmError, match="clip is unavailable"):
        build_story_film_segments(
            plan,
            cards,
            {beat.event_id: FootageSource(path=link, start_s=0.0) for beat in plan.footage_beats},
        )


def test_footage_is_cut_from_a_window_inside_its_recording(tmp_path: Path) -> None:
    """The film uses the ride's own footage, not the 720p review proxy."""
    recording = tmp_path / "GH011147.MP4"
    recording.write_bytes(b"four kay")

    command = build_story_film_command(
        (
            StoryFilmSegment(
                kind=StoryBeatKind.FOOTAGE,
                input_path=recording,
                duration_s=30.0,
                source_start_s=3_600.0,
            ),
        ),
        tmp_path / "film.mp4",
    )

    # Seeking before the input makes FFmpeg jump rather than decode its way in.
    assert command.index("-ss") < command.index("-i")
    assert command[command.index("-ss") + 1] == "3600.000"


def test_a_source_window_cannot_start_before_its_recording(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="before its source"):
        StoryFilmSegment(
            kind=StoryBeatKind.FOOTAGE,
            input_path=tmp_path / "a.mp4",
            duration_s=30.0,
            source_start_s=-1.0,
        )
    with pytest.raises(ValueError, match="before its recording"):
        FootageSource(path=tmp_path / "a.mp4", start_s=-1.0)


def test_a_card_count_that_does_not_match_the_plan_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StoryFilmError, match="do not match the plan"):
        build_story_film_segments(_plan(), (tmp_path / "a.png",), {})


# --- drawing the cards ------------------------------------------------------


def test_cards_are_drawn_one_per_gap_beat(tmp_path: Path) -> None:
    plan = _plan()

    rasters = tuple(
        r.still for r in write_chapter_cards(plan, tmp_path, runner=_drawing_runner(tmp_path))
    )

    assert len(rasters) == len(plan.card_beats)
    assert all(raster.is_file() for raster in rasters)
    assert (tmp_path / "story-cards" / "card-001.html").is_file()


def test_card_html_carries_the_planned_text(tmp_path: Path) -> None:
    plan = _plan()

    write_chapter_cards(plan, tmp_path, runner=_drawing_runner(tmp_path))

    html = (tmp_path / "story-cards" / "card-001.html").read_text(encoding="utf-8")
    assert plan.card_beats[0].card.title in html
    assert plan.card_beats[0].card.body in html


def test_a_card_that_cannot_be_drawn_stops_the_render(tmp_path: Path) -> None:
    def failing(*_args, **_kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=(), returncode=1, stdout="", stderr="no")

    with pytest.raises(StoryFilmError, match="could not be drawn"):
        write_chapter_cards(_plan(), tmp_path, runner=failing)


def test_a_silent_failure_that_writes_nothing_still_stops_the_render(tmp_path: Path) -> None:
    """A zero exit code with no file is a failure, not a success."""

    def quiet(*_args, **_kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=(), returncode=0, stdout="", stderr="")

    with pytest.raises(StoryFilmError, match="could not be drawn"):
        write_chapter_cards(_plan(), tmp_path, runner=quiet)


def test_a_machine_without_the_rasteriser_is_reported_plainly(tmp_path: Path) -> None:
    def absent(*_args, **_kwargs):
        raise FileNotFoundError("qlmanage")

    with pytest.raises(StoryFilmError, match="quick-look rasteriser is required"):
        write_chapter_cards(_plan(), tmp_path, runner=absent)


def test_the_raster_command_names_quick_look_and_its_output(tmp_path: Path) -> None:
    command = build_card_raster_command(tmp_path / "card-001.html", tmp_path)

    assert command[0] == "qlmanage"
    assert "-t" in command
    assert str(tmp_path) in command
    assert card_raster_path(tmp_path / "card-001.html", tmp_path).name == "card-001.html.png"


def test_a_linux_container_draws_the_same_card_with_chromium(tmp_path: Path) -> None:
    """Cloud Run has no Quick Look, so the same HTML is drawn by Chromium."""
    html_path = tmp_path / "card-001.html"

    command = build_card_raster_command(html_path, tmp_path, rasteriser=HEADLESS_CHROMIUM)

    assert command[0] == "chromium"
    assert "--headless=new" in command
    # The same square as Quick Look, so the film's crop is identical either way.
    assert f"--window-size={CARD_RASTER_SIZE},{CARD_RASTER_SIZE}" in command
    assert command[-1] == html_path.as_uri()
    assert card_raster_path(html_path, tmp_path, rasteriser=HEADLESS_CHROMIUM) == card_raster_path(
        html_path, tmp_path, rasteriser=QUICK_LOOK
    )


def test_the_chosen_rasteriser_is_the_one_run(tmp_path: Path) -> None:
    seen: list[str] = []

    def runner(command, **_kwargs) -> subprocess.CompletedProcess[str]:
        seen.append(command[0])
        html_path = Path(command[-1].removeprefix("file://"))
        card_raster_path(html_path, tmp_path / "story-cards").write_bytes(b"\x89PNG")
        return _ok()

    write_chapter_cards(_plan(), tmp_path, rasteriser=HEADLESS_CHROMIUM, runner=runner)

    assert set(seen) == {"chromium"}


# --- running the cut --------------------------------------------------------


def _writing_runner() -> object:
    """Stand in for FFmpeg by writing to the path the command actually names."""

    def runner(command, **_kwargs) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"film")
        return _ok()

    return runner


def test_a_successful_cut_reports_what_it_made(tmp_path: Path) -> None:
    output = tmp_path / "film.mp4"
    runner = _writing_runner()

    result = render_story_film(
        (
            _segment(StoryBeatKind.GAP_CARD, tmp_path / "card.png", 12.0),
            _segment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4", 30.0),
        ),
        output,
        runner=runner,
    )

    assert result.card_segment_count == 1
    assert result.footage_segment_count == 1
    assert result.duration_s == pytest.approx(42.0)
    assert result.to_dict()["audio_included"] is False
    assert result.to_dict()["external_data_sent"] is False
    assert output.is_file()


def test_an_interrupted_cut_leaves_no_film_at_all(tmp_path: Path) -> None:
    """A half-written MP4 has no index: it looks finished and will not play."""
    output = tmp_path / "film.mp4"

    def dying(command, **_kwargs) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"half a film")
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=1.0)

    with pytest.raises(StoryFilmError, match="timed out"):
        render_story_film(
            (_segment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4"),), output, runner=dying
        )

    assert not output.exists()
    assert list(tmp_path.glob(".*partial*")) == []


def test_a_failed_cut_leaves_the_earlier_film_untouched(tmp_path: Path) -> None:
    output = tmp_path / "film.mp4"
    output.write_bytes(b"the film from last time")

    def failing(command, **_kwargs) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"rubbish")
        return subprocess.CompletedProcess(args=(), returncode=1, stdout="", stderr="bad")

    with pytest.raises(StoryFilmError, match="could not cut"):
        render_story_film(
            (_segment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4"),),
            output,
            overwrite=True,
            runner=failing,
        )

    assert output.read_bytes() == b"the film from last time"


def test_a_failed_cut_is_reported(tmp_path: Path) -> None:
    def failing(*_args, **_kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=(), returncode=1, stdout="", stderr="bad")

    with pytest.raises(StoryFilmError, match="could not cut"):
        render_story_film(
            (_segment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4"),),
            tmp_path / "film.mp4",
            runner=failing,
        )


def test_a_cut_that_produces_no_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(StoryFilmError, match="did not create"):
        render_story_film(
            (_segment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4"),),
            tmp_path / "film.mp4",
            runner=_ok,
        )


def test_an_existing_film_is_not_replaced_by_accident(tmp_path: Path) -> None:
    output = tmp_path / "film.mp4"
    output.write_bytes(b"earlier")

    with pytest.raises(FileExistsError):
        render_story_film(
            (_segment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4"),), output, runner=_ok
        )


def test_a_symlinked_output_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real.mp4"
    real.write_bytes(b"film")
    link = tmp_path / "link.mp4"
    link.symlink_to(real)

    with pytest.raises(StoryFilmError, match="output path is unsafe"):
        render_story_film(
            (_segment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4"),), link, runner=_ok
        )


def test_a_missing_ffmpeg_is_reported_plainly(tmp_path: Path) -> None:
    def absent(*_args, **_kwargs):
        raise FileNotFoundError("ffmpeg")

    with pytest.raises(StoryFilmError, match="ffmpeg is required"):
        render_story_film(
            (_segment(StoryBeatKind.FOOTAGE, tmp_path / "clip.mp4"),),
            tmp_path / "film.mp4",
            runner=absent,
        )


def test_chromium_is_given_absolute_paths_even_for_a_relative_package(
    tmp_path: Path, monkeypatch
) -> None:
    """A judge names the package relatively from the clone; a file URI has no relative form."""
    monkeypatch.chdir(tmp_path)
    html_path = Path("cards") / "card-001.html"
    html_path.parent.mkdir()
    html_path.write_text("<html></html>", encoding="utf-8")

    command = build_card_raster_command(html_path, Path("cards"), rasteriser=HEADLESS_CHROMIUM)

    assert command[-1] == html_path.resolve().as_uri()
    assert command[-1].startswith("file:///")
    screenshot = next(part for part in command if part.startswith("--screenshot="))
    assert Path(screenshot.removeprefix("--screenshot=")).is_absolute()
