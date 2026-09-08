"""Synthetic-fixture tests for assembling the demo from the film's own parts.

FFmpeg and Quick Look are replaced by a runner that records commands and
writes empty files, so what is held is the timeline, what a card may say,
and the shape of the commands -- never the pixels.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.submission.demo_assembly import (
    DEMO_FILE_NAME,
    DEMO_TOTAL_S,
    CaptionedExcerpt,
    Card,
    DemoAssemblyError,
    Excerpt,
    assemble_demo,
    assert_no_private_text,
    caption_html,
    captioned_excerpt_segment_command,
    card_html,
    chapter_cards_in,
    concat_command,
    demo_subtitles,
    demo_timeline,
    excerpt_segment_command,
    still_segment_command,
    timeline_duration_s,
)

_CONSOLE = {
    "stages": [
        {
            "key": "footage_planned",
            "candidate_count": 173,
            "upload_megabytes": 95.1,
            "cost_jpy": 25.56,
            "budget_jpy": 500.0,
        },
        {"key": "copies_prepared", "prepared_count": 173, "wanted_count": 173},
        {"key": "footage_judged", "judged_count": 173, "wanted_count": 173},
        {"key": "story_planned", "beat_count": 41, "total_screen_duration_s": 320.7},
    ]
}


def _timeline(tmp_path: Path):
    bob = tmp_path / "06-bob.png"
    bob.write_bytes(b"\x89PNG")
    return demo_timeline(_CONSOLE, excerpt_start_s=20.4, bob_png=bob)


def test_the_timeline_is_three_minutes_to_the_second(tmp_path: Path) -> None:
    assert timeline_duration_s(_timeline(tmp_path)) == pytest.approx(DEMO_TOTAL_S)


def test_the_console_card_carries_the_figures_a_judge_should_see(tmp_path: Path) -> None:
    console = next(s for s in _timeline(tmp_path) if isinstance(s, Card) and s.key == "console")
    text = " ".join(console.lines)

    for figure in ("173", "95.1 MB", "¥25.56", "173 / 173", "41 beats", "321 s"):
        assert figure in text


def test_no_card_names_a_file_a_path_or_the_package(tmp_path: Path) -> None:
    segments = _timeline(tmp_path)

    assert_no_private_text(segments, forbidden=(str(tmp_path), "GH01", ".MP4", "bridge-e2e-v1"))


def test_a_card_that_would_show_a_path_is_refused() -> None:
    leaky = (Card("x", "Title", ("/Users/someone/private-media/ride.mp4",), 5.0),)

    with pytest.raises(DemoAssemblyError, match="path"):
        assert_no_private_text(leaky, forbidden=())


def test_card_html_escapes_what_it_shows() -> None:
    page = card_html(Card("k", "<b>Title</b>", ("a & b",), 5.0))

    assert "&lt;b&gt;Title&lt;/b&gt;" in page
    assert "a &amp; b" in page
    assert "<b>" not in page


def test_cards_and_excerpts_refuse_nonsense() -> None:
    with pytest.raises(ValueError):
        Card("", "Title", (), 5.0)
    with pytest.raises(ValueError):
        Card("k", "Title", (), 0.0)
    with pytest.raises(ValueError):
        Excerpt("e", -1.0, 5.0)


def test_captioned_excerpts_refuse_nonsense() -> None:
    with pytest.raises(ValueError):
        CaptionedExcerpt("e", -1.0, 5.0, "Title", ())
    with pytest.raises(ValueError):
        CaptionedExcerpt("e", 0.0, 0.0, "Title", ())
    with pytest.raises(ValueError):
        CaptionedExcerpt("e", 0.0, 5.0, "", ())
    with pytest.raises(ValueError):
        CaptionedExcerpt("e", 0.0, 5.0, "Title", (), caption_hold_s=0.0)
    with pytest.raises(ValueError):
        CaptionedExcerpt("e", 0.0, 5.0, "Title", (), caption_hold_s=5.1)


def test_a_captioned_excerpt_without_a_caption_hold_holds_the_whole_excerpt() -> None:
    segment = CaptionedExcerpt("e", 0.0, 12.0, "Title", ())

    assert segment.hold_s == 12.0


def test_the_five_narrated_stretches_are_cut_back_to_back(tmp_path: Path) -> None:
    narrated = [s for s in _timeline(tmp_path) if isinstance(s, CaptionedExcerpt)]

    assert len(narrated) == 5
    offset = 20.4
    for segment in narrated:
        assert segment.start_s == pytest.approx(offset)
        offset += segment.duration_s


def test_caption_html_escapes_what_it_shows() -> None:
    page = caption_html("<b>Title</b>", ("a & b",))

    assert "&lt;b&gt;Title&lt;/b&gt;" in page
    assert "a &amp; b" in page
    assert "<b>" not in page


def test_captioned_excerpt_command_cuts_the_film_and_lays_the_caption_over_it(
    tmp_path: Path,
) -> None:
    segment = CaptionedExcerpt("close", 20.4, 20.0, "Title", ("body",), caption_hold_s=8.0)
    command = captioned_excerpt_segment_command(
        tmp_path / "film.mp4", segment, tmp_path / "caption.png", tmp_path / "out.mp4"
    )
    joined = " ".join(command)

    assert "-ss 20.400 -t 20.000" in joined
    assert str(tmp_path / "film.mp4") in command
    assert str(tmp_path / "caption.png") in command
    assert "overlay=" in joined
    assert "fade=t=out:st=7.600" in joined, "the caption fades out before the excerpt ends"
    assert "eof_action=pass" in joined, "the footage plays on once the caption clip ends"


def test_segment_commands_normalise_to_one_frame_size_and_rate(tmp_path: Path) -> None:
    still = still_segment_command(tmp_path / "card.png", 20.0, tmp_path / "p.mp4")
    excerpt = excerpt_segment_command(
        tmp_path / "film.mp4", Excerpt("e", 20.4, 15.0), tmp_path / "e.mp4"
    )

    for command in (still, excerpt):
        joined = " ".join(command)
        assert "1920:1080" in joined and "fps=30" in joined and "yuv420p" in joined
        assert "libx264" in joined and "aac" in joined
    assert "anullsrc" in " ".join(still)
    assert "-ss 20.400 -t 15.000" in " ".join(excerpt)
    assert "-c copy" in " ".join(concat_command(tmp_path / "l.txt", tmp_path / "o.mp4"))


# --- assembling, with the tools stubbed -----------------------------------------


class _FakeRasteriser:
    name = "fake"

    def command(self, html_path: Path, output_directory: Path, *, size: int) -> tuple[str, ...]:
        return ("qlmanage", str(html_path), str(output_directory))

    def output_path(self, html_path: Path, output_directory: Path) -> Path:
        return output_directory / f"{html_path.name}.png"


def _package(tmp_path: Path) -> Path:
    """Enough of a package for the console to read, plus a 'film'."""
    import json
    from datetime import UTC, datetime, timedelta

    from app.agents import StoryOutputLanguage
    from app.local_pipeline import LocalPipelineInputs
    from app.video import VideoCatalog, VideoCatalogEntry

    start = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
    root = tmp_path / "package"
    root.mkdir()
    (root / "synthetic.mp4").write_bytes(b"a recording")
    step = 4 * 3600.0 / 59
    points = "".join(
        '<trkpt lat="{lat:.6f}" lon="{lon:.6f}"><ele>100</ele><time>{t}</time></trkpt>'.format(
            lat=35.0 + 0.001 * i,
            lon=139.0 + 0.001 * i,
            t=(start + timedelta(seconds=step * i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        for i in range(60)
    )
    (root / "ride.gpx").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="t" '
        'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        + points
        + "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    inputs = LocalPipelineInputs(
        gpx_path=(root / "ride.gpx").resolve(),
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
                recorded_start_time=start + timedelta(seconds=600),
                duration_s=120.0,
            ),
        ),
        video_to_gps_offset_s=0.0,
    )
    (root / "local-video-catalog.json").write_text(json.dumps(catalog.to_dict()), encoding="utf-8")
    (root / "ride-storyteller-story-film-scored.mp4").write_bytes(b"film")
    return root


def _recording_runner(seen: list[list[str]]):
    def run(command, capture_output=True, text=True, check=False):
        seen.append(command)
        # Whatever the tool would write, write something at its output path.
        if command[0] == "qlmanage":
            Path(command[2]).joinpath(Path(command[1]).name + ".png").write_bytes(b"\x89PNG")
        else:
            Path(command[-1]).write_bytes(b"mp4")
        return subprocess.CompletedProcess(command, 0, "", "")

    return run


def test_assembly_draws_every_card_and_caption_cuts_the_stretches_and_joins(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    bob = tmp_path / "06-bob.png"
    bob.write_bytes(b"\x89PNG")
    cards = (tmp_path / "c1.png", tmp_path / "c2.png")
    for c in cards:
        c.write_bytes(b"\x89PNG")
    srt = tmp_path / "demo-subtitles-en.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:05,000\nHello\n", encoding="utf-8")
    seen: list[list[str]] = []

    out = assemble_demo(
        package,
        bob_png=bob,
        subtitles=srt,
        chapter_cards=cards,
        excerpt_start_s=20.4,
        rasteriser=_FakeRasteriser(),
        runner=_recording_runner(seen),
    )

    assert out == package / "demo" / DEMO_FILE_NAME
    assert out.is_file()
    assert (package / "demo" / "demo-subtitles-en.srt").is_file()
    kinds = [c[0] for c in seen]
    assert kinds.count("qlmanage") == 6, "one console card + five captions"
    assert sum(1 for c in seen if c[0] == "ffmpeg" and "-loop" in c) == 9, (
        "one console card + three stills + five captioned excerpts"
    )
    assert sum(1 for c in seen if c[0] == "ffmpeg" and "-ss" in c) == 5, "five narrated stretches"
    assert sum(1 for c in seen if "concat" in c) == 1
    assert not any(p.name.startswith(".assembling-") for p in (package / "demo").iterdir())


def test_a_second_assembly_needs_overwrite(tmp_path: Path) -> None:
    package = _package(tmp_path)
    bob = tmp_path / "06-bob.png"
    bob.write_bytes(b"\x89PNG")
    cards = (tmp_path / "c1.png", tmp_path / "c2.png")
    for c in cards:
        c.write_bytes(b"\x89PNG")
    srt = tmp_path / "s.srt"
    srt.write_text("x", encoding="utf-8")
    kwargs = dict(
        bob_png=bob,
        subtitles=srt,
        chapter_cards=cards,
        excerpt_start_s=0.0,
        rasteriser=_FakeRasteriser(),
        runner=_recording_runner([]),
    )

    assemble_demo(package, **kwargs)
    with pytest.raises(FileExistsError):
        assemble_demo(package, **kwargs)
    assemble_demo(package, overwrite=True, **kwargs)


def test_a_package_without_a_film_cannot_be_demoed(tmp_path: Path) -> None:
    package = _package(tmp_path)
    (package / "ride-storyteller-story-film-scored.mp4").unlink()
    bob = tmp_path / "b.png"
    bob.write_bytes(b"x")

    with pytest.raises(DemoAssemblyError, match="no finished film"):
        assemble_demo(
            package,
            bob_png=bob,
            subtitles=bob,
            chapter_cards=(bob, bob),
            excerpt_start_s=0.0,
            rasteriser=_FakeRasteriser(),
            runner=_recording_runner([]),
        )


def test_a_failing_tool_leaves_no_demo_and_no_scratch(tmp_path: Path) -> None:
    package = _package(tmp_path)
    bob = tmp_path / "b.png"
    bob.write_bytes(b"x")

    def failing(command, capture_output=True, text=True, check=False):
        return subprocess.CompletedProcess(command, 1, "", "boom")

    with pytest.raises(DemoAssemblyError):
        assemble_demo(
            package,
            bob_png=bob,
            subtitles=bob,
            chapter_cards=(bob, bob),
            excerpt_start_s=0.0,
            rasteriser=_FakeRasteriser(),
            runner=failing,
        )
    assert not (package / "demo" / DEMO_FILE_NAME).exists()
    assert not any(p.name.startswith(".assembling-") for p in (package / "demo").iterdir())


def test_the_command_line_refuses_a_package_without_a_film(tmp_path: Path) -> None:
    from app.submission.demo_assembly import main

    package = _package(tmp_path)
    (package / "ride-storyteller-story-film-scored.mp4").unlink()

    with pytest.raises(SystemExit, match="no finished film"):
        main([str(package)])


def test_the_subtitles_are_written_from_the_timeline_they_are_cut_to(tmp_path: Path) -> None:
    """A hand-timed subtitle file drifts the moment a hold changes; these cannot."""
    segments = _timeline(tmp_path)
    text = demo_subtitles(segments)

    assert text.startswith("1\n00:00:00,000 --> 00:00:20,000\n")
    # One cue per segment that says something; the stills say nothing.
    spoken = sum(1 for segment in segments if isinstance(segment, CaptionedExcerpt | Card))
    assert text.count(" --> ") == spoken
    assert text.endswith("\n\n")


def test_the_demo_takes_two_chapter_cards_the_package_actually_has(tmp_path: Path) -> None:
    """A day has as many cards as chapters, so a fixed pair of names fits some
    packages and not others."""
    cards = tmp_path / "story-cards"
    cards.mkdir()
    for name in ("card-001.html.png", "card-002.html.png", "card-003.html.png"):
        (cards / name).write_bytes(b"x")
    # Frames of a card are not the card.
    (cards / "card-002-f004.html.png").write_bytes(b"x")

    assert [p.name for p in chapter_cards_in(cards)] == ["card-001.html.png", "card-003.html.png"]
    named = chapter_cards_in(cards, "card-002.html.png", "card-003.html.png")
    assert [p.name for p in named] == ["card-002.html.png", "card-003.html.png"]


def test_a_package_with_one_chapter_card_cannot_be_demoed(tmp_path: Path) -> None:
    cards = tmp_path / "story-cards"
    cards.mkdir()
    (cards / "card-001.html.png").write_bytes(b"x")

    with pytest.raises(DemoAssemblyError, match="fewer than two chapter cards"):
        chapter_cards_in(cards)
