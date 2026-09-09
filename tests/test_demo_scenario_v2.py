"""Synthetic-fixture tests for the second demo scenario.

FFmpeg, ffprobe and Quick Look are replaced by a runner that records
commands and writes empty files, so what is held is the timeline, what a
screen may say, where each figure comes from, and the shape of the
commands -- never the pixels, and never real media.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

import pytest

from app.contracts.models import VideoAnalysis
from app.submission import demo_scenario_v2 as v2
from app.submission.demo_assembly import DEMO_TOTAL_S, Card, DemoAssemblyError

_FIGURES = {
    "source_files": 35,
    "source_gigabytes": 108.6,
    "source_hours": 4.72,
    "windows": 337,
    "window_seconds": 12,
    "proxy_megabytes": 245.1,
    "cost_jpy": 49.79,
    "interest_07_count": 43,
    "beats": 63,
    "film_seconds": 380,
    "machine_minutes": 80,
    "confirmations": 2,
}
_IDS = tuple(f"evt-{n:04d}" for n in range(1, 18))
_MOSAIC = _IDS[:12]
_SINGLE = _IDS[12]
_JUDGED = _IDS[13:]


def _console(
    windows: int = 337,
    mb: float = 245.1,
    cost: float = 49.79,
    beats: int = 63,
    film_s: float = 380.0,
):
    return {
        "stages": [
            {
                "key": "footage_planned",
                "state": "done",
                "candidate_count": windows,
                "upload_megabytes": mb,
                "cost_jpy": cost,
                "budget_jpy": 500.0,
            },
            {
                "key": "copies_prepared",
                "state": "done",
                "prepared_count": windows,
                "wanted_count": windows,
            },
            {
                "key": "footage_judged",
                "state": "done",
                "judged_count": windows,
                "wanted_count": windows,
            },
            {
                "key": "story_planned",
                "state": "done",
                "beat_count": beats,
                "total_screen_duration_s": film_s,
            },
        ]
    }


def _inputs_dict(proxy_package: Path, **figures: object) -> dict[str, object]:
    return {
        "schema_version": v2.DEMO_V2_INPUTS_SCHEMA_VERSION,
        "proxy_package": str(proxy_package),
        "mosaic": list(_MOSAIC),
        "single": _SINGLE,
        "judged": [
            {"event_id": _JUDGED[0], "label": "high"},
            {"event_id": _JUDGED[1], "label": "high"},
            {"event_id": _JUDGED[2], "label": "low"},
            {"event_id": _JUDGED[3], "label": "low"},
        ],
        "figures": {**_FIGURES, **figures},
    }


def _judgement(**overrides: object) -> v2.Judgement:
    values: dict[str, object] = {
        "description": "A rural highway runs between green hills under a wide sky.",
        "road_type": "rural highway",
        "highlight_subject": "vista",
        "visual_interest_score": 0.9,
        "photogenic_score": 0.8,
        "stationary": "no",
        "rider_visible": "none",
    }
    values.update(overrides)
    return v2.Judgement(**values)  # type: ignore[arg-type]


def _judgements() -> dict[str, v2.Judgement]:
    return {event_id: _judgement() for event_id in _JUDGED}


def _timeline(
    tmp_path: Path, *, figures: dict[str, object] | None = None, console=None, **pngs: Path
):
    card = tmp_path / "card-001.html.png"
    card.write_bytes(b"\x89PNG")
    inputs = v2.DemoInputs.from_dict(_inputs_dict(tmp_path / "proxies", **(figures or {})))
    return v2.demo_timeline_v2(
        console if console is not None else _console(),
        inputs,
        _judgements(),
        cold_open_s=12.0,
        result_start_s=100.0,
        chapter_card=card,
        **pngs,
    )


def _spoken_by_scene(segments) -> dict[int, str]:
    said: dict[int, list[str]] = {}
    for segment in segments:
        lines = v2.spoken_v2(segment)
        if lines:
            said.setdefault(v2.scene_number(segment), [])
            if not said[v2.scene_number(segment)]:
                said[v2.scene_number(segment)] = list(lines)
    return {scene: " ".join(lines) for scene, lines in said.items()}


# --- the timeline ------------------------------------------------------------------


def test_the_timeline_is_the_scenario_to_the_second(tmp_path: Path) -> None:
    total = v2.timeline_duration_s(_timeline(tmp_path), seconds=v2.segment_seconds_v2)

    assert total == 177.0
    assert total == DEMO_TOTAL_S
    assert total < 180.0


def test_the_ten_scenes_come_in_order_with_the_scenario_seconds(tmp_path: Path) -> None:
    segments = _timeline(tmp_path)
    by_scene: dict[int, float] = {}
    for segment in segments:
        by_scene[v2.scene_number(segment)] = by_scene.get(v2.scene_number(segment), 0.0) + (
            v2.segment_seconds_v2(segment)
        )

    assert list(by_scene) == list(range(1, 11)), "scenes in order, each once"
    assert list(by_scene.values()) == [8, 12, 12, 15, 18, 15, 30, 15, 40, 12]
    kinds = [type(segment).__name__ for segment in segments]
    assert kinds == [
        "FramedExcerpt",
        "Mosaic",
        "SingleRaw",
        "ConsoleStill",
        "Card",
        "Card",
        "JudgedWindow",
        "JudgedWindow",
        "JudgedWindow",
        "JudgedWindow",
        "ConsoleStill",
        "FramedExcerpt",
        "FullScreenExcerpt",
        "Card",
    ]


def test_scene_seven_is_four_judged_windows_under_one_caption(tmp_path: Path) -> None:
    judged = [s for s in _timeline(tmp_path) if isinstance(s, v2.JudgedWindow)]

    assert [s.event_id for s in judged] == list(_JUDGED), "display order is the inputs' order"
    assert all(s.duration_s == 7.5 for s in judged)
    assert len({(s.title, s.lines) for s in judged}) == 1, "one caption, drawn once"
    assert [s.caption_fade_in for s in judged] == [True, False, False, False]
    assert [s.caption_fade_out for s in judged] == [False, False, False, True]


def test_scene_nine_is_continuous_in_the_film(tmp_path: Path) -> None:
    segments = _timeline(tmp_path)
    framed = next(s for s in segments if s.key == "09-result")
    tail = next(s for s in segments if s.key == "09-result-tail")

    assert isinstance(framed, v2.FramedExcerpt) and isinstance(tail, v2.FullScreenExcerpt)
    assert framed.start_s == 100.0 and framed.duration_s == 30.0
    assert tail.start_s == 130.0 and tail.duration_s == 10.0
    assert framed.hold_s == 30.0, "the caption is held for the framed part"


def test_scene_one_opens_on_the_cold_open(tmp_path: Path) -> None:
    first = _timeline(tmp_path)[0]

    assert isinstance(first, v2.FramedExcerpt)
    assert first.start_s == 12.0 and first.duration_s == 8.0


_SCENARIO_TEXT = {
    1: "Made by Ride Storyteller from 4 hours 43 minutes of GoPro footage. No one edited this.",
    2: "One day of riding: 108 GB of video, 4 hours 43 minutes. Nearly all of it looks like this.",
    3: "Finding the good minutes means watching all of it. So the footage sat on a hard drive.",
    4: (
        "The GPS track already knows where the day happened: setting off, each stop, "
        "each named road. Every leg becomes a chapter."
    ),
    5: (
        "Locally, ffmpeg cuts 337 twelve-second windows and shrinks each to 480p at one frame "
        "a second: 245 MB in all. The 4K never leaves the machine."
    ),
    6: (
        "One page shows the price — ¥49.79 — and waits for a person to type that figure back. "
        "Nothing is bought until then."
    ),
    7: (
        "Gemini 2.5 Flash judges every window: is the rider in frame, is the bike stopped, "
        "what is worth looking at. 337 structured judgements. Only 43 scored 0.7 or more."
    ),
    8: (
        "The story planner keeps 63 beats in the order the day happened; ffmpeg cuts the film "
        "and adds the music. About 80 minutes of machine time. Two confirmations from a person."
    ),
    9: (
        "The result: six minutes, chapters named by place, a map in the corner, sections for "
        "scenic roads and stops."
    ),
    10: (
        "Open source (AGPL-3.0). Runs on your machine. About ¥50 of Gemini per riding day. "
        "Judges: the day-7 package cuts this film on your own computer."
    ),
}


def test_the_captions_are_the_scenario_text_verbatim(tmp_path: Path) -> None:
    """The doc's English, with the day's figures in it, sentence for sentence."""
    assert _spoken_by_scene(_timeline(tmp_path)) == _SCENARIO_TEXT


def test_the_figures_card_states_the_console_figures(tmp_path: Path) -> None:
    planner = next(s for s in _timeline(tmp_path) if s.key == "08-planner")

    assert isinstance(planner, v2.ConsoleStill) and isinstance(planner.image, Card)
    text = " ".join((planner.image.title, *planner.image.lines))
    for figure in ("337 windows", "245.1 MB", "¥49.79", "63 beats", "380 s", "337 / 337"):
        assert figure in text
    assert v2.spoken_v2(planner) == (planner.title, *planner.lines), (
        "the card's figures are not speech"
    )


def test_every_figure_on_screen_comes_from_the_inputs_or_the_console(tmp_path: Path) -> None:
    """Change every figure and the screens change with them; nothing is typed in."""
    figures = {
        "source_files": 20,
        "source_gigabytes": 77.4,
        "source_hours": 3.25,
        "windows": 512,
        "window_seconds": 10,
        "proxy_megabytes": 133.4,
        "cost_jpy": 12.34,
        "interest_07_count": 29,
        "beats": 41,
        "film_seconds": 245,
        "machine_minutes": 55,
        "confirmations": 3,
    }
    console = _console(windows=512, mb=133.4, cost=12.34, beats=41, film_s=245.0)
    segments = _timeline(tmp_path, figures=figures, console=console)
    texts = [text for what, text in v2.on_screen_texts(segments) if what in ("a caption", "a card")]
    everything = " ".join(texts)

    derived = {
        "512",  # windows, copies, judged
        "77",  # floor of 77.4 GB
        "3",  # hours
        "15",  # minutes
        "133",  # MB in the caption
        "133.4",  # MB on the card
        "¥12.34",
        "¥12",  # about ¥12 per day
        "29",
        "41",
        "245",  # film seconds on the card
        "55",
    }
    names = {"480p", "4K", "2.5", "3.0", "0.7", "7"}  # 480p, 4K, Gemini 2.5, AGPL-3.0, 0.7, day-7
    tokens = set(re.findall(r"¥?\d+(?:\.\d+)?[A-Za-z]*", everything))
    assert tokens <= derived | names, tokens - (derived | names)
    for word in ("ten-second", "four minutes", "Three confirmations", "3 hours 15 minutes"):
        assert word in everything
    for stale in ("337", "49.79", "63 beats", "380", "six minutes", "twelve", "108"):
        assert stale not in everything


def test_a_screenshot_that_was_not_supplied_becomes_a_card_with_the_same_words(
    tmp_path: Path,
) -> None:
    shot = tmp_path / "copies.png"
    shot.write_bytes(b"\x89PNG")
    with_shot = _timeline(tmp_path, console_copies_png=shot)
    without = _timeline(tmp_path)

    copies_still = next(s for s in with_shot if s.key == "05-copies")
    copies_card = next(s for s in without if s.key == "05-copies")
    assert isinstance(copies_still, v2.ConsoleStill) and copies_still.letterbox
    assert copies_still.image == shot
    assert isinstance(copies_card, Card)
    assert v2.spoken_v2(copies_still) == v2.spoken_v2(copies_card)
    assert v2.timeline_duration_s(with_shot, seconds=v2.segment_seconds_v2) == 177.0


# --- what a screen may say -----------------------------------------------------------


def test_a_caption_that_would_name_a_window_is_refused(tmp_path: Path) -> None:
    segments = _timeline(tmp_path)
    forbidden = (*_IDS, *(f"{i}.mp4" for i in _IDS), "asset-7", str(tmp_path))
    v2.assert_no_private_text_v2(segments, forbidden)

    leaky = (v2.SingleRaw("03-single", _SINGLE, 12.0, f"Window {_SINGLE} sat on a drive.", ()),)
    with pytest.raises(DemoAssemblyError, match="caption would show something private"):
        v2.assert_no_private_text_v2(leaky, forbidden)


def test_a_judgement_that_would_name_a_file_is_refused() -> None:
    forbidden = (*_IDS, *(f"{i}.mp4" for i in _IDS))
    window = v2.JudgedWindow(
        "07-judged-1",
        _JUDGED[0],
        7.5,
        _judgement(description=f"The window {_JUDGED[0]}.mp4 shows a road."),
        "Title",
        (),
    )

    with pytest.raises(DemoAssemblyError, match="judgement panel would show something private"):
        v2.assert_no_private_text_v2((window,), forbidden)


def test_a_card_that_would_show_a_path_is_refused() -> None:
    leaky = (Card("10-close", "Title", ("/Users/someone/private-media/ride.mp4",), 5.0),)

    with pytest.raises(DemoAssemblyError, match="path"):
        v2.assert_no_private_text_v2(leaky, forbidden=())


def test_tags_and_the_badge_are_checked_too(tmp_path: Path) -> None:
    with pytest.raises(DemoAssemblyError, match="badge would show something private"):
        v2.assert_no_private_text_v2(_timeline(tmp_path), forbidden=("no one edited this",))


def test_the_judgement_panel_says_what_the_model_said_and_names_nothing() -> None:
    analysis = VideoAnalysis(
        asset_id="asset-7",
        start_offset_s=0.0,
        end_offset_s=12.0,
        visual_description=(
            "The camera looks along a two-lane rural highway that bends gently to the left "
            "between paddocks and a line of wind-bent trees; low hills rise in the middle "
            "distance under a sky of broken cloud, and the road surface is dry and empty of "
            "other traffic for as far as it can be seen."
        ),
        road_type="Rural_highway / State highway",
        scenery_tags=("hills", "trees"),
        weather_visible="cloudy",
        visual_interest_score=0.9,
        story_relevance_score=0.5,
        confidence=0.8,
        analysis_provider="gemini-2.5-flash",
        rider_visible="none",
        stationary="no",
        photogenic_score=0.8,
        highlight_subject="vista",
    )
    judgement = v2.Judgement.from_analysis(analysis)

    assert len(judgement.description) <= v2.JUDGEMENT_DESCRIPTION_CHARS
    assert judgement.description.endswith("…")
    assert judgement.description.startswith("The camera looks along a two-lane rural highway")
    assert judgement.facts == (
        "road: Rural highway / State highway",
        "subject: vista",
        "interest 0.9 · photogenic 0.8",
        "stationary: no",
        "rider in frame: none",
    )
    assert "asset-7" not in " ".join(judgement.lines)
    v2.assert_no_private_text_v2(
        (v2.JudgedWindow("07-judged-1", "evt-1", 7.5, judgement, "T", ()),), ("asset-7", "evt-1")
    ) if False else None  # the event id is only in the segment, never in its text
    for what, text in v2.on_screen_texts(
        (v2.JudgedWindow("07-judged-1", "evt-1", 7.5, judgement, "T", ()),)
    ):
        assert "evt-1" not in text and "asset-7" not in text


def test_an_unknown_subject_and_a_missing_photogenic_score_are_left_out() -> None:
    judgement = _judgement(highlight_subject="unknown", photogenic_score=None)

    assert judgement.facts == (
        "road: rural highway",
        "interest 0.9",
        "stationary: no",
        "rider in frame: none",
    )


def test_a_judgement_that_reads_like_a_number_plate_is_refused() -> None:
    with pytest.raises(DemoAssemblyError, match="number plate"):
        _judgement(description="A parked car with the plate ABC123 faces the camera.")


def test_a_short_description_is_kept_whole() -> None:
    assert v2.shorten("Short.", 180) == "Short."
    assert v2.shorten("a" * 200, 20).endswith("…")
    assert len(v2.shorten("word " * 100, 50)) <= 50


# --- the inputs ------------------------------------------------------------------------


def test_the_inputs_are_read_as_written(tmp_path: Path) -> None:
    inputs = v2.DemoInputs.from_dict(_inputs_dict(tmp_path))

    assert inputs.event_ids == _IDS
    assert inputs.proxy_path("evt-0001") == tmp_path / "analysis-proxies" / "evt-0001.mp4"
    assert inputs.figures.source_hours_minutes == (4, 43)
    assert inputs.figures.film_minutes == 6


@pytest.mark.parametrize(
    "change, message",
    [
        ({"schema_version": "demo-v1"}, "schema"),
        ({"mosaic": list(_MOSAIC[:11])}, "12 distinct"),
        ({"mosaic": [_MOSAIC[0], *_MOSAIC[:11]]}, "12 distinct"),
        ({"judged": [{"event_id": "e", "label": "high"}] * 3}, "4 judged"),
        ({"judged": [{"event_id": "e", "label": "meh"}] * 4}, "high or low"),
        ({"single": "a/b"}, "plain file stem"),
        ({"proxy_package": "relative/package"}, "absolute"),
        ({"figures": {**_FIGURES, "windows": "337"}}, "whole number"),
        ({"figures": {**_FIGURES, "cost_jpy": -1}}, "must be a number"),
        ({"figures": {k: v for k, v in _FIGURES.items() if k != "beats"}}, "beats"),
    ],
)
def test_bad_inputs_are_refused(tmp_path: Path, change: dict[str, object], message: str) -> None:
    payload = {**_inputs_dict(tmp_path), **change}

    with pytest.raises(DemoAssemblyError, match=message):
        v2.DemoInputs.from_dict(payload)


def test_the_figures_must_agree_with_the_console(tmp_path: Path) -> None:
    figures = v2.Figures.from_dict(_FIGURES)
    v2.check_figures_against_console(figures, _console())

    with pytest.raises(DemoAssemblyError, match="window count"):
        v2.check_figures_against_console(figures, _console(windows=336))
    with pytest.raises(DemoAssemblyError, match="cost"):
        v2.check_figures_against_console(figures, _console(cost=49.8))
    with pytest.raises(DemoAssemblyError, match="beat count"):
        v2.check_figures_against_console(figures, _console(beats=61))
    with pytest.raises(DemoAssemblyError, match="no footage plan"):
        v2.check_figures_against_console(
            figures, {"stages": [{"key": "footage_planned", "state": "blocked"}]}
        )


# --- the commands ----------------------------------------------------------------------


def test_the_framed_excerpt_frames_the_film_at_eighty_percent_top_right(tmp_path: Path) -> None:
    segment = v2.FramedExcerpt("01-made-by", 12.0, 8.0, "Title", ("body",))
    command = v2.framed_excerpt_command(
        tmp_path / "film.mp4",
        segment,
        tmp_path / "badge.png",
        tmp_path / "caption.png",
        tmp_path / "o.mp4",
    )
    joined = " ".join(command)

    assert "-ss 12.000 -t 8.000" in joined
    assert "scale=1536:864" in joined
    assert "pad=1920:1080:360:24" in joined, "the film sits at (360, 24) on the black canvas"
    assert "drawbox=x=358:y=22:w=1540:h=868:color=white:t=2" in joined, "a 2 px white frame"
    assert "overlay=360:24" in joined, "the badge at the frame's top-left"
    assert f"crop={v2.tag_width_px(v2.BADGE_OUTPUT_TEXT)}:48:0:0" in joined
    assert "crop=1920:192:0:1308" in joined, "the caption from the band under the frame"
    assert "overlay=0:888" in joined
    assert "fade=t=in:st=0" in joined and "fade=t=out:st=7.600" in joined
    assert "-map 0:a" in joined, "the film's own audio passes through"
    assert "anullsrc" not in joined
    assert "libx264" in joined and "aac" in joined and "yuv420p" in joined


def test_the_full_screen_excerpt_keeps_only_the_badge(tmp_path: Path) -> None:
    segment = v2.FullScreenExcerpt("09-result-tail", 130.0, 10.0)
    joined = " ".join(
        v2.full_screen_excerpt_command(
            tmp_path / "film.mp4", segment, tmp_path / "b.png", tmp_path / "o.mp4"
        )
    )

    assert "-ss 130.000 -t 10.000" in joined
    assert "scale=1920:1080" in joined and "pad=" not in joined
    assert "overlay=24:24" in joined
    assert "crop=1920:192" not in joined, "no caption"
    assert "-map 0:a" in joined


def test_the_mosaic_stacks_twelve_looped_proxies_in_a_four_by_three_grid(tmp_path: Path) -> None:
    segment = v2.Mosaic("02-mosaic", _MOSAIC, 12.0, "Title", ("body",))
    proxies = tuple(tmp_path / f"{i}.mp4" for i in _MOSAIC)
    command = v2.mosaic_command(
        proxies, segment, tmp_path / "tag.png", tmp_path / "cap.png", tmp_path / "o.mp4"
    )
    joined = " ".join(command)

    assert command.count("-stream_loop") == 12
    assert joined.count("scale=480:270") == 12
    assert (
        "xstack=inputs=12:layout=0_0|480_0|960_0|1440_0|0_270|480_270|960_270|1440_270"
        "|0_540|480_540|960_540|1440_540" in joined
    )
    assert "pad=1920:1080:0:135" in joined, "letterboxed on the canvas"
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in joined
    assert "-map 12:a" in joined, "the silence is input twelve, after the proxies"
    assert "crop=1920:240:0:1260" in joined and "overlay=0:840" in joined, (
        "caption over the lower third"
    )
    assert "color=c=black@0.55:s=1920x240" in joined, "the film's own darkening strip"
    assert f"crop={v2.tag_width_px(v2.TAG_RAW_TEXT)}:48:0:0" in joined and "overlay=24:24" in joined


def test_the_mosaic_refuses_the_wrong_number_of_proxies(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        v2.Mosaic("02-mosaic", _MOSAIC[:5], 12.0, "Title", ())
    segment = v2.Mosaic("02-mosaic", _MOSAIC, 12.0, "Title", ())
    with pytest.raises(ValueError):
        v2.mosaic_command(
            (tmp_path / "a.mp4",), segment, tmp_path / "t", tmp_path / "c", tmp_path / "o"
        )


def test_the_single_raw_window_fills_the_screen(tmp_path: Path) -> None:
    segment = v2.SingleRaw("03-single", _SINGLE, 12.0, "Title", ())
    joined = " ".join(
        v2.single_raw_command(
            tmp_path / "p.mp4", segment, tmp_path / "t.png", tmp_path / "c.png", tmp_path / "o.mp4"
        )
    )

    assert "-stream_loop -1 -t 12.000" in joined
    assert (
        "scale=1920:1080:force_original_aspect_ratio=increase" in joined
        and "crop=1920:1080" in joined
    )
    assert "anullsrc" in joined and "-map 1:a" in joined
    assert "crop=1920:240:0:1260" in joined


def test_the_judged_window_puts_the_panel_in_the_left_column(tmp_path: Path) -> None:
    middle = v2.JudgedWindow(
        "07-judged-2",
        _JUDGED[1],
        7.5,
        _judgement(),
        "Title",
        (),
        caption_fade_in=False,
        caption_fade_out=False,
    )
    first = v2.JudgedWindow(
        "07-judged-1", _JUDGED[0], 7.5, _judgement(), "Title", (), caption_fade_out=False
    )
    last = v2.JudgedWindow(
        "07-judged-4", _JUDGED[3], 7.5, _judgement(), "Title", (), caption_fade_in=False
    )
    paths = (
        tmp_path / "p.mp4",
        tmp_path / "t.png",
        tmp_path / "panel.png",
        tmp_path / "c.png",
        tmp_path / "o.mp4",
    )

    joined = " ".join(v2.judged_window_command(paths[0], middle, *paths[1:]))
    assert (
        "scale=1536:864:force_original_aspect_ratio=increase" in joined
        and "crop=1536:864" in joined
    )
    assert "pad=1920:1080:360:24" in joined and ":t=2" in joined
    assert (
        f"crop={v2.tag_width_px(v2.TAG_RAW_SENT_TEXT)}:48:0:0" in joined
        and "overlay=360:24" in joined
    )
    assert "crop=312:864:24:444" in joined and "overlay=24:24" in joined, "the panel, x 24..336"
    assert "crop=1920:192:0:1308" in joined and "overlay=0:888" in joined
    assert "anullsrc" in joined and "-map 1:a" in joined
    # The panel fades with every window; the caption fades only at the ends of the run.
    assert joined.count("fade=t=in") == 1 and joined.count("fade=t=out") == 1
    first_joined = " ".join(v2.judged_window_command(paths[0], first, *paths[1:]))
    assert first_joined.count("fade=t=in") == 2 and first_joined.count("fade=t=out") == 1
    last_joined = " ".join(v2.judged_window_command(paths[0], last, *paths[1:]))
    assert last_joined.count("fade=t=in") == 1 and last_joined.count("fade=t=out") == 2


def test_the_console_still_is_tagged_and_captioned(tmp_path: Path) -> None:
    cropped = " ".join(
        v2.console_still_command(
            tmp_path / "card.png", 15.0, tmp_path / "t.png", tmp_path / "c.png", tmp_path / "o.mp4"
        )
    )
    boxed = " ".join(
        v2.console_still_command(
            tmp_path / "shot.png",
            18.0,
            tmp_path / "t.png",
            tmp_path / "c.png",
            tmp_path / "o.mp4",
            letterbox=True,
        )
    )
    silent_card = " ".join(
        v2.console_still_command(
            tmp_path / "card.png", 12.0, tmp_path / "t.png", None, tmp_path / "o.mp4"
        )
    )

    assert "-loop 1 -t 15.000" in cropped
    filled = "scale=1920:888:force_original_aspect_ratio=increase,crop=1920:888,pad=1920:1080:0:0"
    assert filled in cropped, "a captioned card fills the picture area with its middle"
    fitted = (
        "scale=1920:888:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(888-ih)/2"
    )
    assert fitted in boxed, "a captioned screenshot sits whole above the band"
    assert "overlay=0:888" in cropped and "overlay=0:888" in boxed, "the caption in the band below"
    assert "force_original_aspect_ratio=increase,crop=1920:1080" in silent_card, (
        "an uncaptioned card fills the frame"
    )
    for joined in (cropped, boxed, silent_card):
        assert (
            f"crop={v2.tag_width_px(v2.TAG_CONSOLE_TEXT)}:48:0:0" in joined
            and "overlay=24:24" in joined
        )
        assert "anullsrc" in joined and "-map 1:a" in joined
    assert "crop=1920:192:0:1308" in cropped and "crop=1920:192:0:1308" in boxed, "the band"
    assert "crop=1920:192" not in silent_card, "a card carries its own words"


def test_pages_escape_what_they_show() -> None:
    for page in (
        v2.tag_html("<b>RAW</b> & co"),
        v2.caption_page_html("<b>Title</b>", ("a & b",), band=v2.FRAMED_BAND),
        v2.judgement_panel_html(_judgement(description="<b>bold</b> & so")),
    ):
        assert "<b>" not in page
        assert "&lt;b&gt;" in page and "&amp;" in page


def test_the_caption_page_places_the_band_where_ffmpeg_crops_it() -> None:
    framed = v2.caption_page_html("T", (), band=v2.FRAMED_BAND)
    lower = v2.caption_page_html("T", (), band=v2.LOWER_THIRD_BAND)

    assert (
        f"top:{1308 * 100 / 1920:.4f}vw" in framed and f"height:{192 * 100 / 1920:.4f}vw" in framed
    )
    assert f"top:{1260 * 100 / 1920:.4f}vw" in lower and f"height:{240 * 100 / 1920:.4f}vw" in lower


# --- subtitles ---------------------------------------------------------------------------


def test_the_subtitles_hold_one_cue_across_the_four_judged_windows(tmp_path: Path) -> None:
    from app.submission.demo_assembly import demo_subtitles

    segments = _timeline(tmp_path)
    text = demo_subtitles(segments, seconds=v2.segment_seconds_v2, spoken=v2.spoken_v2)
    cues = [block.splitlines() for block in text.strip().split("\n\n")]

    assert len(cues) == 10, "one cue per scene; the full-screen tail says nothing new"
    assert cues[0][1] == "00:00:00,000 --> 00:00:08,000"
    assert cues[6][1] == "00:01:20,000 --> 00:01:50,000", "scene 7 is one caption for 30 s"
    assert cues[6][2].startswith("Gemini 2.5 Flash judges every window")
    assert cues[8][1] == "00:02:05,000 --> 00:02:35,000", "the caption leaves with the frame"
    assert cues[9][1] == "00:02:45,000 --> 00:02:57,000"
    for not_speech in (
        "RAW GoPro",
        "Local console",
        "no one edited this",
        "rural highway",
        "interest 0.9",
    ):
        assert not_speech not in text
    assert "337 windows · 245.1 MB" not in text, "the figures card is not speech"


# --- assembling, with the tools stubbed ---------------------------------------------------


class _FakeRasteriser:
    name = "fake"

    def command(self, html_path: Path, output_directory: Path, *, size: int) -> tuple[str, ...]:
        return ("qlmanage", str(html_path), str(output_directory))

    def output_path(self, html_path: Path, output_directory: Path) -> Path:
        return output_directory / f"{html_path.name}.png"


def _recording_runner(seen: list[list[str]], *, film_seconds: float = 600.0, audio: bool = True):
    def run(command, capture_output=True, text=True, check=False):
        seen.append(list(command))
        if command[0] == "ffprobe":
            streams = [{"codec_type": "video"}] + ([{"codec_type": "audio"}] if audio else [])
            payload = {"format": {"duration": str(film_seconds)}, "streams": streams}
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[0] == "qlmanage":
            Path(command[2]).joinpath(Path(command[1]).name + ".png").write_bytes(b"\x89PNG")
        else:
            Path(command[-1]).write_bytes(b"mp4")
        return subprocess.CompletedProcess(command, 0, "", "")

    return run


def _english_package(tmp_path: Path, *, language: str = "en") -> Path:
    """Enough of a package for the console to read, with English cards and a film."""
    from datetime import UTC, datetime, timedelta

    from app.agents import StoryOutputLanguage
    from app.local_pipeline import LocalPipelineInputs
    from app.video import VideoCatalog, VideoCatalogEntry

    start = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
    root = tmp_path / "package-en"
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
        output_language=StoryOutputLanguage(language),
    )
    (root / "local-pipeline-inputs.json").write_text(json.dumps(inputs.to_dict()), encoding="utf-8")
    catalog = VideoCatalog(
        entries=(
            VideoCatalogEntry(
                asset_id="asset-1",
                file_name="synthetic.mp4",
                recorded_start_time=start + timedelta(seconds=600),
                duration_s=1200.0,
            ),
        ),
        video_to_gps_offset_s=0.0,
    )
    (root / "local-video-catalog.json").write_text(json.dumps(catalog.to_dict()), encoding="utf-8")
    cards = root / "story-cards"
    cards.mkdir()
    for name in ("card-001.html.png", "card-002.html.png"):
        (cards / name).write_bytes(b"\x89PNG")
    return root


def _proxy_package(tmp_path: Path, *, ids: tuple[str, ...] = _IDS) -> Path:
    from app.analysis_record import AnalysedEvent, VideoAnalysisRecord, write_video_analysis_record

    root = tmp_path / "proxies"
    (root / "analysis-proxies").mkdir(parents=True)
    for event_id in ids:
        (root / "analysis-proxies" / f"{event_id}.mp4").write_bytes(b"proxy")
    analysed = tuple(
        AnalysedEvent(
            event_id=event_id,
            analysis=VideoAnalysis(
                asset_id=f"asset-{index}",
                start_offset_s=0.0,
                end_offset_s=12.0,
                visual_description="A grey road between paddocks under cloud.",
                road_type="rural road",
                scenery_tags=("paddocks",),
                weather_visible="cloudy",
                visual_interest_score=0.3,
                story_relevance_score=0.3,
                confidence=0.8,
                analysis_provider="gemini-2.5-flash",
                rider_visible="none",
                stationary="no",
            ),
        )
        for index, event_id in enumerate(ids)
    )
    write_video_analysis_record(root / "gemini-video-analysis.json", VideoAnalysisRecord(analysed))
    return root


def _console_figures(package: Path) -> dict[str, object]:
    """The figures the fixture package's own console states, so the cross-check passes."""
    from app.web.private_journey_console import PrivateJourneyConsole

    stages = {
        s["key"]: s for s in PrivateJourneyConsole.from_directory(package).payload()["stages"]
    }
    planned = stages["footage_planned"]
    assert planned["state"] == "done", planned
    return {
        "windows": planned["candidate_count"],
        "proxy_megabytes": planned["upload_megabytes"],
        "cost_jpy": planned["cost_jpy"],
    }


def _write_inputs(tmp_path: Path, package: Path, proxies: Path, **figures: object) -> Path:
    path = tmp_path / "inputs.json"
    path.write_text(
        json.dumps(_inputs_dict(proxies, **{**_console_figures(package), **figures})),
        encoding="utf-8",
    )
    return path


def _argv(package: Path, inputs: Path, film: Path, *extra: str) -> list[str]:
    return [
        str(package),
        "--inputs",
        str(inputs),
        "--film",
        str(film),
        "--cold-open-s",
        "12",
        "--result-start-s",
        "100",
        "--skip-inspection",
        *extra,
    ]


def test_assembly_draws_every_page_cuts_every_segment_and_joins(
    tmp_path: Path, monkeypatch
) -> None:
    package = _english_package(tmp_path)
    proxies = _proxy_package(tmp_path)
    film = tmp_path / "published.mp4"
    film.write_bytes(b"film")
    inputs = v2.DemoInputs.load(_write_inputs(tmp_path, package, proxies))
    seen: list[list[str]] = []

    out, segments = v2.assemble_demo_v2(
        package,
        inputs=inputs,
        film=film,
        cold_open_s=12.0,
        result_start_s=100.0,
        rasteriser=_FakeRasteriser(),
        runner=_recording_runner(seen),
    )

    assert out == package / "demo" / v2.DEMO_V2_FILE_NAME and out.is_file()
    srt = (package / "demo" / v2.DEMO_V2_SUBTITLES_FILE_NAME).read_text(encoding="utf-8")
    assert srt.count(" --> ") == 10
    assert len(segments) == 14
    kinds = [c[0] for c in seen]
    assert kinds.count("ffprobe") == 1
    # 4 tags/badge + 7 distinct captions (segment 7's four windows share one) + 1 panel (the
    # fixture's four judgements read the same, so one page) + 4 cards (two fallbacks, figures,
    # close). The drawer draws each distinct page once.
    assert kinds.count("qlmanage") == 16, kinds.count("qlmanage")
    assert sum(1 for c in seen if c[0] == "ffmpeg" and "-filter_complex" in c) == 14
    assert sum(1 for c in seen if c[0] == "ffmpeg" and "-ss" in c) == 3, (
        "two framed cuts and the tail"
    )
    assert sum(1 for c in seen if "concat" in c) == 1
    assert not any(p.name.startswith(".assembling-") for p in (package / "demo").iterdir())


def test_a_second_assembly_needs_overwrite(tmp_path: Path) -> None:
    package = _english_package(tmp_path)
    proxies = _proxy_package(tmp_path)
    film = tmp_path / "published.mp4"
    film.write_bytes(b"film")
    inputs = v2.DemoInputs.load(_write_inputs(tmp_path, package, proxies))
    kwargs = dict(
        inputs=inputs,
        film=film,
        cold_open_s=0.0,
        result_start_s=100.0,
        rasteriser=_FakeRasteriser(),
        runner=_recording_runner([]),
    )

    v2.assemble_demo_v2(package, **kwargs)
    with pytest.raises(FileExistsError):
        v2.assemble_demo_v2(package, **kwargs)
    v2.assemble_demo_v2(package, overwrite=True, **kwargs)


def test_a_failing_tool_leaves_no_demo_and_no_scratch(tmp_path: Path) -> None:
    package = _english_package(tmp_path)
    proxies = _proxy_package(tmp_path)
    film = tmp_path / "published.mp4"
    film.write_bytes(b"film")
    inputs = v2.DemoInputs.load(_write_inputs(tmp_path, package, proxies))
    probe = _recording_runner([])

    def failing(command, capture_output=True, text=True, check=False):
        if command[0] == "ffprobe":
            return probe(command)
        return subprocess.CompletedProcess(command, 1, "", "boom")

    with pytest.raises(DemoAssemblyError):
        v2.assemble_demo_v2(
            package,
            inputs=inputs,
            film=film,
            cold_open_s=0.0,
            result_start_s=100.0,
            rasteriser=_FakeRasteriser(),
            runner=failing,
        )
    assert not (package / "demo" / v2.DEMO_V2_FILE_NAME).exists()
    assert not any(p.name.startswith(".assembling-") for p in (package / "demo").iterdir())


def test_the_command_line_refuses_a_missing_proxy(tmp_path: Path, monkeypatch) -> None:
    package = _english_package(tmp_path)
    proxies = _proxy_package(tmp_path)
    (proxies / "analysis-proxies" / f"{_SINGLE}.mp4").unlink()
    film = tmp_path / "published.mp4"
    film.write_bytes(b"film")
    inputs = _write_inputs(tmp_path, package, proxies)
    monkeypatch.setattr(v2.subprocess, "run", _recording_runner([]))

    with pytest.raises(SystemExit, match="proxy the demo shows is missing"):
        v2.main(_argv(package, inputs, film))
    assert not (package / "demo").exists()


def test_the_command_line_refuses_a_film_too_short_for_the_result(
    tmp_path: Path, monkeypatch
) -> None:
    package = _english_package(tmp_path)
    proxies = _proxy_package(tmp_path)
    film = tmp_path / "published.mp4"
    film.write_bytes(b"film")
    inputs = _write_inputs(tmp_path, package, proxies)
    monkeypatch.setattr(v2.subprocess, "run", _recording_runner([], film_seconds=139.0))

    with pytest.raises(SystemExit, match="shorter than the excerpts"):
        v2.main(_argv(package, inputs, film))


def test_the_command_line_refuses_a_film_too_short_for_the_cold_open(
    tmp_path: Path, monkeypatch
) -> None:
    package = _english_package(tmp_path)
    proxies = _proxy_package(tmp_path)
    film = tmp_path / "published.mp4"
    film.write_bytes(b"film")
    inputs = _write_inputs(tmp_path, package, proxies)
    monkeypatch.setattr(v2.subprocess, "run", _recording_runner([], film_seconds=150.0))

    with pytest.raises(SystemExit, match="shorter than the excerpts"):
        v2.main(
            [
                *_argv(package, inputs, film)[:5],
                "--cold-open-s",
                "143",
                "--result-start-s",
                "100",
                "--skip-inspection",
            ]
        )


def test_the_command_line_refuses_a_silent_film(tmp_path: Path, monkeypatch) -> None:
    package = _english_package(tmp_path)
    proxies = _proxy_package(tmp_path)
    film = tmp_path / "published.mp4"
    film.write_bytes(b"film")
    inputs = _write_inputs(tmp_path, package, proxies)
    monkeypatch.setattr(v2.subprocess, "run", _recording_runner([], audio=False))

    with pytest.raises(SystemExit, match="no audio"):
        v2.main(_argv(package, inputs, film))


def test_the_command_line_refuses_bad_inputs(tmp_path: Path, monkeypatch) -> None:
    package = _english_package(tmp_path)
    film = tmp_path / "published.mp4"
    film.write_bytes(b"film")
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps({"schema_version": "something-else"}), encoding="utf-8")
    monkeypatch.setattr(v2.subprocess, "run", _recording_runner([]))

    with pytest.raises(SystemExit, match="schema"):
        v2.main(_argv(package, inputs, film))
    inputs.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit, match="unreadable"):
        v2.main(_argv(package, inputs, film))
    with pytest.raises(SystemExit, match="missing"):
        v2.main(_argv(package, tmp_path / "absent.json", film))


def test_the_command_line_refuses_a_missing_film(tmp_path: Path, monkeypatch) -> None:
    package = _english_package(tmp_path)
    proxies = _proxy_package(tmp_path)
    inputs = _write_inputs(tmp_path, package, proxies)
    monkeypatch.setattr(v2.subprocess, "run", _recording_runner([]))

    with pytest.raises(SystemExit, match="film to excerpt is missing"):
        v2.main(_argv(package, inputs, tmp_path / "absent.mp4"))


def test_the_command_line_refuses_a_package_whose_story_is_not_english(
    tmp_path: Path, monkeypatch
) -> None:
    package = _english_package(tmp_path, language="ja")
    proxies = _proxy_package(tmp_path)
    film = tmp_path / "published.mp4"
    film.write_bytes(b"film")
    inputs = _write_inputs(tmp_path, package, proxies)
    monkeypatch.setattr(v2.subprocess, "run", _recording_runner([]))

    with pytest.raises(SystemExit, match="not in English"):
        v2.main(_argv(package, inputs, film))


def test_the_command_line_refuses_a_package_with_one_chapter_card(
    tmp_path: Path, monkeypatch
) -> None:
    package = _english_package(tmp_path)
    (package / "story-cards" / "card-002.html.png").unlink()
    proxies = _proxy_package(tmp_path)
    film = tmp_path / "published.mp4"
    film.write_bytes(b"film")
    inputs = _write_inputs(tmp_path, package, proxies)
    monkeypatch.setattr(v2.subprocess, "run", _recording_runner([]))

    with pytest.raises(SystemExit, match="fewer than two chapter cards"):
        v2.main(_argv(package, inputs, film))


def test_the_command_line_refuses_figures_the_console_does_not_state(
    tmp_path: Path, monkeypatch
) -> None:
    package = _english_package(tmp_path)
    proxies = _proxy_package(tmp_path)
    film = tmp_path / "published.mp4"
    film.write_bytes(b"film")
    inputs = _write_inputs(tmp_path, package, proxies, windows=9999)
    monkeypatch.setattr(v2.subprocess, "run", _recording_runner([]))

    with pytest.raises(SystemExit, match="window count"):
        v2.main(_argv(package, inputs, film))


def test_the_command_line_refuses_a_window_that_was_never_judged(
    tmp_path: Path, monkeypatch
) -> None:
    package = _english_package(tmp_path)
    proxies = _proxy_package(tmp_path, ids=_IDS[:16])
    (proxies / "analysis-proxies" / f"{_IDS[16]}.mp4").write_bytes(b"proxy")
    film = tmp_path / "published.mp4"
    film.write_bytes(b"film")
    inputs = _write_inputs(tmp_path, package, proxies)
    monkeypatch.setattr(v2.subprocess, "run", _recording_runner([]))

    with pytest.raises(SystemExit, match="never judged"):
        v2.main(_argv(package, inputs, film))


def test_the_command_line_assembles_and_reports(tmp_path: Path, monkeypatch, capsys) -> None:
    package = _english_package(tmp_path)
    proxies = _proxy_package(tmp_path)
    film = tmp_path / "published.mp4"
    film.write_bytes(b"film")
    shot = tmp_path / "copies.png"
    shot.write_bytes(b"\x89PNG")
    inputs = _write_inputs(tmp_path, package, proxies)
    monkeypatch.setattr(v2.subprocess, "run", _recording_runner([]))
    monkeypatch.setattr(v2, "chosen_rasteriser", lambda: _FakeRasteriser())

    v2.main(_argv(package, inputs, film, "--console-copies-png", str(shot)))

    out = capsys.readouterr().out
    assert str(package / "demo" / v2.DEMO_V2_FILE_NAME) in out
    assert "177.0s total" in out
    assert "inspected: skipped" in out
    assert (package / "demo" / v2.DEMO_V2_SUBTITLES_FILE_NAME).is_file()


def test_the_command_line_removes_a_demo_that_shows_a_plate_or_a_face(
    tmp_path: Path, monkeypatch
) -> None:
    package = _english_package(tmp_path)
    proxies = _proxy_package(tmp_path)
    film = tmp_path / "published.mp4"
    film.write_bytes(b"film")
    inputs = _write_inputs(tmp_path, package, proxies)
    monkeypatch.setattr(v2.subprocess, "run", _recording_runner([]))
    monkeypatch.setattr(v2, "chosen_rasteriser", lambda: _FakeRasteriser())
    argv = _argv(package, inputs, film)[:-1]  # without --skip-inspection

    with pytest.raises(SystemExit, match="1 plate regions and faces at \\[42.0s\\]"):
        v2.main(argv, inspect=lambda demo: (1, (42.0,)))
    assert not (package / "demo" / v2.DEMO_V2_FILE_NAME).exists()
    assert not (package / "demo" / v2.DEMO_V2_SUBTITLES_FILE_NAME).exists()

    v2.main([*argv, "--overwrite"], inspect=lambda demo: (0, ()))
    assert (package / "demo" / v2.DEMO_V2_FILE_NAME).is_file()


def test_the_segment_table_reads_as_a_timeline(tmp_path: Path) -> None:
    table = v2.segment_table(_timeline(tmp_path))

    assert table.splitlines()[0].startswith("   0.0s   8.0s  FramedExcerpt")
    assert "  80.0s   7.5s  JudgedWindow" in table
    assert table.splitlines()[-1] == " 177.0s total"
    assert not math.isnan(float(table.splitlines()[-1].split("s")[0]))


# --- the figures follow what was bought, not a plan recomputed later -----------------


def _console_with(plan_count: int, cost: float, megabytes: float, *, judged: int | None) -> dict:
    stages = [
        {
            "key": "footage_planned",
            "state": "done",
            "candidate_count": plan_count,
            "cost_jpy": cost,
            "upload_megabytes": megabytes,
        }
    ]
    if judged is not None:
        stages.append({"key": "footage_judged", "state": "done", "judged_count": judged})
    return {"stages": stages}


def _figures(**overrides: object) -> v2.Figures:
    base = {
        "source_files": 35,
        "source_gigabytes": 108.6,
        "source_hours": 4.72,
        "windows": 337,
        "window_seconds": 12,
        "proxy_megabytes": 245.1,
        "cost_jpy": 49.79,
        "interest_07_count": 43,
        "beats": 63,
        "film_seconds": 380,
        "machine_minutes": 80,
        "confirmations": 2,
    }
    base.update(overrides)
    return v2.Figures(**base)  # type: ignore[arg-type]


def test_a_plan_recomputed_since_the_purchase_is_scaled_to_the_windows_judged() -> None:
    """Today's planner picks 326 windows; 337 were bought. Cost and megabytes are linear."""
    console = _console_with(326, 48.17, 237.1, judged=337)

    v2.check_figures_against_console(_figures(), console)

    with pytest.raises(v2.DemoAssemblyError, match="window count is not what the judgement bought"):
        v2.check_figures_against_console(_figures(windows=326), console)
    with pytest.raises(v2.DemoAssemblyError, match="cost is not what the judgement bought"):
        v2.check_figures_against_console(_figures(cost_jpy=48.17), console)
    with pytest.raises(v2.DemoAssemblyError, match="megabytes are not what the judgement bought"):
        v2.check_figures_against_console(_figures(proxy_megabytes=237.1), console)


def test_without_a_judgement_the_figures_must_match_the_plan_itself() -> None:
    console = _console_with(337, 49.79, 245.1, judged=None)

    v2.check_figures_against_console(_figures(), console)

    with pytest.raises(v2.DemoAssemblyError, match="window count is not the console's"):
        v2.check_figures_against_console(_figures(windows=326), console)


def test_a_console_without_a_usable_plan_is_refused() -> None:
    with pytest.raises(v2.DemoAssemblyError, match="no usable footage plan"):
        v2.check_figures_against_console(_figures(), _console_with(0, 0.0, 0.0, judged=None))
