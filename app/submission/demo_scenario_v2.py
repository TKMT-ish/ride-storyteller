"""Assemble the second demo scenario: the problem, the mechanism, the result.

The first demo (app.submission.demo_assembly) laid narration over the
finished film and never showed what the problem had been. This scenario
(docs/submission/demo-scenario-v2-ja.md) spends its first half on the
problem and the mechanism -- a day of raw footage that is nearly all grey
road, the small copies made of it on this machine, the price a person has
to type back, the model's own words about four windows -- and its second
half on the result. Three kinds of screen keep the viewer oriented about
what they are looking at, because a judge who cannot tell the product's
output from its input has been shown nothing:

* **RAW**: a proxy copy of the GoPro footage, full screen, tagged
  `RAW GoPro · unedited` (or, when it is the copy the model was sent,
  `RAW GoPro · 480p copy sent to Gemini`).
* **Console**: a card or a still of the local console, tagged `Local console`.
* **Output**: the finished film scaled to 80 % and framed top-right on
  black, with a badge saying that Ride Storyteller made it and no one edited
  it. The demo's own caption sits in the free band under the frame, so it
  never fights the film's own lower thirds -- those stay visible inside
  the frame. The last ten seconds of the result go full screen, badge kept.

Everything is built from v1's parts: the same HTML-to-PNG rasteriser draws
every card, caption, tag and panel; ffmpeg cuts each segment to one frame
size and rate and the concat demuxer joins them; the subtitle file is
written from the same timeline the segments are cut to. The figures a
caption may state come from one inputs file the owner wrote from the day's
records, and the package's own console payload, and nothing else -- held by
test. No file name, event id, asset id, path, coordinate or capture time
appears on any screen, held by test over every caption, card, tag, badge and
judgement panel, with the inputs' own identifiers on the forbidden list.

Nothing is published. The result is a file under the package's private
`demo/` directory; putting it anywhere is a separate act by the owner after
they have looked at it. No network call is made by anything here.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

from app.agents import StoryOutputLanguage
from app.analysis_record import (
    VIDEO_ANALYSIS_RECORD_FILE_NAME,
    VideoAnalysisRecordError,
    load_video_analysis_record,
)
from app.analysis_run import PROXY_DIRECTORY_NAME
from app.chapter_card import LOWER_THIRD_HEIGHT_SHARE
from app.contracts.models import VideoAnalysis
from app.plate_blur import looks_like_a_plate
from app.story_film import (
    CARD_RASTER_SIZE,
    LOWER_THIRD_FADE_S,
    LOWER_THIRD_STRIP_OPACITY,
    CardRasteriser,
    chosen_rasteriser,
)
from app.submission.demo_assembly import (
    DEMO_DIRECTORY_NAME,
    DEMO_FPS,
    DEMO_HEIGHT,
    DEMO_TOTAL_S,
    DEMO_WIDTH,
    Card,
    DemoAssemblyError,
    Runner,
    _run,
    chapter_cards_in,
    concat_command,
    demo_subtitles,
    rasterise_card,
    refuse_private_text,
    segment_seconds,
    spoken_lines,
    timeline_duration_s,
)
from app.web.private_journey_console import PrivateJourneyConsole, PrivateJourneyConsoleError

DEMO_V2_INPUTS_SCHEMA_VERSION = "demo-v2-inputs-v1"
DEMO_V2_FILE_NAME = "demo-v2-en.mp4"
DEMO_V2_SUBTITLES_FILE_NAME = "demo-v2-en.srt"
PIPELINE_INPUTS_FILE_NAME = "local-pipeline-inputs.json"

# The output screen: the film at 80 %, framed top-right on a black canvas
# with this margin, inside a thin white line. The free band under the frame
# carries the demo's caption, left-aligned with its own margin.
FRAMED_WIDTH = 1536
FRAMED_HEIGHT = 864
FRAME_MARGIN = 24
FRAMED_X = DEMO_WIDTH - FRAME_MARGIN - FRAMED_WIDTH
FRAMED_Y = FRAME_MARGIN
FRAME_LINE = 2
BAND_TOP = FRAMED_Y + FRAMED_HEIGHT
BAND_HEIGHT = DEMO_HEIGHT - BAND_TOP
BAND_MARGIN = 48
# The judgement panel lives in the column left of the frame.
PANEL_X = FRAME_MARGIN
PANEL_Y = FRAMED_Y
PANEL_WIDTH = FRAMED_X - 2 * FRAME_MARGIN
PANEL_HEIGHT = FRAMED_HEIGHT

# The full-screen kinds carry their caption over the film's own lower third.
LOWER_THIRD_HEIGHT = round(DEMO_HEIGHT * LOWER_THIRD_HEIGHT_SHARE)
LOWER_THIRD_TOP = DEMO_HEIGHT - LOWER_THIRD_HEIGHT

# The raw mosaic: twelve proxies in a 4x3 grid, letterboxed on the canvas.
MOSAIC_COLUMNS = 4
MOSAIC_ROWS = 3
MOSAIC_COUNT = MOSAIC_COLUMNS * MOSAIC_ROWS
TILE_WIDTH = DEMO_WIDTH // MOSAIC_COLUMNS
TILE_HEIGHT = TILE_WIDTH * 9 // 16
GRID_HEIGHT = TILE_HEIGHT * MOSAIC_ROWS
GRID_TOP = (DEMO_HEIGHT - GRID_HEIGHT) // 2

# Tags and the badge: a small translucent strip with one line of text.
TAG_HEIGHT = 48
TAG_FONT_PX = 22
TAG_PADDING_PX = 16
TAG_BOX_OPACITY = 0.6
BADGE_OUTPUT_TEXT = "Ride Storyteller output · day 7 · no one edited this"
TAG_RAW_TEXT = "RAW GoPro · unedited"
TAG_RAW_SENT_TEXT = "RAW GoPro · 480p copy sent to Gemini"
TAG_CONSOLE_TEXT = "Local console"
PANEL_LABEL_TEXT = "Gemini 2.5 Flash said"

# The model's description of a window is long; the panel shows this much.
JUDGEMENT_DESCRIPTION_CHARS = 180
JUDGED_WINDOW_COUNT = 4
JUDGED_LABELS = ("high", "low")

# The scenario's ten scenes and their seconds, in order (the doc's table).
SCENE_SECONDS = (8.0, 12.0, 12.0, 15.0, 18.0, 15.0, 30.0, 15.0, 40.0, 12.0)
RESULT_FRAMED_S = 30.0
RESULT_FULL_SCREEN_S = 10.0

SILENCE_INPUT = ("-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000")
_VIDEO_CODEC = ("-c:v", "libx264", "-preset", "medium", "-crf", "20")
_AUDIO_CODEC = ("-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2")
_KEY_BY_BRIGHTNESS = "format=rgba,colorchannelmixer=aa=0:ar=0.299:ag=0.587:ab=0.114"
# The 16:9 frame is the middle of the square page the rasteriser draws.
_PAGE_TOP = (CARD_RASTER_SIZE - DEMO_HEIGHT) // 2


# --- inputs ---------------------------------------------------------------------


@dataclass(frozen=True)
class Figures:
    """The day's numbers, as the owner recorded them from the package's own files."""

    source_files: int
    source_gigabytes: float
    source_hours: float
    windows: int
    window_seconds: int
    proxy_megabytes: float
    cost_jpy: float
    interest_07_count: int
    beats: int
    film_seconds: int
    machine_minutes: int
    confirmations: int

    _INTEGERS = (
        "source_files",
        "windows",
        "window_seconds",
        "interest_07_count",
        "beats",
        "film_seconds",
        "machine_minutes",
        "confirmations",
    )
    _REALS = ("source_gigabytes", "source_hours", "proxy_megabytes", "cost_jpy")

    @classmethod
    def from_dict(cls, payload: object) -> Figures:
        if not isinstance(payload, dict):
            raise DemoAssemblyError("the inputs' figures must be an object")
        values: dict[str, float | int] = {}
        for name in cls._INTEGERS:
            value = payload.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise DemoAssemblyError(f"the figure {name} must be a whole number")
            values[name] = value
        for name in cls._REALS:
            value = payload.get(name)
            if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
                raise DemoAssemblyError(f"the figure {name} must be a number")
            values[name] = float(value)
        return cls(**values)  # type: ignore[arg-type]

    @property
    def source_hours_minutes(self) -> tuple[int, int]:
        hours = int(self.source_hours)
        minutes = int(round((self.source_hours - hours) * 60))
        if minutes == 60:
            hours, minutes = hours + 1, 0
        return hours, minutes

    @property
    def film_minutes(self) -> int:
        return int(round(self.film_seconds / 60))


@dataclass(frozen=True)
class JudgedChoice:
    """One window the demo shows with the model's judgement, and why it was chosen."""

    event_id: str
    label: str

    def __post_init__(self) -> None:
        _check_event_id(self.event_id)
        if self.label not in JUDGED_LABELS:
            raise DemoAssemblyError("a judged window is labelled high or low")


@dataclass(frozen=True)
class DemoInputs:
    """What the owner chose for the demo: which proxies, and the day's figures."""

    proxy_package: Path
    mosaic: tuple[str, ...]
    single: str
    judged: tuple[JudgedChoice, ...]
    figures: Figures

    def __post_init__(self) -> None:
        if not self.proxy_package.is_absolute():
            raise DemoAssemblyError("the proxy package must be an absolute path")
        if len(self.mosaic) != MOSAIC_COUNT or len(set(self.mosaic)) != MOSAIC_COUNT:
            raise DemoAssemblyError(f"the mosaic needs exactly {MOSAIC_COUNT} distinct windows")
        for event_id in self.mosaic:
            _check_event_id(event_id)
        _check_event_id(self.single)
        if len(self.judged) != JUDGED_WINDOW_COUNT:
            raise DemoAssemblyError(f"exactly {JUDGED_WINDOW_COUNT} judged windows are shown")

    @classmethod
    def from_dict(cls, payload: object) -> DemoInputs:
        if not isinstance(payload, dict):
            raise DemoAssemblyError("the inputs file must hold an object")
        if payload.get("schema_version") != DEMO_V2_INPUTS_SCHEMA_VERSION:
            raise DemoAssemblyError("unsupported inputs schema")
        package = payload.get("proxy_package")
        if not isinstance(package, str) or not package:
            raise DemoAssemblyError("the inputs must name the proxy package")
        mosaic = payload.get("mosaic")
        if not isinstance(mosaic, list) or not all(isinstance(i, str) for i in mosaic):
            raise DemoAssemblyError("the mosaic must be a list of window ids")
        single = payload.get("single")
        if not isinstance(single, str):
            raise DemoAssemblyError("the single window must be an id")
        judged = payload.get("judged")
        if not isinstance(judged, list) or not all(isinstance(j, dict) for j in judged):
            raise DemoAssemblyError("the judged windows must be a list of objects")
        return cls(
            proxy_package=Path(package),
            mosaic=tuple(mosaic),
            single=single,
            judged=tuple(
                JudgedChoice(event_id=str(j.get("event_id", "")), label=str(j.get("label", "")))
                for j in judged
            ),
            figures=Figures.from_dict(payload.get("figures")),
        )

    @classmethod
    def load(cls, path: Path) -> DemoInputs:
        if path.is_symlink() or not path.is_file():
            raise DemoAssemblyError("the inputs file is missing")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DemoAssemblyError("the inputs file is unreadable") from error
        return cls.from_dict(payload)

    @property
    def event_ids(self) -> tuple[str, ...]:
        """Every window the demo shows, in the order it shows them."""
        return (*self.mosaic, self.single, *(choice.event_id for choice in self.judged))

    def proxy_path(self, event_id: str) -> Path:
        return self.proxy_package / PROXY_DIRECTORY_NAME / f"{event_id}.mp4"


def _check_event_id(event_id: str) -> None:
    """An id names a proxy file, so it must be one plain path component."""
    if not event_id or "/" in event_id or "\\" in event_id or event_id in (".", ".."):
        raise DemoAssemblyError("a window id must be a plain file stem")


# --- what the model said --------------------------------------------------------


@dataclass(frozen=True)
class Judgement:
    """What the model said about one window, as the panel shows it.

    Built from the record's fields and nothing else: the panel never sees
    an id, a file name, an offset or a coordinate. The description is
    shortened to fit the column, and refused if any word in it is shaped
    like a number plate -- the model reads signs, and once read a plate.
    """

    description: str
    road_type: str
    highlight_subject: str
    visual_interest_score: float
    photogenic_score: float | None
    stationary: str
    rider_visible: str

    def __post_init__(self) -> None:
        if not self.description:
            raise DemoAssemblyError("a judgement needs the model's description")
        for text in (self.description, self.road_type, self.highlight_subject):
            for token in re.findall(r"[A-Za-z0-9-]+", text):
                if looks_like_a_plate(token):
                    raise DemoAssemblyError("a judgement reads like a number plate")

    @classmethod
    def from_analysis(cls, analysis: VideoAnalysis) -> Judgement:
        return cls(
            description=shorten(_plain(analysis.visual_description), JUDGEMENT_DESCRIPTION_CHARS),
            road_type=_plain(analysis.road_type),
            highlight_subject=_plain(analysis.highlight_subject),
            visual_interest_score=analysis.visual_interest_score,
            photogenic_score=analysis.photogenic_score,
            stationary=analysis.stationary,
            rider_visible=analysis.rider_visible,
        )

    @property
    def facts(self) -> tuple[str, ...]:
        scores = f"interest {self.visual_interest_score:.1f}"
        if self.photogenic_score is not None:
            scores += f" · photogenic {self.photogenic_score:.1f}"
        lines = [f"road: {self.road_type}"]
        if self.highlight_subject not in ("", "unknown", "none"):
            lines.append(f"subject: {self.highlight_subject}")
        lines.extend(
            (scores, f"stationary: {self.stationary}", f"rider in frame: {self.rider_visible}")
        )
        return tuple(lines)

    @property
    def lines(self) -> tuple[str, ...]:
        """Everything the panel shows, for the private-text check."""
        return (self.description, *self.facts)


def _plain(text: str) -> str:
    """Model text as one line: underscores are spaces, and a slash is not a path."""
    said = " ".join(text.replace("_", " ").split())
    return re.sub(r"\s*/\s*", " / ", said)


def shorten(text: str, limit: int) -> str:
    """Cut at a word boundary and mark the cut."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:.") + "…"


def load_judgements(record_path: Path, event_ids: tuple[str, ...]) -> dict[str, Judgement]:
    """The model's judgement for each window named, from the bought record."""
    try:
        record = load_video_analysis_record(record_path)
    except VideoAnalysisRecordError as error:
        raise DemoAssemblyError("the proxy package's judgement cannot be read") from error
    judgements: dict[str, Judgement] = {}
    for event_id in event_ids:
        analysis = record.analysis_for(event_id)
        if analysis is None:
            raise DemoAssemblyError("a window the demo shows was never judged")
        judgements[event_id] = Judgement.from_analysis(analysis)
    return judgements


def identifiers_in(record_path: Path, event_ids: tuple[str, ...]) -> tuple[str, ...]:
    """The asset ids the shown windows were cut from, for the forbidden list."""
    try:
        record = load_video_analysis_record(record_path)
    except VideoAnalysisRecordError:
        return ()
    found: list[str] = []
    for event_id in event_ids:
        analysis = record.analysis_for(event_id)
        if analysis is not None:
            found.append(analysis.asset_id)
    return tuple(dict.fromkeys(found))


# --- the segments ----------------------------------------------------------------


def _check_caption(title: str) -> None:
    if not title:
        raise ValueError("a caption needs a title")


def _check_footage(start_s: float, duration_s: float) -> None:
    if start_s < 0 or duration_s <= 0:
        raise ValueError("an excerpt needs a non-negative start and a positive length")


@dataclass(frozen=True)
class FramedExcerpt:
    """The film at 80 %, framed top-right, badge on the frame, caption in the band below."""

    key: str
    start_s: float
    duration_s: float
    title: str
    lines: tuple[str, ...]
    caption_hold_s: float | None = None

    def __post_init__(self) -> None:
        _check_footage(self.start_s, self.duration_s)
        _check_caption(self.title)
        if self.hold_s <= 0 or self.hold_s > self.duration_s:
            raise ValueError("a caption cannot outlast the excerpt it is held over")

    @property
    def hold_s(self) -> float:
        return self.caption_hold_s if self.caption_hold_s is not None else self.duration_s


@dataclass(frozen=True)
class FullScreenExcerpt:
    """The film full screen with only the badge: the last seconds of the result."""

    key: str
    start_s: float
    duration_s: float

    def __post_init__(self) -> None:
        _check_footage(self.start_s, self.duration_s)


@dataclass(frozen=True)
class Mosaic:
    """Twelve raw proxies at once in a 4x3 grid, each looped to fill the time."""

    key: str
    event_ids: tuple[str, ...]
    duration_s: float
    title: str
    lines: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.event_ids) != MOSAIC_COUNT:
            raise ValueError(f"a mosaic shows exactly {MOSAIC_COUNT} windows")
        if self.duration_s <= 0:
            raise ValueError("a mosaic needs a positive length")
        _check_caption(self.title)


@dataclass(frozen=True)
class SingleRaw:
    """One raw proxy filling the screen; it is 480p, so it is soft, and that is the point."""

    key: str
    event_id: str
    duration_s: float
    title: str
    lines: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.duration_s <= 0:
            raise ValueError("a raw window needs a positive length")
        _check_caption(self.title)


@dataclass(frozen=True)
class JudgedWindow:
    """One proxy in the frame with the model's judgement beside it.

    Four of these run back to back under one caption. The caption is drawn
    once and laid on each without fades except in at the first and out at
    the last, so across the cuts it simply stays.
    """

    key: str
    event_id: str
    duration_s: float
    judgement: Judgement
    title: str
    lines: tuple[str, ...]
    caption_fade_in: bool = True
    caption_fade_out: bool = True

    def __post_init__(self) -> None:
        if self.duration_s <= 0:
            raise ValueError("a judged window needs a positive length")
        _check_caption(self.title)


@dataclass(frozen=True)
class ConsoleStill:
    """A console image -- a screenshot, a chapter card, or a card drawn here -- with a caption.

    A square page (a chapter card, a drawn card) is cropped to its middle
    16:9 as the film does; a screenshot of any shape is letterboxed whole.
    """

    key: str
    image: Path | Card
    hold_s: float
    title: str
    lines: tuple[str, ...]
    letterbox: bool = False

    def __post_init__(self) -> None:
        if self.hold_s <= 0:
            raise ValueError("a still must be held for a positive time")
        _check_caption(self.title)


SegmentV2 = (
    FramedExcerpt | FullScreenExcerpt | Mosaic | SingleRaw | JudgedWindow | ConsoleStill | Card
)
_CAPTIONED = (FramedExcerpt, Mosaic, SingleRaw, JudgedWindow, ConsoleStill)


def segment_seconds_v2(segment: SegmentV2) -> float:
    if isinstance(segment, FramedExcerpt | FullScreenExcerpt | Mosaic | SingleRaw | JudgedWindow):
        return segment.duration_s
    if isinstance(segment, ConsoleStill):
        return segment.hold_s
    return segment_seconds(segment)


def spoken_v2(segment: SegmentV2) -> tuple[str, ...]:
    """What a segment says on screen. Tags, badges and the judgement panel are not speech."""
    if isinstance(segment, _CAPTIONED):
        return (segment.title, *segment.lines)
    if isinstance(segment, Card):
        return spoken_lines(segment)
    return ()


def scene_number(segment: SegmentV2) -> int:
    """Which of the scenario's ten scenes a segment belongs to, from its key."""
    return int(segment.key[:2])


def on_screen_texts(segments: tuple[SegmentV2, ...]) -> tuple[tuple[str, str], ...]:
    """Every piece of text the demo draws, with what kind of thing it is."""
    texts: list[tuple[str, str]] = [
        ("a badge", BADGE_OUTPUT_TEXT),
        ("a tag", TAG_RAW_TEXT),
        ("a tag", TAG_RAW_SENT_TEXT),
        ("a tag", TAG_CONSOLE_TEXT),
        ("the judgement panel", PANEL_LABEL_TEXT),
    ]
    for segment in segments:
        spoken = spoken_v2(segment)
        if spoken:
            what = "a card" if isinstance(segment, Card) else "a caption"
            texts.append((what, " ".join(spoken)))
        if isinstance(segment, ConsoleStill) and isinstance(segment.image, Card):
            texts.append(("a card", " ".join(spoken_lines(segment.image))))
        if isinstance(segment, JudgedWindow):
            texts.append(("the judgement panel", " ".join(segment.judgement.lines)))
    return tuple(texts)


def assert_no_private_text_v2(segments: tuple[SegmentV2, ...], forbidden: tuple[str, ...]) -> None:
    """Nothing drawn -- caption, card, tag, badge or judgement -- names anything private."""
    for what, text in on_screen_texts(segments):
        refuse_private_text(text, forbidden, what=what)


# --- the timeline -----------------------------------------------------------------


_NUMBER_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
}


def number_word(value: int, *, capital: bool = False) -> str:
    """Small counts are words in running English; larger ones stay digits."""
    word = _NUMBER_WORDS.get(value, str(value))
    return word.capitalize() if capital else word


def scenario_captions(figures: Figures) -> dict[str, tuple[str, tuple[str, ...]]]:
    """The ten scenes' English, verbatim from the scenario, with the day's figures in it.

    The first sentence is the caption's title and the rest its lines; the
    words are the doc's, and every number in them is one of the figures.
    """
    hours, minutes = figures.source_hours_minutes
    length = f"{hours} hours {minutes} minutes"
    return {
        "made-by": (
            f"Made by Ride Storyteller from {length} of GoPro footage.",
            ("No one edited this.",),
        ),
        "mosaic": (
            f"One day of riding: {math.floor(figures.source_gigabytes)} GB of video, {length}.",
            ("Nearly all of it looks like this.",),
        ),
        "single": (
            "Finding the good minutes means watching all of it.",
            ("So the footage sat on a hard drive.",),
        ),
        "chapters": (
            "The GPS track already knows where the day happened: "
            "setting off, each stop, each named road.",
            ("Every leg becomes a chapter.",),
        ),
        "copies": (
            f"Locally, ffmpeg cuts {figures.windows} "
            f"{number_word(figures.window_seconds)}-second windows and shrinks each to "
            f"480p at one frame a second: {figures.proxy_megabytes:.0f} MB in all.",
            ("The 4K never leaves the machine.",),
        ),
        "cost": (
            f"One page shows the price — ¥{figures.cost_jpy:.2f} — "
            "and waits for a person to type that figure back.",
            ("Nothing is bought until then.",),
        ),
        "judged": (
            "Gemini 2.5 Flash judges every window: is the rider in frame, "
            "is the bike stopped, what is worth looking at.",
            (
                f"{figures.windows} structured judgements. "
                f"Only {figures.interest_07_count} scored 0.7 or more.",
            ),
        ),
        "planner": (
            f"The story planner keeps {figures.beats} beats in the order the day happened; "
            "ffmpeg cuts the film and adds the music.",
            (
                f"About {figures.machine_minutes} minutes of machine time. "
                f"{number_word(figures.confirmations, capital=True)} confirmations from a person.",
            ),
        ),
        "result": (
            f"The result: {number_word(figures.film_minutes)} minutes, chapters named by place, "
            "a map in the corner, sections for scenic roads and stops.",
            (),
        ),
        "close": (
            "Open source (AGPL-3.0).",
            (
                "Runs on your machine.",
                f"About ¥{round(figures.cost_jpy):.0f} of Gemini per riding day.",
                "Judges: the day-7 package cuts this film on your own computer.",
                # CC BY asks for the credit in the work itself; the description
                # of the published video repeats it.
                "Music: Wandering by Numall Fix · CC BY 3.0 · "
                "royalty free music by www.free-stock-music.com",
            ),
        ),
    }


def figures_card(figures: Figures, console: Mapping[str, object]) -> Card:
    """The console's figures as a card, the way the local page states them."""
    stages = {str(s["key"]): s for s in console["stages"]}  # type: ignore[index, union-attr]
    copies = stages.get("copies_prepared", {})
    judged = stages.get("footage_judged", {})
    lines: list[str] = []
    bought = int(judged.get("judged_count", 0)) if judged.get("state") == "done" else 0
    if bought:
        # Once the judgement is bought, the counts of record are the judged ones; the
        # console's "wanted" counts come from a plan recomputed by today's code and
        # can drift from what was actually bought (326 against 337 on the real day).
        lines.append(f"Copies made {bought} · Judged {bought} / {bought}")
    elif copies and judged:
        lines.append(
            f"Copies made {copies.get('prepared_count', 0)} / "
            f"{copies.get('wanted_count', copies.get('prepared_count', 0))} · "
            f"Judged {judged.get('judged_count', 0)} / "
            f"{judged.get('wanted_count', judged.get('judged_count', 0))}"
        )
    return Card(
        "08-figures",
        f"{figures.windows} windows · {figures.proxy_megabytes:.1f} MB · ¥{figures.cost_jpy:.2f}",
        (*lines, f"{figures.beats} beats · {figures.film_seconds} s"),
        SCENE_SECONDS[7],
    )


def demo_timeline_v2(
    console: Mapping[str, object],
    inputs: DemoInputs | Mapping[str, object],
    judgements: Mapping[str, Judgement],
    *,
    cold_open_s: float,
    result_start_s: float,
    chapter_card: Path,
    console_copies_png: Path | None = None,
    console_cost_png: Path | None = None,
) -> tuple[SegmentV2, ...]:
    """The scenario's ten scenes as segments, 177 seconds in all.

    Scene 7 is four judged windows of seven and a half seconds under one
    caption; scene 9 is thirty seconds framed then ten full screen, cut
    continuously from the film. A console screenshot that was not supplied
    becomes a card carrying the same words, so the build never fails on a
    missing picture. Every figure comes from `inputs` and `console`.
    """
    chosen = inputs if isinstance(inputs, DemoInputs) else DemoInputs.from_dict(inputs)
    captions = scenario_captions(chosen.figures)
    seconds = SCENE_SECONDS

    def console_scene(key: str, name: str, png: Path | None, hold_s: float) -> SegmentV2:
        title, lines = captions[name]
        if png is None:
            return Card(key, title, lines, hold_s)
        return ConsoleStill(key, png, hold_s, title, lines, letterbox=True)

    judged: list[SegmentV2] = []
    each = seconds[6] / JUDGED_WINDOW_COUNT
    for index, choice in enumerate(chosen.judged):
        if choice.event_id not in judgements:
            raise DemoAssemblyError("a judged window has no judgement to show")
        judged.append(
            JudgedWindow(
                f"07-judged-{index + 1}",
                choice.event_id,
                each,
                judgements[choice.event_id],
                *captions["judged"],
                caption_fade_in=index == 0,
                caption_fade_out=index == JUDGED_WINDOW_COUNT - 1,
            )
        )

    return (
        FramedExcerpt("01-made-by", cold_open_s, seconds[0], *captions["made-by"]),
        Mosaic("02-mosaic", chosen.mosaic, seconds[1], *captions["mosaic"]),
        SingleRaw("03-single", chosen.single, seconds[2], *captions["single"]),
        ConsoleStill("04-chapters", chapter_card, seconds[3], *captions["chapters"]),
        console_scene("05-copies", "copies", console_copies_png, seconds[4]),
        console_scene("06-cost", "cost", console_cost_png, seconds[5]),
        *judged,
        ConsoleStill(
            "08-planner", figures_card(chosen.figures, console), seconds[7], *captions["planner"]
        ),
        FramedExcerpt("09-result", result_start_s, RESULT_FRAMED_S, *captions["result"]),
        FullScreenExcerpt("09-result-tail", result_start_s + RESULT_FRAMED_S, RESULT_FULL_SCREEN_S),
        Card("10-close", *captions["close"], seconds[9]),
    )


def check_figures_against_console(figures: Figures, console: Mapping[str, object]) -> None:
    """The figures the captions state must be the ones the package's console states.

    The owner wrote the figures from the day's records; the console computes
    its own from the package. Where both know a number they must agree, or
    the demo would say one thing and the product another.
    """
    stages = {str(s["key"]): s for s in console["stages"]}  # type: ignore[index, union-attr]
    planned = stages.get("footage_planned", {})
    if planned.get("state") != "done":
        raise DemoAssemblyError("the package's console has no footage plan to compare with")
    plan_count = int(planned.get("candidate_count", -1))
    plan_cost = float(planned.get("cost_jpy", -1.0))
    plan_megabytes = float(planned.get("upload_megabytes", -1.0))
    if plan_count <= 0 or plan_cost < 0 or plan_megabytes < 0:
        raise DemoAssemblyError("the package's console states no usable footage plan")
    # The plan is recomputed from today's code, so it can drift from the windows
    # that were actually bought; the judgement record cannot. Once a judgement is
    # done, the count of record is what was judged, and cost and megabytes follow
    # it at the plan's own per-window rate -- both are linear in the window count.
    judged = stages.get("footage_judged", {})
    bought = int(judged.get("judged_count", 0)) if judged.get("state") == "done" else 0
    if bought > 0 and bought != plan_count:
        scale = bought / plan_count
        count, cost, megabytes = bought, plan_cost * scale, plan_megabytes * scale
        # The plan's totals are shown to the yen cent and the tenth of a megabyte,
        # so scaling them carries that rounding along; nothing tighter is honest.
        cost_tolerance, megabyte_tolerance = 0.005 + 0.005 * scale, 1.0 + 0.05 * scale
        what = "what the judgement bought"
    else:
        count, cost, megabytes = plan_count, plan_cost, plan_megabytes
        cost_tolerance, megabyte_tolerance = 0.005, 1.0
        what = "the console's"
    if count != figures.windows:
        raise DemoAssemblyError(f"the figures' window count is not {what}")
    if abs(cost - figures.cost_jpy) > cost_tolerance:
        raise DemoAssemblyError(f"the figures' cost is not {what}")
    if abs(megabytes - figures.proxy_megabytes) > megabyte_tolerance:
        raise DemoAssemblyError(f"the figures' megabytes are not {what}")
    story = stages.get("story_planned")
    if story and story.get("state") == "done":
        if int(story.get("beat_count", -1)) != figures.beats:
            raise DemoAssemblyError("the figures' beat count is not the story plan's")
        if abs(float(story.get("total_screen_duration_s", -1.0)) - figures.film_seconds) > 1.0:
            raise DemoAssemblyError("the figures' film length is not the story plan's")


# --- drawing -----------------------------------------------------------------------


def _vw(pixels: float) -> str:
    """A length in pixels of the 1920-wide frame, as a share of the square page."""
    return f"{pixels * 100 / CARD_RASTER_SIZE:.4f}vw"


_FONT = '"Helvetica Neue",Helvetica,Arial,sans-serif'


def tag_width_px(text: str) -> int:
    """Wide enough for the text at its font, and even, so the crop stays aligned."""
    width = math.ceil(len(text) * TAG_FONT_PX * 0.6 + 2 * TAG_PADDING_PX)
    return width + width % 2


def tag_html(text: str) -> str:
    """One line of white text at the page's top-left, on black, boxed later by ffmpeg."""
    width = tag_width_px(text)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
html,body{{margin:0;padding:0}}
body{{width:100vw;height:100vh;background:#000;color:#fff;position:relative;
font-family:{_FONT};overflow:hidden}}
.tag{{position:absolute;left:0;top:0;width:{_vw(width)};height:{_vw(TAG_HEIGHT)};
box-sizing:border-box;padding:0 {_vw(TAG_PADDING_PX)};display:flex;align-items:center;
font-size:{_vw(TAG_FONT_PX)};font-weight:600;letter-spacing:.03em;white-space:nowrap;
overflow:hidden}}
</style>
</head>
<body>
<div class="tag">{html.escape(text)}</div>
</body>
</html>
"""


@dataclass(frozen=True)
class Band:
    """Where on the 1080-line frame a caption sits: its top and height, in pixels."""

    top: int
    height: int


FRAMED_BAND = Band(BAND_TOP, BAND_HEIGHT)
LOWER_THIRD_BAND = Band(LOWER_THIRD_TOP, LOWER_THIRD_HEIGHT)


def caption_page_html(title: str, lines: tuple[str, ...], *, band: Band) -> str:
    """The caption drawn on black in the band it will occupy, left-aligned.

    Styled as v1's caption (the same face, colours and letter-spacing, title
    bold and body lighter) but set smaller: the scenario's sentences are
    whole lines of English, not a title, and must wrap inside the band.
    """
    body = "".join(f'<div class="body">{html.escape(line)}</div>' for line in lines)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
html,body{{margin:0;padding:0}}
body{{width:100vw;height:100vh;background:#000;color:#fff;position:relative;
font-family:{_FONT};overflow:hidden}}
.strip{{position:absolute;left:0;top:{_vw(_PAGE_TOP + band.top)};width:100vw;
height:{_vw(band.height)};box-sizing:border-box;padding:0 {_vw(BAND_MARGIN)};
display:flex;align-items:center}}
.text{{display:flex;flex-direction:column;gap:{_vw(10)};text-align:left}}
.title{{font-size:{_vw(38)};font-weight:700;letter-spacing:.03em;line-height:1.15;margin:0}}
.body{{font-size:{_vw(29)};color:#d7dde9;letter-spacing:.03em;line-height:1.3;margin:0}}
</style>
</head>
<body>
<div class="strip"><div class="text"><div class="title">{html.escape(title)}</div>
{body}</div></div>
</body>
</html>
"""


def judgement_panel_html(judgement: Judgement) -> str:
    """The model's words in the column left of the frame, on black."""
    facts = "".join(f'<div class="fact">{html.escape(line)}</div>' for line in judgement.facts)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
html,body{{margin:0;padding:0}}
body{{width:100vw;height:100vh;background:#000;color:#fff;position:relative;
font-family:{_FONT};overflow:hidden}}
.panel{{position:absolute;left:{_vw(PANEL_X)};top:{_vw(_PAGE_TOP + PANEL_Y)};
width:{_vw(PANEL_WIDTH)};height:{_vw(PANEL_HEIGHT)};box-sizing:border-box;
padding:{_vw(24)} {_vw(18)};display:flex;flex-direction:column;gap:{_vw(14)};text-align:left}}
.label{{font-size:{_vw(17)};letter-spacing:.16em;color:#9ed0ff;font-weight:600;
text-transform:uppercase}}
.desc{{font-size:{_vw(21)};line-height:1.35;overflow-wrap:anywhere}}
.fact{{font-size:{_vw(19)};line-height:1.3;color:#d7dde9;margin-top:{_vw(4)}}}
</style>
</head>
<body>
<div class="panel"><div class="label">{html.escape(PANEL_LABEL_TEXT)}</div>
<div class="desc">{html.escape(judgement.description)}</div>
{facts}</div>
</body>
</html>
"""


class _Drawer:
    """Draws pages once each and remembers where; the same caption is one PNG."""

    def __init__(self, work: Path, *, rasteriser: CardRasteriser, runner: Runner) -> None:
        self.work = work
        self.rasteriser = rasteriser
        self.runner = runner
        self._drawn: dict[str, Path] = {}

    def draw(self, kind: str, page: str) -> Path:
        digest = hashlib.sha1(page.encode("utf-8")).hexdigest()[:10]
        name = f"{kind}-{digest}"
        if name in self._drawn:
            return self._drawn[name]
        html_path = self.work / f"{name}.html"
        html_path.write_text(page, encoding="utf-8")
        _run(
            self.rasteriser.command(html_path, self.work, size=CARD_RASTER_SIZE),
            runner=self.runner,
            what=f"{kind} raster",
        )
        png = self.rasteriser.output_path(html_path, self.work)
        if not png.is_file():
            raise DemoAssemblyError(f"the {kind} was not drawn")
        self._drawn[name] = png
        return png

    def tag(self, text: str) -> Path:
        return self.draw("tag", tag_html(text))

    def caption(self, title: str, lines: tuple[str, ...], band: Band) -> Path:
        return self.draw("caption", caption_page_html(title, lines, band=band))

    def panel(self, judgement: Judgement) -> Path:
        return self.draw("panel", judgement_panel_html(judgement))


# --- the ffmpeg commands ------------------------------------------------------------


@dataclass(frozen=True)
class Layer:
    """A drawn page laid on the frame: which part of it, where, for how long.

    The page is black with white text; ffmpeg keys it by brightness so only
    the text lands, and optionally darkens a box under it first. Fades are
    the film's own lower-third fades.
    """

    png: Path
    crop: tuple[int, int, int, int]
    at: tuple[int, int]
    hold_s: float
    box_opacity: float | None = None
    fade_in: bool = False
    fade_out: bool = False

    def __post_init__(self) -> None:
        if self.hold_s <= 0:
            raise ValueError("a layer must be held for a positive time")

    @property
    def inputs(self) -> tuple[str, ...]:
        return ("-loop", "1", "-t", f"{self.hold_s:.3f}", "-i", str(self.png))

    @property
    def fades(self) -> str:
        steps = []
        if self.fade_in:
            steps.append(f"fade=t=in:st=0:d={LOWER_THIRD_FADE_S}:alpha=1")
        if self.fade_out:
            out_at = f"{max(0.0, self.hold_s - LOWER_THIRD_FADE_S):.3f}"
            steps.append(f"fade=t=out:st={out_at}:d={LOWER_THIRD_FADE_S}:alpha=1")
        return "".join(f",{step}" for step in steps)


def badge_layer(png: Path, text: str, at: tuple[int, int], hold_s: float) -> Layer:
    return Layer(png, (tag_width_px(text), TAG_HEIGHT, 0, 0), at, hold_s, TAG_BOX_OPACITY)


def caption_layer(
    png: Path,
    band: Band,
    hold_s: float,
    *,
    darken: bool,
    fade_in: bool = True,
    fade_out: bool = True,
) -> Layer:
    return Layer(
        png,
        (DEMO_WIDTH, band.height, 0, _PAGE_TOP + band.top),
        (0, band.top),
        hold_s,
        LOWER_THIRD_STRIP_OPACITY if darken else None,
        fade_in,
        fade_out,
    )


def panel_layer(png: Path, hold_s: float) -> Layer:
    return Layer(
        png,
        (PANEL_WIDTH, PANEL_HEIGHT, PANEL_X, _PAGE_TOP + PANEL_Y),
        (PANEL_X, PANEL_Y),
        hold_s,
        None,
        True,
        True,
    )


def _layer_chains(layers: tuple[Layer, ...], *, first_input: int, base: str) -> list[str]:
    """Lay each layer over the last, ending in [v]."""
    chains: list[str] = []
    current = base
    for index, layer in enumerate(layers):
        width, height, x, y = layer.crop
        at_x, at_y = layer.at
        chains.append(
            f"[{first_input + index}:v]crop={width}:{height}:{x}:{y},fps={DEMO_FPS},"
            f"{_KEY_BY_BRIGHTNESS}{layer.fades}[k{index}]"
        )
        if layer.box_opacity is not None:
            chains.append(
                f"color=c=black@{layer.box_opacity}:s={width}x{height}:r={DEMO_FPS}:"
                f"d={layer.hold_s:.3f},format=rgba{layer.fades}[b{index}]"
            )
            chains.append(
                f"[{current}][b{index}]overlay={at_x}:{at_y}:eof_action=pass:repeatlast=0[m{index}]"
            )
            current = f"m{index}"
        chains.append(
            f"[{current}][k{index}]overlay={at_x}:{at_y}:eof_action=pass:repeatlast=0[o{index}]"
        )
        current = f"o{index}"
    chains.append(f"[{current}]format=yuv420p[v]")
    return chains


def _frame_chain() -> str:
    """Place the 1536x864 picture at (360, 24) on black and line it in white."""
    return (
        f"pad={DEMO_WIDTH}:{DEMO_HEIGHT}:{FRAMED_X}:{FRAMED_Y}:color=black,"
        f"drawbox=x={FRAMED_X - FRAME_LINE}:y={FRAMED_Y - FRAME_LINE}:"
        f"w={FRAMED_WIDTH + 2 * FRAME_LINE}:h={FRAMED_HEIGHT + 2 * FRAME_LINE}:"
        f"color=white:t={FRAME_LINE}"
    )


def _cover(width: int, height: int) -> str:
    """Scale to fill, cropping the excess: a 480p proxy is not quite 16:9."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height},setsar=1"
    )


def _film_inputs(film: Path, start_s: float, duration_s: float) -> tuple[str, ...]:
    return ("-ss", f"{start_s:.3f}", "-t", f"{duration_s:.3f}", "-i", str(film))


def _proxy_inputs(proxy: Path, duration_s: float) -> tuple[str, ...]:
    """A proxy, looped for as long as the segment needs it."""
    return ("-stream_loop", "-1", "-t", f"{duration_s:.3f}", "-i", str(proxy))


def _silence(duration_s: float) -> tuple[str, ...]:
    return (*SILENCE_INPUT[:2], "-t", f"{duration_s:.3f}", *SILENCE_INPUT[2:])


def _command(
    inputs: tuple[str, ...], chains: list[str], audio_map: str, output: Path
) -> tuple[str, ...]:
    return (
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        *inputs,
        "-filter_complex",
        ";".join(chains),
        "-map",
        "[v]",
        "-map",
        audio_map,
        *_VIDEO_CODEC,
        *_AUDIO_CODEC,
        "-shortest",
        str(output),
    )


def framed_excerpt_command(
    film: Path, segment: FramedExcerpt, badge_png: Path, caption_png: Path, output: Path
) -> tuple[str, ...]:
    """The film at 80 % in its frame, the badge on it, the caption in the band under it."""
    layers = (
        badge_layer(badge_png, BADGE_OUTPUT_TEXT, (FRAMED_X, FRAMED_Y), segment.duration_s),
        caption_layer(caption_png, FRAMED_BAND, segment.hold_s, darken=False),
    )
    chains = [
        f"[0:v]scale={FRAMED_WIDTH}:{FRAMED_HEIGHT},fps={DEMO_FPS},format=yuv420p,"
        f"{_frame_chain()}[base]",
        *_layer_chains(layers, first_input=1, base="base"),
    ]
    inputs = (*_film_inputs(film, segment.start_s, segment.duration_s), *_layer_inputs(layers))
    return _command(inputs, chains, "0:a", output)


def full_screen_excerpt_command(
    film: Path, segment: FullScreenExcerpt, badge_png: Path, output: Path
) -> tuple[str, ...]:
    """The film full screen with only the badge on it."""
    layers = (
        badge_layer(badge_png, BADGE_OUTPUT_TEXT, (FRAME_MARGIN, FRAME_MARGIN), segment.duration_s),
    )
    chains = [
        f"[0:v]scale={DEMO_WIDTH}:{DEMO_HEIGHT},fps={DEMO_FPS},format=yuv420p[base]",
        *_layer_chains(layers, first_input=1, base="base"),
    ]
    inputs = (*_film_inputs(film, segment.start_s, segment.duration_s), *_layer_inputs(layers))
    return _command(inputs, chains, "0:a", output)


def mosaic_layout() -> str:
    """xstack's layout string for the 4x3 grid, row by row."""
    return "|".join(
        f"{column * TILE_WIDTH}_{row * TILE_HEIGHT}"
        for row in range(MOSAIC_ROWS)
        for column in range(MOSAIC_COLUMNS)
    )


def mosaic_command(
    proxies: tuple[Path, ...], segment: Mosaic, tag_png: Path, caption_png: Path, output: Path
) -> tuple[str, ...]:
    """Twelve proxies in a grid, letterboxed, tagged RAW, captioned; silent."""
    if len(proxies) != MOSAIC_COUNT:
        raise ValueError(f"a mosaic takes exactly {MOSAIC_COUNT} proxies")
    audio = MOSAIC_COUNT
    layers = (
        badge_layer(tag_png, TAG_RAW_TEXT, (FRAME_MARGIN, FRAME_MARGIN), segment.duration_s),
        caption_layer(caption_png, LOWER_THIRD_BAND, segment.duration_s, darken=True),
    )
    tiles = [
        f"[{index}:v]scale={TILE_WIDTH}:{TILE_HEIGHT},setsar=1,fps={DEMO_FPS}[t{index}]"
        for index in range(MOSAIC_COUNT)
    ]
    chains = [
        *tiles,
        "".join(f"[t{index}]" for index in range(MOSAIC_COUNT))
        + f"xstack=inputs={MOSAIC_COUNT}:layout={mosaic_layout()}[grid]",
        f"[grid]pad={DEMO_WIDTH}:{DEMO_HEIGHT}:0:{GRID_TOP}:color=black,format=yuv420p[base]",
        *_layer_chains(layers, first_input=audio + 1, base="base"),
    ]
    inputs = (
        *(part for proxy in proxies for part in _proxy_inputs(proxy, segment.duration_s)),
        *_silence(segment.duration_s),
        *_layer_inputs(layers),
    )
    return _command(inputs, chains, f"{audio}:a", output)


def single_raw_command(
    proxy: Path, segment: SingleRaw, tag_png: Path, caption_png: Path, output: Path
) -> tuple[str, ...]:
    """One proxy filling the screen, tagged RAW, captioned; silent."""
    layers = (
        badge_layer(tag_png, TAG_RAW_TEXT, (FRAME_MARGIN, FRAME_MARGIN), segment.duration_s),
        caption_layer(caption_png, LOWER_THIRD_BAND, segment.duration_s, darken=True),
    )
    chains = [
        f"[0:v]{_cover(DEMO_WIDTH, DEMO_HEIGHT)},fps={DEMO_FPS},format=yuv420p[base]",
        *_layer_chains(layers, first_input=2, base="base"),
    ]
    inputs = (
        *_proxy_inputs(proxy, segment.duration_s),
        *_silence(segment.duration_s),
        *_layer_inputs(layers),
    )
    return _command(inputs, chains, "1:a", output)


def judged_window_command(
    proxy: Path,
    segment: JudgedWindow,
    tag_png: Path,
    panel_png: Path,
    caption_png: Path,
    output: Path,
) -> tuple[str, ...]:
    """One proxy in the frame, tagged as the copy the model saw, its judgement beside it."""
    layers = (
        badge_layer(tag_png, TAG_RAW_SENT_TEXT, (FRAMED_X, FRAMED_Y), segment.duration_s),
        panel_layer(panel_png, segment.duration_s),
        caption_layer(
            caption_png,
            FRAMED_BAND,
            segment.duration_s,
            darken=False,
            fade_in=segment.caption_fade_in,
            fade_out=segment.caption_fade_out,
        ),
    )
    chains = [
        f"[0:v]{_cover(FRAMED_WIDTH, FRAMED_HEIGHT)},fps={DEMO_FPS},format=yuv420p,"
        f"{_frame_chain()}[base]",
        *_layer_chains(layers, first_input=2, base="base"),
    ]
    inputs = (
        *_proxy_inputs(proxy, segment.duration_s),
        *_silence(segment.duration_s),
        *_layer_inputs(layers),
    )
    return _command(inputs, chains, "1:a", output)


def console_still_command(
    png: Path,
    hold_s: float,
    tag_png: Path,
    caption_png: Path | None,
    output: Path,
    *,
    letterbox: bool = False,
) -> tuple[str, ...]:
    """A console image held, tagged as the local console, captioned if asked; silent.

    A captioned still is fitted whole into the picture area above the band and
    the caption goes in the band below it, as on a framed excerpt: a screenshot
    is text, and a caption laid over its lower third would cover the very rows
    it talks about. An uncaptioned still fills the frame.
    """
    layers: list[Layer] = [
        badge_layer(tag_png, TAG_CONSOLE_TEXT, (FRAME_MARGIN, FRAME_MARGIN), hold_s)
    ]
    if caption_png is not None and letterbox:
        # A screenshot, shown whole in the picture area.
        layers.append(caption_layer(caption_png, FRAMED_BAND, hold_s, darken=False))
        fit = (
            f"scale={DEMO_WIDTH}:{BAND_TOP}:force_original_aspect_ratio=decrease,"
            f"pad={DEMO_WIDTH}:{DEMO_HEIGHT}:(ow-iw)/2:({BAND_TOP}-ih)/2:color=black"
        )
    elif caption_png is not None:
        # A card is drawn square with its words in the middle: fill the picture area
        # with its middle, as the film does with its own cards.
        layers.append(caption_layer(caption_png, FRAMED_BAND, hold_s, darken=False))
        fit = (
            f"scale={DEMO_WIDTH}:{BAND_TOP}:force_original_aspect_ratio=increase,"
            f"crop={DEMO_WIDTH}:{BAND_TOP},"
            f"pad={DEMO_WIDTH}:{DEMO_HEIGHT}:0:0:color=black"
        )
    elif letterbox:
        fit = (
            f"scale={DEMO_WIDTH}:{DEMO_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={DEMO_WIDTH}:{DEMO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    else:
        fit = (
            f"scale={DEMO_WIDTH}:{DEMO_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={DEMO_WIDTH}:{DEMO_HEIGHT}"
        )
    chains = [
        f"[0:v]{fit},setsar=1,fps={DEMO_FPS},format=yuv420p[base]",
        *_layer_chains(tuple(layers), first_input=2, base="base"),
    ]
    inputs = (
        "-loop",
        "1",
        "-t",
        f"{hold_s:.3f}",
        "-i",
        str(png),
        *_silence(hold_s),
        *_layer_inputs(tuple(layers)),
    )
    return _command(inputs, chains, "1:a", output)


def _layer_inputs(layers: tuple[Layer, ...]) -> tuple[str, ...]:
    return tuple(part for layer in layers for part in layer.inputs)


def film_facts_command(film: Path) -> tuple[str, ...]:
    return (
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type",
        "-of",
        "json",
        str(film),
    )


def film_facts(film: Path, *, runner: Runner = subprocess.run) -> tuple[float, bool]:
    """How long the film is, and whether it carries sound."""
    try:
        completed = runner(
            list(film_facts_command(film)), capture_output=True, text=True, check=False
        )
    except OSError as error:
        raise DemoAssemblyError("ffprobe could not be started") from error
    if completed.returncode != 0:
        raise DemoAssemblyError("the film could not be read")
    try:
        payload = json.loads(completed.stdout)
        duration = float(payload["format"]["duration"])
        streams = payload.get("streams", [])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise DemoAssemblyError("the film's length could not be read") from error
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    return duration, has_audio


# --- assembling ---------------------------------------------------------------------


@dataclass(frozen=True)
class Preflight:
    """Everything checked before a frame is drawn."""

    console: dict[str, object]
    judgements: dict[str, Judgement]
    chapter_card: Path
    film_seconds: float
    forbidden: tuple[str, ...]


def _usable(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and path.stat().st_size > 0


def preflight(
    package_directory: Path,
    *,
    inputs: DemoInputs,
    film: Path,
    cold_open_s: float,
    result_start_s: float,
    chapter_card_name: str | None = None,
    runner: Runner = subprocess.run,
) -> Preflight:
    """Refuse, before drawing anything, everything that would make the demo wrong.

    In the order most useful to be told: the film, the proxies, the
    judgement, the package's language and cards, its console, and the
    figures against that console.
    """
    if cold_open_s < 0 or result_start_s < 0:
        raise DemoAssemblyError("the film timestamps cannot be negative")
    if not _usable(film):
        raise DemoAssemblyError("the film to excerpt is missing")
    film_seconds, has_audio = film_facts(film, runner=runner)
    needed = max(cold_open_s + SCENE_SECONDS[0], result_start_s + SCENE_SECONDS[8])
    if film_seconds < needed:
        raise DemoAssemblyError("the film is shorter than the excerpts asked of it")
    if not has_audio:
        raise DemoAssemblyError("the film has no audio track to carry through the demo")

    for event_id in inputs.event_ids:
        if not _usable(inputs.proxy_path(event_id)):
            raise DemoAssemblyError("a proxy the demo shows is missing")

    # Every window the demo shows -- the mosaic and the single one included, not only
    # the four with a panel -- must be one the model judged: the scenario's claim is
    # "337 windows judged", so nothing unjudged may stand in for them.
    record = inputs.proxy_package / VIDEO_ANALYSIS_RECORD_FILE_NAME
    judgements = load_judgements(record, inputs.event_ids)

    language_file = package_directory / PIPELINE_INPUTS_FILE_NAME
    try:
        language = json.loads(language_file.read_text(encoding="utf-8")).get("output_language")
    except (OSError, json.JSONDecodeError, AttributeError) as error:
        raise DemoAssemblyError("the package's inputs cannot be read") from error
    if language != StoryOutputLanguage.ENGLISH.value:
        raise DemoAssemblyError("the package's story is not in English")
    cards = package_directory / "story-cards"
    if chapter_card_name:
        chapter_card = chapter_cards_in(cards, chapter_card_name, chapter_card_name)[0]
        if not _usable(chapter_card):
            raise DemoAssemblyError("the named chapter card is missing")
    else:
        chapter_card = chapter_cards_in(cards)[0]

    try:
        console = PrivateJourneyConsole.from_directory(package_directory).payload()
    except PrivateJourneyConsoleError as error:
        raise DemoAssemblyError("the package has no console to read figures from") from error
    check_figures_against_console(inputs.figures, console)

    forbidden = (
        str(package_directory),
        package_directory.name,
        str(inputs.proxy_package),
        inputs.proxy_package.name,
        *inputs.event_ids,
        *(f"{event_id}.mp4" for event_id in inputs.event_ids),
        *identifiers_in(record, inputs.event_ids),
    )
    return Preflight(console, judgements, chapter_card, film_seconds, forbidden)


def assemble_demo_v2(
    package_directory: Path,
    *,
    inputs: DemoInputs,
    film: Path,
    cold_open_s: float,
    result_start_s: float,
    console_copies_png: Path | None = None,
    console_cost_png: Path | None = None,
    chapter_card_name: str | None = None,
    subtitles: Path | None = None,
    rasteriser: CardRasteriser | None = None,
    runner: Runner = subprocess.run,
    overwrite: bool = False,
) -> tuple[Path, tuple[SegmentV2, ...]]:
    """Check everything, draw every page, cut every segment, join them; wholly or not at all."""
    checked = preflight(
        package_directory,
        inputs=inputs,
        film=film,
        cold_open_s=cold_open_s,
        result_start_s=result_start_s,
        chapter_card_name=chapter_card_name,
        runner=runner,
    )
    for png in (console_copies_png, console_cost_png):
        if png is not None and not _usable(png):
            raise DemoAssemblyError("a console screenshot named on the command line is missing")

    out_dir = package_directory / DEMO_DIRECTORY_NAME
    destination = out_dir / DEMO_V2_FILE_NAME
    subtitle_path = subtitles if subtitles is not None else out_dir / DEMO_V2_SUBTITLES_FILE_NAME
    if destination.exists() and not overwrite:
        raise FileExistsError("a demo already exists here; pass overwrite=True to replace it")
    out_dir.mkdir(parents=True, exist_ok=True)

    segments = demo_timeline_v2(
        checked.console,
        inputs,
        checked.judgements,
        cold_open_s=cold_open_s,
        result_start_s=result_start_s,
        chapter_card=checked.chapter_card,
        console_copies_png=console_copies_png,
        console_cost_png=console_cost_png,
    )
    total = timeline_duration_s(segments, seconds=segment_seconds_v2)
    if abs(total - DEMO_TOTAL_S) > 1e-6:
        raise DemoAssemblyError("the timeline does not add up to the scenario's length")
    assert_no_private_text_v2(segments, checked.forbidden)

    drawn_with = rasteriser if rasteriser is not None else chosen_rasteriser()
    work = Path(mkdtemp(dir=out_dir, prefix=".assembling-v2-"))
    try:
        draw = _Drawer(work, rasteriser=drawn_with, runner=runner)
        parts: list[Path] = []
        for index, segment in enumerate(segments):
            part = work / f"part-{index:02d}.mp4"
            command = _segment_command(segment, part, film=film, inputs=inputs, draw=draw)
            _run(command, runner=runner, what=f"segment {segment.key}")
            parts.append(part)
        list_file = work / "parts.txt"
        list_file.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        joined = work / DEMO_V2_FILE_NAME
        _run(concat_command(list_file, joined), runner=runner, what="join")
        if not joined.is_file() or joined.stat().st_size == 0:
            raise DemoAssemblyError("the demo was not written")
        os.replace(joined, destination)
        subtitle_path.parent.mkdir(parents=True, exist_ok=True)
        subtitle_path.write_text(
            demo_subtitles(segments, seconds=segment_seconds_v2, spoken=spoken_v2),
            encoding="utf-8",
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return destination, segments


def _segment_command(
    segment: SegmentV2, part: Path, *, film: Path, inputs: DemoInputs, draw: _Drawer
) -> tuple[str, ...]:
    """Draw what a segment needs and build the command that cuts it."""
    if isinstance(segment, FramedExcerpt):
        caption = draw.caption(segment.title, segment.lines, FRAMED_BAND)
        return framed_excerpt_command(film, segment, draw.tag(BADGE_OUTPUT_TEXT), caption, part)
    if isinstance(segment, FullScreenExcerpt):
        return full_screen_excerpt_command(film, segment, draw.tag(BADGE_OUTPUT_TEXT), part)
    if isinstance(segment, Mosaic):
        proxies = tuple(inputs.proxy_path(event_id) for event_id in segment.event_ids)
        caption = draw.caption(segment.title, segment.lines, LOWER_THIRD_BAND)
        return mosaic_command(proxies, segment, draw.tag(TAG_RAW_TEXT), caption, part)
    if isinstance(segment, SingleRaw):
        caption = draw.caption(segment.title, segment.lines, LOWER_THIRD_BAND)
        proxy = inputs.proxy_path(segment.event_id)
        return single_raw_command(proxy, segment, draw.tag(TAG_RAW_TEXT), caption, part)
    if isinstance(segment, JudgedWindow):
        caption = draw.caption(segment.title, segment.lines, FRAMED_BAND)
        return judged_window_command(
            inputs.proxy_path(segment.event_id),
            segment,
            draw.tag(TAG_RAW_SENT_TEXT),
            draw.panel(segment.judgement),
            caption,
            part,
        )
    if isinstance(segment, ConsoleStill):
        if isinstance(segment.image, Card):
            png = rasterise_card(
                segment.image, draw.work, rasteriser=draw.rasteriser, runner=draw.runner
            )
        else:
            png = segment.image
        caption = draw.caption(segment.title, segment.lines, FRAMED_BAND)
        return console_still_command(
            png,
            segment.hold_s,
            draw.tag(TAG_CONSOLE_TEXT),
            caption,
            part,
            letterbox=segment.letterbox,
        )
    png = rasterise_card(segment, draw.work, rasteriser=draw.rasteriser, runner=draw.runner)
    return console_still_command(png, segment.hold_s, draw.tag(TAG_CONSOLE_TEXT), None, part)


def segment_table(segments: tuple[SegmentV2, ...]) -> str:
    """The timeline as a person reads it: start, length, kind, key, what it says."""
    rows = []
    at = 0.0
    for segment in segments:
        length = segment_seconds_v2(segment)
        said = " ".join(spoken_v2(segment))
        if len(said) > 60:
            said = said[:59] + "…"
        rows.append(
            f"{at:6.1f}s {length:5.1f}s  {type(segment).__name__:18} {segment.key:16} {said}"
        )
        at += length
    rows.append(f"{at:6.1f}s total")
    return "\n".join(rows)


Inspector = Callable[[Path], tuple[int, tuple[float, ...]]]
DEFAULT_PROBE_PATH = Path("private-media/cache/vision-boxes")


def inspect_demo(
    demo: Path, *, probe: Path, runner: Runner = subprocess.run
) -> tuple[int, tuple[float, ...]]:
    """Look at every frame of the finished demo for plates and faces, on this machine.

    The raw proxies go out unblurred, so the demo is inspected whole after
    it is joined, the way a published film is (app.plate_blur). Returns how
    many plate regions were read and the seconds at which a face appears.
    """
    from app.plate_blur import inspect_footage
    from app.video.vision_boxes import build_vision_boxes_probe

    if not probe.is_file():
        build_vision_boxes_probe(probe)
    work = Path(mkdtemp(dir=demo.parent, prefix=".inspecting-"))
    try:
        regions, faces = inspect_footage(demo, probe_path=probe, work=work, runner=runner)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return len(regions), faces


def main(argv: list[str] | None = None, *, inspect: Inspector | None = None) -> None:
    """Assemble the scenario-v2 demo for an English package; publishes nothing.

    The joined demo is inspected for plates and faces before it is kept: if
    either is found, the file is removed and the finding reported, so what
    is left in `demo/` is always something the owner may look at without
    first asking whether it is clean.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m app.submission.demo_scenario_v2",
        description=(
            "Assemble the second demo scenario locally: raw proxies, the console, the "
            "judgement, and the finished film in its frame. Publishes nothing; look at the "
            "footage for faces and plates before you do."
        ),
    )
    parser.add_argument("package", type=Path, help="the English package whose cards are shown")
    parser.add_argument("--inputs", type=Path, required=True, help="the demo-v2 inputs file")
    parser.add_argument("--film", type=Path, required=True, help="the published film to excerpt")
    parser.add_argument("--cold-open-s", type=float, required=True)
    parser.add_argument("--result-start-s", type=float, required=True)
    parser.add_argument("--console-copies-png", type=Path, default=None)
    parser.add_argument("--console-cost-png", type=Path, default=None)
    parser.add_argument("--chapter-card", default=None, help="a story-cards file name")
    parser.add_argument("--subtitles", type=Path, default=None, help="where to write the .srt")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--probe",
        type=Path,
        default=DEFAULT_PROBE_PATH,
        help="where the compiled Vision helper lives; it is built if absent",
    )
    parser.add_argument(
        "--skip-inspection",
        action="store_true",
        help="do not look for plates and faces in the joined demo",
    )
    args = parser.parse_args(argv)
    try:
        inputs = DemoInputs.load(args.inputs)
        out, segments = assemble_demo_v2(
            args.package,
            inputs=inputs,
            film=args.film,
            cold_open_s=args.cold_open_s,
            result_start_s=args.result_start_s,
            console_copies_png=args.console_copies_png,
            console_cost_png=args.console_cost_png,
            chapter_card_name=args.chapter_card,
            subtitles=args.subtitles,
            runner=subprocess.run,
            overwrite=args.overwrite,
        )
        if not args.skip_inspection:
            look = (
                inspect
                if inspect is not None
                else (lambda demo: inspect_demo(demo, probe=args.probe))
            )
            plates, faces = look(out)
            if plates or faces:
                srt = (
                    args.subtitles
                    if args.subtitles is not None
                    else out.parent / DEMO_V2_SUBTITLES_FILE_NAME
                )
                out.unlink(missing_ok=True)
                srt.unlink(missing_ok=True)
                when = ", ".join(f"{at:.1f}s" for at in faces[:8])
                raise DemoAssemblyError(
                    f"the joined demo shows {plates} plate regions and faces at [{when}]; "
                    "it was removed. Choose other windows."
                )
    except (DemoAssemblyError, FileExistsError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(segment_table(segments))
    print(out)
    print("inspected: skipped" if args.skip_inspection else "inspected: no plates, no faces")


if __name__ == "__main__":
    main()
