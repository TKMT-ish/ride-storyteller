"""Cut the planned film: confirmed footage and the cards between it.

Gate 3 of docs/completion-roadmap-ja.md. `journey-story-plan.json` says what
the film is, beat by beat; this turns that into an actual file. Chapter cards
are laid out by `app.chapter_card`, drawn by whichever rasteriser this
machine has, and cut together with the confirmed review clips in the plan's
own order.

Which rasteriser is a deployment question, not a design one: Quick Look on
macOS, headless Chromium in a Linux container. The card's HTML is the one
contract both draw, so the film looks the same wherever it was cut.

Two rules the assembly exists to keep. The evidence gate cannot be walked
around: a beat naming an event that no human confirmed, or whose clip is
missing, stops the render rather than quietly dropping a beat and producing a
shorter film that looks finished. And every segment is normalised to one
frame size, rate, and pixel format before being joined, because FFmpeg's
concat filter will not join streams that disagree and a mismatch caught here
is clearer than one caught halfway through an encode.

The footage's own audio is dropped. It is engine and wind noise, and Gate 3
calls for chosen copyright-free music instead. No narration is added.

Nothing here reaches the network. The commands are built as pure functions
so the whole shape of the render can be tested without FFmpeg, a browser, or
any real material.
"""

from __future__ import annotations

import bisect
import math
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from app.chapter_card import (
    LOWER_THIRD_HEIGHT_SHARE,
    POSITION_MARK_RADIUS,
    SECTION_HEIGHT_SHARE,
    build_chapter_card_html,
    build_lower_third_html,
    build_position_map_html,
    build_section_html,
    route_map_svg,
)
from app.contracts import RoutePoint
from app.gap_chapters import GapCharacter
from app.map_background import MapBackground
from app.story_package import JourneyStoryPlan, StoryPlanBeat
from app.story_timeline import StoryBeatKind

STORY_FILM_WIDTH = 1920
STORY_FILM_HEIGHT = 1080

# The film is delivered, not archived. CRF 20 with no ceiling let x264 spend
# what the footage asked for -- 32 Mbps on a day of motorcycle footage, 1.3 GB
# for five minutes -- which no viewer of a 100-yen-a-month service streams.
# CRF 23 is the encoder's own default for "good", and the VBV ceiling keeps the
# busiest stretch under what a phone on mobile data can pull.
STORY_FILM_CRF = 23
# A chapter's title over its first window (E-4): the strip under it darkens
# the picture this much, and the title fades in and out over this long
# (research §5.2: in and out within 15-25 frames, always eased).
LOWER_THIRD_STRIP_OPACITY = 0.55
LOWER_THIRD_FADE_S = 0.4

# The corner map on every clip (E-9): a square this share of the frame's
# height, this far from the top-left corner. The owner asked for it a little
# larger than the first cut's 18%.
CORNER_MAP_HEIGHT_SHARE = 0.23
CORNER_MAP_MARGIN_SHARE = 0.03
STORY_FILM_MAX_BITRATE_KBPS = 12_000
STORY_FILM_BUFFER_KBITS = 2 * STORY_FILM_MAX_BITRATE_KBPS
STORY_FILM_FPS = 30

# E-6: each footage window has its exposure and contrast stretched toward the
# full range before it is scaled, so a window shot into the sun and the one
# cut next to it read as one day rather than a jump. `independence=0` links
# the three channels -- this is a levels stretch, not a white-balance shift,
# so it never invents a colour cast. `strength` short of 1 keeps the effect
# from overcorrecting a window that was already well exposed, and
# `smoothing` softens frame-to-frame flicker (a shadow crossing the road)
# without slowing or freezing anything. A card is drawn, not filmed, and
# carries no exposure to fix, so this never touches one.
STORY_FILM_NORMALIZE_INDEPENDENCE = 0.0
STORY_FILM_NORMALIZE_STRENGTH = 0.5
STORY_FILM_NORMALIZE_SMOOTHING = 30

# The rasteriser draws HTML into a square of this size and the film's 16:9
# frame is taken from the middle of it, so the square must be as wide as the
# film. Drawing smaller and scaling up would soften the text (see
# app.chapter_card).
CARD_RASTER_SIZE = 1920

_CARD_DIRECTORY_NAME = "story-cards"


class StoryFilmError(RuntimeError):
    """Raised when the planned film cannot be cut safely."""


@dataclass(frozen=True)
class FootageSource:
    """The recording a beat is cut from, and where in it the cut begins."""

    path: Path
    start_s: float

    def __post_init__(self) -> None:
        if self.start_s < 0:
            raise ValueError("a footage source cannot start before its recording")


@dataclass(frozen=True)
class LowerThirdLayer:
    """A chapter's title drawn as a strip, laid over the first seconds of a window.

    The strip is drawn on black; the film keys it over the footage with its
    brightness as opacity and darkens the band under it, so the text reads
    on any picture. A moving route on it is a numbered run of frames, as on
    a card.
    """

    input_path: Path
    duration_s: float
    frame_rate: int | None = None

    def __post_init__(self) -> None:
        if self.duration_s <= 0:
            raise ValueError("a lower third must stay up for some time")
        if self.frame_rate is not None and self.frame_rate <= 0:
            raise ValueError("a frame sequence needs a positive rate")

    @property
    def is_sequence(self) -> bool:
        return self.frame_rate is not None


@dataclass(frozen=True)
class StoryFilmSegment:
    """One input of the final cut, with the length it is held for."""

    kind: StoryBeatKind
    input_path: Path
    duration_s: float
    source_start_s: float | None = None
    """Where in `input_path` this segment begins.

    Footage is cut from the ride's own recording rather than from the 720p
    proxy made for review, so a segment names a window inside a long file.
    A card, and a clip that is already its own file, start at the beginning
    and leave this unset.
    """

    frame_rate: int | None = None
    """Set when `input_path` is a numbered image sequence rather than one file.

    A card whose route drawing moves is a run of frames at this rate; the
    last frame is held for whatever remains of the beat. A still card and
    footage leave this unset.
    """

    lower_third: LowerThirdLayer | None = None
    """The chapter's title over this footage, when the plan lays one there."""

    corner_map: Path | None = None
    """The small map of where the ride is, laid in the corner for the whole clip."""

    section: SectionLayer | None = None
    """A section's line over this footage, when the plan lays one there."""

    def __post_init__(self) -> None:
        if self.duration_s <= 0:
            raise ValueError("a film segment must be held on screen")
        if self.source_start_s is not None and self.source_start_s < 0:
            raise ValueError("a film segment cannot start before its source")
        if self.frame_rate is not None and self.frame_rate <= 0:
            raise ValueError("a frame sequence needs a positive rate")
        if self.frame_rate is not None and self.kind is not StoryBeatKind.GAP_CARD:
            raise ValueError("only a card is a frame sequence")
        if self.lower_third is not None:
            if self.kind is not StoryBeatKind.FOOTAGE:
                raise ValueError("only footage carries a lower third")
            if self.lower_third.duration_s > self.duration_s:
                raise ValueError("a lower third cannot outlast the footage under it")
        if self.corner_map is not None and self.kind is not StoryBeatKind.FOOTAGE:
            raise ValueError("only footage carries a corner map")

    @property
    def is_sequence(self) -> bool:
        return self.frame_rate is not None

    @property
    def is_still(self) -> bool:
        """A card is one image held; footage already moves."""
        return self.kind is StoryBeatKind.GAP_CARD and self.frame_rate is None


@dataclass(frozen=True)
class StoryFilmResult:
    output_file_name: str
    segment_count: int
    footage_segment_count: int
    card_segment_count: int
    duration_s: float
    # True only for the ambient-audio film `app.story_ambient` builds beside
    # this one; `render_story_film` itself always cuts silent (see the
    # module docstring), so it never sets this.
    audio_included: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "output_file_name": self.output_file_name,
            "segment_count": self.segment_count,
            "footage_segment_count": self.footage_segment_count,
            "card_segment_count": self.card_segment_count,
            "duration_s": round(self.duration_s, 3),
            "audio_included": self.audio_included,
            "external_data_sent": False,
        }


def build_story_film_command(
    segments: tuple[StoryFilmSegment, ...],
    output_path: Path,
    *,
    width: int = STORY_FILM_WIDTH,
    height: int = STORY_FILM_HEIGHT,
    fps: int = STORY_FILM_FPS,
    overwrite: bool = False,
) -> tuple[str, ...]:
    """Build the one FFmpeg command that cuts the whole film.

    Each input is trimmed to the length the plan gives it and normalised to
    the same frame before the concat filter joins them, so a card rasterised
    square and a clip shot wide can sit next to each other.
    """
    if not segments:
        raise StoryFilmError("a film needs at least one segment")
    command: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if overwrite else "-n",
    ]
    main_inputs: list[int] = []
    corner_inputs: dict[int, int] = {}
    layer_inputs: dict[int, int] = {}
    section_inputs: dict[int, int] = {}
    next_input = 0
    for index, segment in enumerate(segments):
        main_inputs.append(next_input)
        next_input += 1
        if segment.is_still:
            command.extend(("-loop", "1"))
        if segment.is_sequence:
            # A numbered run of frames; the input ends when they do, and the
            # filter below holds the last one for the rest of the beat.
            command.extend(("-framerate", str(segment.frame_rate), "-start_number", "1"))
            command.extend(("-i", str(segment.input_path)))
        else:
            if segment.source_start_s is not None:
                # Seeking before the input makes FFmpeg jump rather than decode
                # its way there, which matters when the window is an hour in.
                command.extend(("-ss", f"{segment.source_start_s:.3f}"))
            command.extend(("-t", f"{segment.duration_s:.3f}", "-i", str(segment.input_path)))
        if segment.corner_map is not None:
            corner_inputs[index] = next_input
            next_input += 1
            command.extend(("-loop", "1", "-t", f"{segment.duration_s:.3f}"))
            command.extend(("-i", str(segment.corner_map)))
        layer = segment.lower_third
        if layer is not None:
            layer_inputs[index] = next_input
            next_input += 1
            if layer.is_sequence:
                command.extend(("-framerate", str(layer.frame_rate), "-start_number", "1"))
                command.extend(("-i", str(layer.input_path)))
            else:
                command.extend(("-loop", "1", "-t", f"{layer.duration_s:.3f}"))
                command.extend(("-i", str(layer.input_path)))
        if segment.section is not None:
            section_inputs[index] = next_input
            next_input += 1
            command.extend(("-loop", "1", "-t", f"{segment.section.duration_s:.3f}"))
            command.extend(("-i", str(segment.section.input_path)))

    chains: list[str] = []
    labels: list[str] = []
    for index, segment in enumerate(segments):
        steps = []
        if segment.is_sequence:
            steps.extend(
                (
                    f"tpad=stop_mode=clone:stop_duration={segment.duration_s:.3f}",
                    f"trim=duration={segment.duration_s:.3f}",
                    "setpts=PTS-STARTPTS",
                )
            )
        if segment.kind is StoryBeatKind.GAP_CARD:
            # The card was drawn square; the film's frame is its middle band.
            steps.append(f"crop=iw:iw*{height}/{width}")
        if segment.kind is StoryBeatKind.FOOTAGE:
            # E-6: normalise before scaling down, on the frame the camera
            # actually shot, so the stretch reads the footage's own levels
            # rather than a letterboxed one.
            steps.append(
                "normalize="
                f"independence={STORY_FILM_NORMALIZE_INDEPENDENCE}:"
                f"strength={STORY_FILM_NORMALIZE_STRENGTH}:"
                f"smoothing={STORY_FILM_NORMALIZE_SMOOTHING}"
            )
        steps.extend(
            (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                "setsar=1",
                f"fps={fps}",
                "format=yuv420p",
            )
        )
        chains.append(f"[{main_inputs[index]}:v:0]{','.join(steps)}[v{index}]")
        label = f"v{index}"
        if segment.corner_map is not None:
            chains.extend(
                _corner_map_chains(index, corner_inputs[index], width=width, height=height, fps=fps)
            )
            label = f"c{index}"
        if segment.lower_third is not None:
            chains.extend(
                _lower_third_chains(
                    index,
                    layer_inputs[index],
                    segment.lower_third,
                    width=width,
                    height=height,
                    fps=fps,
                    base=label,
                )
            )
            label = f"w{index}"
        if segment.section is not None:
            chains.extend(
                _section_chains(
                    index,
                    section_inputs[index],
                    segment.section,
                    width=width,
                    height=height,
                    fps=fps,
                    base=label,
                )
            )
            label = f"x{index}"
        labels.append(label)
    joined = "".join(f"[{label}]" for label in labels)
    chains.append(f"{joined}concat=n={len(segments)}:v=1:a=0[v]")

    command.extend(
        (
            "-filter_complex",
            ";".join(chains),
            "-map",
            "[v]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            str(STORY_FILM_CRF),
            "-maxrate",
            f"{STORY_FILM_MAX_BITRATE_KBPS}k",
            "-bufsize",
            f"{STORY_FILM_BUFFER_KBITS}k",
            "-movflags",
            "+faststart",
            str(output_path),
        )
    )
    return tuple(command)


def _corner_map_chains(
    index: int, corner_input: int, *, width: int, height: int, fps: int
) -> list[str]:
    """Lay the clip's small map of the ride, and where it is, in the top-left corner."""
    side = round(height * CORNER_MAP_HEIGHT_SHARE)
    margin = round(height * CORNER_MAP_MARGIN_SHARE)
    return [
        f"[{corner_input}:v:0]scale={side}:{side},fps={fps},format=yuv420p[m{index}]",
        f"[v{index}][m{index}]overlay={margin}:{margin}:eof_action=pass:repeatlast=0[c{index}]",
    ]


def _lower_third_chains(
    index: int,
    layer_input: int,
    layer: LowerThirdLayer,
    *,
    width: int,
    height: int,
    fps: int,
    base: str | None = None,
) -> list[str]:
    """Lay a chapter's title strip over the first seconds of segment `index`.

    Two things go over the window: a translucent black strip that darkens
    the band the text sits in, and the drawn title, keyed by its brightness
    so its black page vanishes. Both fade in and out together, and both
    end before the window does; after that the footage passes through.
    """
    strip_height = round(height * LOWER_THIRD_HEIGHT_SHARE)
    top = height - strip_height
    duration = f"{layer.duration_s:.3f}"
    fade_out_at = f"{max(0.0, layer.duration_s - LOWER_THIRD_FADE_S):.3f}"
    fades = (
        f"fade=t=in:st=0:d={LOWER_THIRD_FADE_S}:alpha=1",
        f"fade=t=out:st={fade_out_at}:d={LOWER_THIRD_FADE_S}:alpha=1",
    )
    title_steps: list[str] = []
    if layer.is_sequence:
        title_steps.extend(
            (
                f"tpad=stop_mode=clone:stop_duration={duration}",
                f"trim=duration={duration}",
                "setpts=PTS-STARTPTS",
            )
        )
    title_steps.extend(
        (
            # The page was drawn square; the film's band is its middle, and
            # the strip is the bottom of that band.
            f"crop=iw:iw*{height}/{width}",
            f"crop=iw:ih*{LOWER_THIRD_HEIGHT_SHARE:.6f}:0:ih*{1 - LOWER_THIRD_HEIGHT_SHARE:.6f}",
            f"scale={width}:{strip_height}",
            f"fps={fps}",
            "format=rgba",
            # Brightness becomes opacity: white text stays, the black page goes.
            "colorchannelmixer=aa=0:ar=0.299:ag=0.587:ab=0.114",
            *fades,
        )
    )
    strip = (
        f"color=c=black@{LOWER_THIRD_STRIP_OPACITY}:s={width}x{strip_height}:r={fps}:d={duration}"
        + ",format=rgba,"
        + ",".join(fades)
    )
    under = base or f"v{index}"
    return [
        f"[{layer_input}:v:0]{','.join(title_steps)}[t{index}]",
        f"{strip}[s{index}]",
        f"[{under}][s{index}]overlay=0:{top}:eof_action=pass:repeatlast=0[u{index}]",
        f"[u{index}][t{index}]overlay=0:{top}:eof_action=pass:repeatlast=0[w{index}]",
    ]


@dataclass(frozen=True)
class SectionLayer:
    """A section's one-line strip, laid over the first seconds of a window (点 8)."""

    input_path: Path
    duration_s: float

    def __post_init__(self) -> None:
        if self.duration_s <= 0:
            raise ValueError("a section strip must stay up for some time")


def _section_chains(
    index: int,
    layer_input: int,
    layer: SectionLayer,
    *,
    width: int,
    height: int,
    fps: int,
    base: str | None = None,
) -> list[str]:
    """Lay a section's slim strip over the first seconds of segment `index`.

    The same two things as the chapter's lower third -- a translucent
    darkening of the band the line sits in, and the drawn line keyed by
    its brightness -- at a ninth of the frame instead of two.
    """
    strip_height = round(height * SECTION_HEIGHT_SHARE)
    top = height - strip_height
    duration = f"{layer.duration_s:.3f}"
    fade_out_at = f"{max(0.0, layer.duration_s - LOWER_THIRD_FADE_S):.3f}"
    fades = (
        f"fade=t=in:st=0:d={LOWER_THIRD_FADE_S}:alpha=1",
        f"fade=t=out:st={fade_out_at}:d={LOWER_THIRD_FADE_S}:alpha=1",
    )
    line_steps = (
        f"crop=iw:iw*{height}/{width}",
        f"crop=iw:ih*{SECTION_HEIGHT_SHARE:.6f}:0:ih*{1 - SECTION_HEIGHT_SHARE:.6f}",
        f"scale={width}:{strip_height}",
        f"fps={fps}",
        "format=rgba",
        "colorchannelmixer=aa=0:ar=0.299:ag=0.587:ab=0.114",
        *fades,
    )
    strip = (
        f"color=c=black@{LOWER_THIRD_STRIP_OPACITY}:s={width}x{strip_height}:r={fps}:d={duration}"
        + ",format=rgba,"
        + ",".join(fades)
    )
    under = base or f"v{index}"
    return [
        f"[{layer_input}:v:0]{','.join(line_steps)}[y{index}]",
        f"{strip}[z{index}]",
        f"[{under}][z{index}]overlay=0:{top}:eof_action=pass:repeatlast=0[q{index}]",
        f"[q{index}][y{index}]overlay=0:{top}:eof_action=pass:repeatlast=0[x{index}]",
    ]


class CardRasteriser(Protocol):
    """Turns one card's HTML into one square PNG.

    Two exist because the film is cut in two places. On the developer's Mac,
    Quick Look draws the card with nothing installed at all. In a Linux
    container -- Cloud Run included -- headless Chromium draws the same HTML.
    Both are asked for the same square, so the crop that takes the film's
    16:9 frame is identical either way. Keeping the HTML as the one card
    contract is what makes that possible: only the rasteriser changes, never
    the design.

    Measured on one real card, the two agree on layout, sizes and content
    exactly, and differ only in how glyphs are rasterised -- Quick Look lays
    ink down heavier (PSNR 25 dB, all of it on text edges). Same card, not
    the same pixels. What a Linux container must not skip is installing a
    CJK font; the card's own font stack cannot conjure glyphs that are not
    on the machine.
    """

    name: str

    def command(self, html_path: Path, output_directory: Path, *, size: int) -> tuple[str, ...]: ...

    def output_path(self, html_path: Path, output_directory: Path) -> Path: ...


@dataclass(frozen=True)
class QuickLookRasteriser:
    """macOS, no dependency to install. Requires a logged-in user session."""

    name: str = "quick-look"
    # qlmanage takes any number of files in one invocation, and its start-up
    # is most of the cost: twenty-five frames measured at 0.72 s together.
    batch: bool = True

    def command(
        self, html_path: Path, output_directory: Path, *, size: int = CARD_RASTER_SIZE
    ) -> tuple[str, ...]:
        return (
            "qlmanage",
            "-t",
            "-s",
            str(size),
            "-o",
            str(output_directory),
            str(html_path),
        )

    def output_path(self, html_path: Path, output_directory: Path) -> Path:
        """Quick Look names its output after the whole source file name."""
        return output_directory / f"{html_path.name}.png"


@dataclass(frozen=True)
class HeadlessChromiumRasteriser:
    """Linux containers, where Quick Look does not exist.

    Chromium is told the same square window so the card's viewport-relative
    layout resolves exactly as it does under Quick Look.
    """

    name: str = "headless-chromium"
    executable: str = "chromium"
    batch: bool = False

    def command(
        self, html_path: Path, output_directory: Path, *, size: int = CARD_RASTER_SIZE
    ) -> tuple[str, ...]:
        return (
            self.executable,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-sandbox",
            f"--window-size={size},{size}",
            f"--screenshot={self.output_path(html_path, output_directory)}",
            html_path.as_uri(),
        )

    def output_path(self, html_path: Path, output_directory: Path) -> Path:
        return output_directory / f"{html_path.name}.png"


QUICK_LOOK = QuickLookRasteriser()
HEADLESS_CHROMIUM = HeadlessChromiumRasteriser()
# Which of them draws the cards, when nobody says. The card is one HTML
# contract and the operating system draws it: Quick Look here, headless
# Chromium anywhere else, so a package cut on someone else's machine gets the
# same cards without their having to know that.
CARD_RASTERISER_ENV = "RIDE_CARD_RASTERISER"
_RASTERISERS = {"quick-look": QUICK_LOOK, "chromium": HEADLESS_CHROMIUM}


def chosen_rasteriser(
    *, platform: str | None = None, environ: Mapping[str, str] | None = None
) -> CardRasteriser:
    """The card rasteriser this machine should use, or the one it was told to."""
    values = os.environ if environ is None else environ
    named = str(values.get(CARD_RASTERISER_ENV, "")).strip().lower()
    if named:
        if named not in _RASTERISERS:
            raise StoryFilmError("the card rasteriser must be quick-look or chromium")
        return _RASTERISERS[named]
    system = sys.platform if platform is None else platform
    return QUICK_LOOK if system == "darwin" else HEADLESS_CHROMIUM


def build_card_raster_command(
    html_path: Path,
    output_directory: Path,
    *,
    size: int = CARD_RASTER_SIZE,
    rasteriser: CardRasteriser = QUICK_LOOK,
) -> tuple[str, ...]:
    """Build the command that draws one card."""
    return rasteriser.command(html_path, output_directory, size=size)


def card_raster_path(
    html_path: Path, output_directory: Path, *, rasteriser: CardRasteriser = QUICK_LOOK
) -> Path:
    """Where the chosen rasteriser will have written the card."""
    return rasteriser.output_path(html_path, output_directory)


# A chapter's stretch of the route draws itself over this long, then holds;
# the research puts a route segment at three to five seconds with a pause at
# its end (docs/research-touring-video-editing-ja.md §4.2). The headline card
# draws the whole day and gets longer.
CARD_GROW_S = 3.5
HEADLINE_GROW_S = 6.0
CARD_FRAME_RATE = 12


@dataclass(frozen=True)
class CardRaster:
    """What was drawn for one card: a still, and the frames if it moves."""

    still: Path
    pattern: Path | None = None
    frame_rate: int | None = None
    lower_third: bool = False
    """Drawn as a strip to lay over footage, not as a full-screen card."""

    @property
    def is_sequence(self) -> bool:
        return self.pattern is not None and self.frame_rate is not None


def write_chapter_cards(
    plan: JourneyStoryPlan,
    package_directory: Path,
    *,
    route_points: tuple[RoutePoint, ...] | None = None,
    rasteriser: CardRasteriser = QUICK_LOOK,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    animate: bool = True,
    frame_rate: int = CARD_FRAME_RATE,
    background: MapBackground | None = None,
) -> tuple[CardRaster, ...]:
    """Lay out and draw every chapter card of the plan, in order.

    With the ride's track, each card carries the whole route faintly and its
    own stretch picked out -- and, when animated, that stretch draws itself
    in over the first seconds of the card and then holds (E-3 of the
    research). The headline card draws the whole day from start to finish;
    the closing card shows it drawn. The chapters in between share the
    route by their position among the chapter cards alone, so a headline
    or a close does not push the first chapter's stretch off its start.

    Every frame of every card is one HTML file and they are drawn together
    in one call where the rasteriser allows it, because starting it is most
    of the cost. Without a track, or without animation, a card is one still.
    """
    card_directory = package_directory / _CARD_DIRECTORY_NAME
    if card_directory.is_symlink():
        raise StoryFilmError("the chapter card directory path is unsafe")
    card_directory.mkdir(parents=True, exist_ok=True)
    if frame_rate <= 0:
        raise StoryFilmError("cards need a positive frame rate")
    # A card that animated last time may hold still now; ffmpeg reads a
    # numbered sequence until the numbers stop, so old frames must not stay.
    for pattern in ("card-*", "pos-*", "sec-*"):
        for stale in card_directory.glob(pattern):
            if stale.is_file() or stale.is_symlink():
                stale.unlink()

    card_beats = plan.beats_with_cards
    has_route = route_points is not None and len(route_points) >= 2
    spans = _card_spans(card_beats, route_points) if has_route else {}

    html_paths: list[Path] = []
    rasters: list[CardRaster] = []
    for index, beat in enumerate(card_beats):
        assert beat.card is not None
        stem = f"card-{index + 1:03d}"
        over_footage = beat.is_titled_footage
        page = build_lower_third_html if over_footage else build_chapter_card_html
        if not has_route:
            html_path = card_directory / f"{stem}.html"
            html_path.write_text(page(beat.card), encoding="utf-8")
            html_paths.append(html_path)
            rasters.append(
                CardRaster(
                    still=card_raster_path(html_path, card_directory, rasteriser=rasteriser),
                    lower_third=over_footage,
                )
            )
            continue

        assert route_points is not None
        span = spans[index]
        first, last = span.first, span.last
        # A halt is a point: there is nothing to draw in, so the card holds.
        grow_s = 0.0 if span.is_point else _grow_seconds(beat, animate=animate)
        frame_count = max(1, math.ceil(grow_s * frame_rate)) if grow_s > 0 else 1
        for frame in range(1, frame_count + 1):
            reach = (
                last if frame_count == 1 else _eased(first, last, (frame - 1) / (frame_count - 1))
            )
            svg = _card_map(route_points, span, reach, background)
            html_path = card_directory / (
                f"{stem}-f{frame:03d}.html" if frame_count > 1 else f"{stem}.html"
            )
            html_path.write_text(page(beat.card, route_map_svg=svg), encoding="utf-8")
            html_paths.append(html_path)
        if frame_count > 1:
            # The still is the finished drawing: what the console and the demo show.
            still_html = card_directory / f"{stem}.html"
            still_html.write_text(
                page(beat.card, route_map_svg=_card_map(route_points, span, last, background)),
                encoding="utf-8",
            )
            html_paths.append(still_html)
            pattern_html = card_directory / f"{stem}-f%03d.html"
            rasters.append(
                CardRaster(
                    still=card_raster_path(still_html, card_directory, rasteriser=rasteriser),
                    pattern=card_raster_path(pattern_html, card_directory, rasteriser=rasteriser),
                    frame_rate=frame_rate,
                    lower_third=over_footage,
                )
            )
        else:
            rasters.append(
                CardRaster(
                    still=card_raster_path(html_paths[-1], card_directory, rasteriser=rasteriser),
                    lower_third=over_footage,
                )
            )

    _rasterise_many(html_paths, card_directory, rasteriser=rasteriser, runner=runner)
    for raster in rasters:
        if not raster.still.is_file():
            raise StoryFilmError("a chapter card could not be drawn")
    return tuple(rasters)


def write_position_maps(
    plan: JourneyStoryPlan,
    package_directory: Path,
    *,
    route_points: tuple[RoutePoint, ...],
    ride_times: Mapping[str, datetime],
    rasteriser: CardRasteriser = QUICK_LOOK,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    background: MapBackground | None = None,
) -> dict[str, Path]:
    """Draw, for every footage beat, the small map of where the ride is (E-9).

    Each clip gets one still: the whole route faint, the part ridden so far
    picked out, and a dot where the track was in the middle of the clip. A
    beat whose ride time is unknown gets no map rather than a wrong one.
    Every page is drawn in one call where the rasteriser allows it. Must be
    called after `write_chapter_cards`, which clears the directory.
    """
    card_directory = package_directory / _CARD_DIRECTORY_NAME
    if card_directory.is_symlink():
        raise StoryFilmError("the chapter card directory path is unsafe")
    card_directory.mkdir(parents=True, exist_ok=True)
    if len(route_points) < 2:
        return {}
    stamps = [point.timestamp for point in route_points]
    html_paths: list[Path] = []
    maps: dict[str, Path] = {}
    for number, beat in enumerate(plan.footage_beats, start=1):
        assert beat.event_id is not None
        begins = ride_times.get(beat.event_id)
        if begins is None:
            continue
        middle = begins + timedelta(seconds=beat.source_offset_s + beat.screen_duration_s / 2)
        here = _index_at(stamps, middle)
        svg = route_map_svg(
            route_points,
            highlight_from_index=0,
            highlight_to_index=max(1, here),
            mark_index=here,
            mark_radius=POSITION_MARK_RADIUS,
            background=background,
        )
        html_path = card_directory / f"pos-{number:03d}.html"
        html_path.write_text(build_position_map_html(svg), encoding="utf-8")
        html_paths.append(html_path)
        maps[beat.event_id] = card_raster_path(html_path, card_directory, rasteriser=rasteriser)
    _rasterise_many(html_paths, card_directory, rasteriser=rasteriser, runner=runner)
    for png in maps.values():
        if not png.is_file():
            raise StoryFilmError("a position map could not be drawn")
    return maps


def write_section_strips(
    plan: JourneyStoryPlan,
    package_directory: Path,
    *,
    rasteriser: CardRasteriser = QUICK_LOOK,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Path]:
    """Draw, for every footage beat carrying a section, its one-line strip (点 8).

    One page per section, drawn together in one call where the rasteriser
    allows it. Must be called after `write_chapter_cards`, which clears the
    directory.
    """
    card_directory = package_directory / _CARD_DIRECTORY_NAME
    if card_directory.is_symlink():
        raise StoryFilmError("the chapter card directory path is unsafe")
    card_directory.mkdir(parents=True, exist_ok=True)
    html_paths: list[Path] = []
    strips: dict[str, Path] = {}
    number = 0
    for beat in plan.footage_beats:
        if beat.section is None:
            continue
        assert beat.event_id is not None
        number += 1
        html_path = card_directory / f"sec-{number:03d}.html"
        html_path.write_text(build_section_html(beat.section.text), encoding="utf-8")
        html_paths.append(html_path)
        strips[beat.event_id] = card_raster_path(html_path, card_directory, rasteriser=rasteriser)
    _rasterise_many(html_paths, card_directory, rasteriser=rasteriser, runner=runner)
    for png in strips.values():
        if not png.is_file():
            raise StoryFilmError("a section strip could not be drawn")
    return strips


def _chapter_positions(card_beats: tuple[StoryPlanBeat, ...]) -> dict[int, tuple[int, int]]:
    """Each chapter card's (position, count) among the chapter cards alone."""
    chapters = [
        index
        for index, beat in enumerate(card_beats)
        if beat.card is not None and not _spans_whole_day(beat.card.character)
    ]
    return {index: (position, len(chapters)) for position, index in enumerate(chapters)}


def _spans_whole_day(character: GapCharacter) -> bool:
    return character in (GapCharacter.HEADLINE, GapCharacter.CLOSE)


@dataclass(frozen=True)
class _CardSpan:
    """The route indices one card picks out, and whether it is a point instead."""

    first: int
    last: int
    mark: int | None = None
    wide: bool = False

    @property
    def is_point(self) -> bool:
        return self.mark is not None


def _card_spans(
    card_beats: tuple[StoryPlanBeat, ...], route_points: tuple[RoutePoint, ...]
) -> dict[int, _CardSpan]:
    """Where on the route each card's stretch lies.

    When every chapter card knows its place on the ride's clock, the stretch
    is cut where the track was at that time -- the chapter's real extent. A
    plan written before cards carried a clock falls back to sharing the route
    out by position among the chapter cards. A halt is a point either way:
    where the track stood at the middle of the halt, or the middle of its
    share. The headline and the close take the whole day, drawn large.
    """
    point_count = len(route_points)
    positions = _chapter_positions(card_beats)
    on_the_clock = all(
        card_beats[index].card is not None and card_beats[index].card.is_on_the_clock
        for index in positions
    )
    stamps = [point.timestamp for point in route_points]
    departure = stamps[0]

    spans: dict[int, _CardSpan] = {}
    for index, beat in enumerate(card_beats):
        card = beat.card
        assert card is not None
        if _spans_whole_day(card.character):
            spans[index] = _CardSpan(0, point_count - 1, wide=True)
            continue
        if on_the_clock:
            assert card.since_departure_s is not None and card.duration_s is not None
            began = departure + timedelta(seconds=card.since_departure_s)
            ended = began + timedelta(seconds=card.duration_s)
            first = min(_index_at(stamps, began), point_count - 2)
            last = min(max(_index_at(stamps, ended), first + 1), point_count - 1)
            middle = _index_at(stamps, began + timedelta(seconds=card.duration_s / 2))
        else:
            position, count = positions[index]
            first, last = _stretch_indices(position, count, point_count)
            middle = (first + last) // 2
        mark = middle if card.character is GapCharacter.HALT else None
        spans[index] = _CardSpan(first, last, mark=mark)
    return spans


def _index_at(stamps: list[datetime], when: datetime) -> int:
    """The first track point at or after this moment, clamped to the track."""
    return min(len(stamps) - 1, max(0, bisect.bisect_left(stamps, when)))


def _card_map(
    route_points: tuple[RoutePoint, ...],
    span: _CardSpan,
    reach: int,
    background: MapBackground | None = None,
) -> str:
    """This card's map: its stretch drawn as far as `reach`, or its point."""
    if span.is_point:
        return route_map_svg(
            route_points, mark_index=span.mark, wide=span.wide, background=background
        )
    return route_map_svg(
        route_points,
        highlight_from_index=span.first,
        highlight_to_index=reach,
        wide=span.wide,
        background=background,
    )


def _grow_seconds(beat: StoryPlanBeat, *, animate: bool) -> float:
    """How long the stretch takes to draw: within the card's own time on screen.

    For a title over footage that is the card's screen time, not the
    window's, so the drawing is done before the title fades.
    """
    assert beat.card is not None
    if not animate:
        return 0.0
    if beat.card.character is GapCharacter.CLOSE:
        return 0.0
    shown_s = beat.card.screen_duration_s
    if beat.card.character is GapCharacter.HEADLINE:
        return min(HEADLINE_GROW_S, max(0.0, shown_s - 1.0))
    return min(CARD_GROW_S, max(0.0, shown_s - 1.0))


def _eased(first: int, last: int, share: float) -> int:
    """Where the drawing has reached: quick to start, settling at the end."""
    eased = 1.0 - (1.0 - share) ** 2
    return min(last, max(first + 1, first + round((last - first) * eased)))


def _rasterise_many(
    html_paths: list[Path],
    card_directory: Path,
    *,
    rasteriser: CardRasteriser,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """Draw every page, in one call where the rasteriser allows it."""
    if not html_paths:
        return
    for html_path in html_paths:
        card_raster_path(html_path, card_directory, rasteriser=rasteriser).unlink(missing_ok=True)
    if getattr(rasteriser, "batch", False):
        command = list(
            build_card_raster_command(html_paths[0], card_directory, rasteriser=rasteriser)
        )
        command.extend(str(path) for path in html_paths[1:])
        _run_rasteriser(
            tuple(command), rasteriser=rasteriser, runner=runner, timeout=60 + 2 * len(html_paths)
        )
    else:
        for html_path in html_paths:
            command = build_card_raster_command(html_path, card_directory, rasteriser=rasteriser)
            _run_rasteriser(command, rasteriser=rasteriser, runner=runner, timeout=60)


def _run_rasteriser(
    command: tuple[str, ...],
    *,
    rasteriser: CardRasteriser,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    timeout: float,
) -> None:
    try:
        completed = runner(command, check=False, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as error:
        raise StoryFilmError(
            f"the {rasteriser.name} rasteriser is required to draw chapter cards here"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise StoryFilmError("drawing a chapter card timed out") from error
    if completed.returncode != 0:
        raise StoryFilmError("a chapter card could not be drawn")


def _stretch_indices(index: int, card_count: int, point_count: int) -> tuple[int, int]:
    """Place this card's stretch along the route, in plan order."""
    if card_count <= 0:
        raise StoryFilmError("a stretch cannot be placed without cards")
    first = round(point_count * index / card_count)
    last = round(point_count * (index + 1) / card_count)
    first = min(first, point_count - 2)
    last = min(max(last, first + 1), point_count - 1)
    return first, last


def _rasterise_card(
    html_path: Path,
    card_directory: Path,
    *,
    rasteriser: CardRasteriser,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> Path:
    raster = card_raster_path(html_path, card_directory, rasteriser=rasteriser)
    raster.unlink(missing_ok=True)
    command = build_card_raster_command(html_path, card_directory, rasteriser=rasteriser)
    try:
        completed = runner(command, check=False, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as error:
        raise StoryFilmError(
            f"the {rasteriser.name} rasteriser is required to draw chapter cards here"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise StoryFilmError("drawing a chapter card timed out") from error
    if completed.returncode != 0 or not raster.is_file():
        raise StoryFilmError("a chapter card could not be drawn")
    return raster


def build_story_film_segments(
    plan: JourneyStoryPlan,
    card_rasters: Sequence[Path | CardRaster],
    footage_sources: dict[str, FootageSource],
    position_maps: Mapping[str, Path] | None = None,
    section_strips: Mapping[str, Path] | None = None,
) -> tuple[StoryFilmSegment, ...]:
    """Pair every beat of the plan with the file and window that will fill it.

    A footage beat whose source is absent stops the assembly. Dropping it
    would leave a shorter film that still looked complete, and the whole point
    of the evidence gate is that the film shows only what was confirmed.
    """
    if len(card_rasters) != len(plan.beats_with_cards):
        raise StoryFilmError("the drawn chapter cards do not match the plan")
    cards = iter(card_rasters)
    segments: list[StoryFilmSegment] = []
    for beat in plan.beats:
        if beat.kind is StoryBeatKind.GAP_CARD:
            drawn = next(cards)
            if isinstance(drawn, CardRaster) and drawn.is_sequence:
                assert drawn.pattern is not None
                segments.append(
                    StoryFilmSegment(
                        kind=beat.kind,
                        input_path=drawn.pattern,
                        duration_s=beat.screen_duration_s,
                        frame_rate=drawn.frame_rate,
                    )
                )
            else:
                still = drawn.still if isinstance(drawn, CardRaster) else drawn
                segments.append(
                    StoryFilmSegment(
                        kind=beat.kind, input_path=still, duration_s=beat.screen_duration_s
                    )
                )
            continue
        source = _footage_source(beat, footage_sources)
        layer: LowerThirdLayer | None = None
        if beat.card is not None:
            drawn = next(cards)
            if isinstance(drawn, CardRaster) and drawn.is_sequence:
                assert drawn.pattern is not None
                layer = LowerThirdLayer(
                    input_path=drawn.pattern,
                    duration_s=beat.card.screen_duration_s,
                    frame_rate=drawn.frame_rate,
                )
            else:
                still = drawn.still if isinstance(drawn, CardRaster) else drawn
                layer = LowerThirdLayer(input_path=still, duration_s=beat.card.screen_duration_s)
        segments.append(
            StoryFilmSegment(
                kind=beat.kind,
                input_path=source.path,
                duration_s=beat.screen_duration_s,
                # The window's start in its recording, plus how far into the
                # window the plan begins the cut (E-2).
                source_start_s=source.start_s + beat.source_offset_s,
                lower_third=layer,
                corner_map=(position_maps or {}).get(beat.event_id),
                section=(
                    SectionLayer(
                        input_path=(section_strips or {})[beat.event_id],
                        duration_s=beat.section.screen_duration_s,
                    )
                    if beat.section is not None and beat.event_id in (section_strips or {})
                    else None
                ),
            )
        )
    return tuple(segments)


def _footage_source(
    beat: StoryPlanBeat, footage_sources: dict[str, FootageSource]
) -> FootageSource:
    assert beat.event_id is not None
    source = footage_sources.get(beat.event_id)
    if source is None:
        raise StoryFilmError("a planned footage beat has no confirmed clip")
    if source.path.is_symlink() or not source.path.is_file():
        raise StoryFilmError("a confirmed clip is unavailable")
    return source


def render_story_film(
    segments: tuple[StoryFilmSegment, ...],
    output_path: Path,
    *,
    overwrite: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> StoryFilmResult:
    """Cut the film, and only put it in place once it is whole.

    Encoding a five-minute film takes minutes, and anything that stops
    FFmpeg partway -- a timeout, an interrupt, a full disk -- leaves an MP4
    with no index: hundreds of megabytes that look like a finished film and
    will not play. So the cut is written beside the destination and moved
    onto it only after FFmpeg reports success and the file is there. An
    interrupted render leaves no film rather than a broken one.
    """
    if output_path.is_symlink():
        raise StoryFilmError("the film output path is unsafe")
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            "film output already exists; choose a new name or pass overwrite=True"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the suffix: FFmpeg picks its muxer from the extension.
    partial_path = output_path.with_name(
        f".{output_path.stem}.partial-{os.getpid()}{output_path.suffix}"
    )
    partial_path.unlink(missing_ok=True)
    command = build_story_film_command(segments, partial_path, overwrite=True)
    total_duration_s = sum(segment.duration_s for segment in segments)
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(300.0, total_duration_s * 20),
        )
    except FileNotFoundError as error:
        partial_path.unlink(missing_ok=True)
        raise StoryFilmError("ffmpeg is required to cut the film") from error
    except subprocess.TimeoutExpired as error:
        partial_path.unlink(missing_ok=True)
        raise StoryFilmError("cutting the film timed out") from error
    except BaseException:
        # A Ctrl-C or a kill must not leave an unplayable film behind either.
        partial_path.unlink(missing_ok=True)
        raise
    if completed.returncode != 0:
        partial_path.unlink(missing_ok=True)
        raise StoryFilmError("ffmpeg could not cut the planned film")
    if not partial_path.is_file():
        raise StoryFilmError("ffmpeg did not create the expected film")
    os.replace(partial_path, output_path)
    return StoryFilmResult(
        output_file_name=output_path.name,
        segment_count=len(segments),
        footage_segment_count=sum(
            1 for segment in segments if segment.kind is StoryBeatKind.FOOTAGE
        ),
        card_segment_count=sum(1 for segment in segments if segment.kind is StoryBeatKind.GAP_CARD),
        duration_s=total_duration_s,
    )
