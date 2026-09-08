"""Assemble the three-minute demo locally, from the film and its own parts.

The demo script is mostly footage: five stretches of the finished film carry
the narration as a caption over their lower third (Q5 of
docs/user-feedback-2026-09-04-ja.md -- a demo that opens on cards and closes
on fifteen seconds of video reads as a slideshow, not a video product's
demo). A full-screen card remains only for what a caption cannot hold -- the
console's own figures -- and three stills (two of the film's own chapter
cards, and the evidence gate) are held briefly between stretches. The
default timeline spends well over half its three minutes on footage, cut
back to back from one place in the film so reviewing it for faces and
plates is one contiguous look, not several. Every card and caption here is
drawn the way the film's chapter cards are drawn -- one HTML contract,
rasterised by the OS -- so the demo looks like the product, because it is
made of it. The console's stages are drawn from the same payload the page
reads, not from a screenshot, so what the demo shows is what the package
says.

Nothing is published. The result is a file under the private work directory,
with the subtitle file beside it; putting it anywhere is a separate act by
the owner, after they have looked at the film's footage -- there is
substantially more of it in view now than one fifteen-second excerpt -- for
faces and plates.

What a card or caption may say is bounded the same way the console is:
counts, sizes, durations, money, and the words already on the film's own
cards. No file name, path, coordinate or capture time appears in any of
them, held by test. FFmpeg on this machine has no text renderer, which is
why the cards are HTML and the subtitles are a file rather than burned in.
"""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

from app.chapter_card import (
    CARD_ASPECT_DENOMINATOR,
    CARD_ASPECT_NUMERATOR,
    LOWER_THIRD_HEIGHT_SHARE,
)
from app.story_film import (
    CARD_RASTER_SIZE,
    LOWER_THIRD_FADE_S,
    LOWER_THIRD_STRIP_OPACITY,
    QUICK_LOOK,
    CardRasteriser,
)
from app.web.private_journey_console import PrivateJourneyConsole

DEMO_ASSEMBLY_SCHEMA_VERSION = "demo-assembly-v1"
DEMO_FILE_NAME = "demo-en.mp4"
SCORED_FILM_FILE_NAME = "ride-storyteller-story-film-scored.mp4"
DEMO_DIRECTORY_NAME = "demo"
DEMO_WIDTH = 1920
DEMO_HEIGHT = 1080
DEMO_FPS = 30
# Three minutes is the official ceiling, so the timeline stops short of it:
# an encode lands a few hundredths of a second over its own sum, and a demo
# measured at 3:00.02 is a demo an automated check can refuse.
DEMO_TOTAL_S = 177.0

Runner = Callable[..., subprocess.CompletedProcess[str]]


class DemoAssemblyError(RuntimeError):
    """Raised when the demo cannot be assembled as asked."""


@dataclass(frozen=True)
class Card:
    """One full-screen card: a title, a few lines, held for some seconds."""

    key: str
    title: str
    lines: tuple[str, ...]
    hold_s: float

    def __post_init__(self) -> None:
        if not self.key or not self.title:
            raise ValueError("a card needs a key and a title")
        if self.hold_s <= 0:
            raise ValueError("a card must be held for a positive time")


@dataclass(frozen=True)
class Excerpt:
    """A stretch of the finished film, shown as it is."""

    key: str
    start_s: float
    duration_s: float

    def __post_init__(self) -> None:
        if self.start_s < 0 or self.duration_s <= 0:
            raise ValueError("an excerpt needs a non-negative start and a positive length")


@dataclass(frozen=True)
class Still:
    """An existing image, held for some seconds."""

    key: str
    path: Path
    hold_s: float


@dataclass(frozen=True)
class CaptionedExcerpt:
    """A stretch of the finished film with narration held over its lower third.

    The footage plays and the caption fades in over it, the same lower-third
    band the film's own chapter titles use (E-4) but without a route map --
    the demo has no ride to draw one for. When `caption_hold_s` is shorter
    than the excerpt, the caption fades out and the footage plays on alone
    for the rest; when it is None the caption stays for the whole excerpt.
    """

    key: str
    start_s: float
    duration_s: float
    title: str
    lines: tuple[str, ...]
    caption_hold_s: float | None = None

    def __post_init__(self) -> None:
        if self.start_s < 0 or self.duration_s <= 0:
            raise ValueError("an excerpt needs a non-negative start and a positive length")
        if not self.title:
            raise ValueError("a caption needs a title")
        hold = self.hold_s
        if hold <= 0 or hold > self.duration_s:
            raise ValueError("a caption cannot outlast the excerpt it is held over")

    @property
    def hold_s(self) -> float:
        return self.caption_hold_s if self.caption_hold_s is not None else self.duration_s


Segment = Card | Excerpt | Still | CaptionedExcerpt


def card_html(card: Card) -> str:
    """The same dark, centred contract the chapter cards use."""
    body = "".join(f'<div class="body">{html.escape(line)}</div>' for line in card.lines)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
html,body{{margin:0;padding:0}}
body{{width:100vw;height:100vh;background:#11131a;color:#f4f4f2;
font-family:"Helvetica Neue",Helvetica,"Hiragino Sans","Noto Sans CJK JP",Arial,sans-serif;
display:flex;flex-direction:column;justify-content:center;align-items:center;
text-align:center;overflow:hidden;padding:0 8vw;box-sizing:border-box}}
.title{{font-size:5.2vw;margin:0 0 2.4vw;letter-spacing:.04em;font-weight:600;line-height:1.15}}
.body{{font-size:2.3vw;margin:.5vw 0;color:#a8b0c0;letter-spacing:.03em;line-height:1.4}}
</style>
</head>
<body>
<div class="title">{html.escape(card.title)}</div>
{body}
</body>
</html>
"""


# The caption sits in the same lower-third band the film's chapter titles
# use (app.chapter_card), computed from the same public constants so the
# strip lands in the same place on the frame; there is no map to draw here.
_CAPTION_BAND_TOP_VW = (100 - 100 * CARD_ASPECT_DENOMINATOR / CARD_ASPECT_NUMERATOR) / 2
_CAPTION_BAND_HEIGHT_VW = 100 * CARD_ASPECT_DENOMINATOR / CARD_ASPECT_NUMERATOR
_CAPTION_STRIP_HEIGHT_VW = _CAPTION_BAND_HEIGHT_VW * LOWER_THIRD_HEIGHT_SHARE

_CAPTION_STYLE = f"""
html,body{{margin:0;padding:0}}
body{{width:100vw;height:100vh;background:#000;color:#fff;position:relative;
font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;overflow:hidden}}
.band{{position:absolute;left:0;top:{_CAPTION_BAND_TOP_VW:.4f}vw;width:100vw;
height:{_CAPTION_BAND_HEIGHT_VW:.4f}vw}}
.strip{{position:absolute;left:0;bottom:0;width:100vw;height:{_CAPTION_STRIP_HEIGHT_VW:.4f}vw;
box-sizing:border-box;padding:0 4vw;display:flex;align-items:center}}
.text{{display:flex;flex-direction:column;gap:.9vw;text-align:left}}
.title{{font-size:3.6vw;font-weight:700;letter-spacing:.06em;line-height:1.1;margin:0}}
.body{{font-size:1.9vw;color:#d7dde9;letter-spacing:.04em;margin:.4vw 0 0}}
"""


def caption_html(title: str, lines: tuple[str, ...]) -> str:
    """A caption held over the lower third of playing footage, not a full screen."""
    body = "".join(f'<div class="body">{html.escape(line)}</div>' for line in lines)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>{_CAPTION_STYLE}</style>
</head>
<body>
<div class="band"><div class="strip">
<div class="text"><div class="title">{html.escape(title)}</div>
{body}</div>
</div></div>
</body>
</html>
"""


# The five narrated stretches (key, duration_s, caption_hold_s, title, lines),
# cut back to back from one place in the film so reviewing them for faces and
# plates is one contiguous look, not five scattered ones. `caption_hold_s`
# is `None` except for the close, which lets the last stretch play out under
# its own footage once the caption has said its piece.
_NARRATED_EXCERPTS: tuple[tuple[str, float, float | None, str, tuple[str, ...]], ...] = (
    (
        "problem",
        20.0,
        None,
        "One day, 68 gigabytes of video.",
        ("Somewhere in it is a story worth watching.",),
    ),
    (
        "evidence",
        25.0,
        None,
        "The track gives the day its shape.",
        ("Each leg — halt to halt — is a chapter that says where it went from and to.",),
    ),
    (
        "clock",
        20.0,
        None,
        "One question needs a person.",
        ("The system proposes the clock offset with its evidence; a person confirms it.",),
    ),
    (
        "gemini",
        25.0,
        None,
        "Gemini decides what the film shows.",
        (
            "Every window is judged on a small copy — the 4K source never leaves the machine.",
            "Setting off, each stop, joining the highway: the moments the track proves are kept.",
        ),
    ),
    (
        "close",
        17.0,
        8.0,
        "Telemetry becomes a story.",
        ("The footage that proves it stays on your machine.",),
    ),
)


def demo_timeline(
    console: dict[str, object], *, excerpt_start_s: float, bob_png: Path
) -> tuple[Segment, ...]:
    """The script's timeline, filled from the package's own facts.

    Five stretches of the finished film, cut back to back starting at
    `excerpt_start_s`, carry the narration as a caption over their lower
    third (Q5 -- a demo that opens on cards and closes on fifteen seconds of
    video reads as a slideshow). The console's own figures stay a full-screen
    card, because a caption cannot hold a table of numbers, and the three
    stills (two of the film's own chapter cards, and the evidence gate) stay
    stills. Holds add up to three minutes. The figures come from the console
    payload -- counts, sizes and money -- and nothing else is read to write
    them.
    """
    stages = {str(s["key"]): s for s in console["stages"]}  # type: ignore[index]
    planned = stages["footage_planned"]
    copies = stages["copies_prepared"]
    judged = stages["footage_judged"]
    story = stages.get("story_planned", {})
    beats = story.get("beat_count", 0)
    film_s = float(story.get("total_screen_duration_s", 0.0))

    excerpts: dict[str, CaptionedExcerpt] = {}
    offset = excerpt_start_s
    for key, duration_s, caption_hold_s, title, lines in _NARRATED_EXCERPTS:
        excerpts[key] = CaptionedExcerpt(key, offset, duration_s, title, lines, caption_hold_s)
        offset += duration_s

    return (
        excerpts["problem"],
        excerpts["evidence"],
        excerpts["clock"],
        Still("chapter-a", bob_png.parent / "_chapter_a.png", 15.0),
        Still("chapter-b", bob_png.parent / "_chapter_b.png", 15.0),
        Card(
            "console",
            "From there it is one page.",
            (
                f"{planned['candidate_count']} footage windows · "
                f"{planned['upload_megabytes']} MB to send · "
                f"¥{planned['cost_jpy']} (ceiling ¥{planned['budget_jpy']})",
                f"Copies made {copies['prepared_count']} / "
                f"{copies.get('wanted_count', copies['prepared_count'])} · "
                f"Judged {judged['judged_count']} / "
                f"{judged.get('wanted_count', judged['judged_count'])}",
                "Buying the judgement starts only when that exact figure is typed back.",
                f"Story planned: {beats} beats, {film_s:.0f} s. Film cut. Music added.",
            ),
            25.0,
        ),
        excerpts["gemini"],
        Still("bob", bob_png, 15.0),
        excerpts["close"],
    )


def demo_subtitles(segments: tuple[Segment, ...]) -> str:
    """The demo's own subtitles, written from the timeline it is cut from.

    A hand-timed subtitle file drifts the moment a hold changes, and a demo
    whose captions and subtitles disagree is worse than one with neither.
    Every cue here is the text already on screen, timed by the same holds
    the segments are cut to, so the two cannot come apart.
    """
    cues: list[str] = []
    at = 0.0
    for segment in segments:
        length = (
            segment.duration_s
            if isinstance(segment, Excerpt | CaptionedExcerpt)
            else segment.hold_s
        )
        lines = _spoken(segment)
        if lines:
            cues.append((at, at + length, lines))  # type: ignore[arg-type]
        at += length
    return "".join(
        f"{index}\n{_stamp(start)} --> {_stamp(end)}\n" + "\n".join(lines) + "\n\n"
        for index, (start, end, lines) in enumerate(cues, start=1)
    )


def _spoken(segment: Segment) -> tuple[str, ...]:
    """What a segment says on screen, as subtitle lines."""
    if isinstance(segment, CaptionedExcerpt | Card):
        return (segment.title, *segment.lines)
    return ()


def _stamp(seconds: float) -> str:
    whole = int(seconds)
    milliseconds = int(round((seconds - whole) * 1000))
    hours, rest = divmod(whole, 3600)
    minutes, second = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{second:02d},{milliseconds:03d}"


def timeline_duration_s(segments: tuple[Segment, ...]) -> float:
    total = 0.0
    for segment in segments:
        is_footage = isinstance(segment, (Excerpt, CaptionedExcerpt))
        total += segment.duration_s if is_footage else segment.hold_s
    return total


def assert_no_private_text(segments: tuple[Segment, ...], forbidden: tuple[str, ...]) -> None:
    """Nothing a card or caption says may name a file, a path, a place or a time."""
    for segment in segments:
        if not isinstance(segment, (Card, CaptionedExcerpt)):
            continue
        text = " ".join((segment.title, *segment.lines))
        for needle in forbidden:
            if needle and needle in text:
                raise DemoAssemblyError("a card would show something private")
        # "173 / 173" is a ratio; "/Users/..." or "a/b.mp4" is a path.
        if re.search(r"/\S", text):
            raise DemoAssemblyError("a card would show a path")


# --- rendering ------------------------------------------------------------------


def _run(command: tuple[str, ...], *, runner: Runner, what: str) -> None:
    try:
        result = runner(list(command), capture_output=True, text=True, check=False)
    except OSError as error:
        raise DemoAssemblyError(f"{what} could not be started") from error
    if result.returncode != 0:
        raise DemoAssemblyError(f"{what} failed")


def rasterise_card(
    card: Card,
    work: Path,
    *,
    rasteriser: CardRasteriser = QUICK_LOOK,
    runner: Runner = subprocess.run,
) -> Path:
    html_path = work / f"{card.key}.html"
    html_path.write_text(card_html(card), encoding="utf-8")
    _run(
        rasteriser.command(html_path, work, size=CARD_RASTER_SIZE),
        runner=runner,
        what="card raster",
    )
    png = rasteriser.output_path(html_path, work)
    if not png.is_file():
        raise DemoAssemblyError("the card was not drawn")
    return png


def rasterise_caption(
    segment: CaptionedExcerpt,
    work: Path,
    *,
    rasteriser: CardRasteriser = QUICK_LOOK,
    runner: Runner = subprocess.run,
) -> Path:
    """Draw a caption's HTML the same way a card is drawn -- square, then cropped later."""
    html_path = work / f"{segment.key}-caption.html"
    html_path.write_text(caption_html(segment.title, segment.lines), encoding="utf-8")
    _run(
        rasteriser.command(html_path, work, size=CARD_RASTER_SIZE),
        runner=runner,
        what="caption raster",
    )
    png = rasteriser.output_path(html_path, work)
    if not png.is_file():
        raise DemoAssemblyError("the caption was not drawn")
    return png


def still_segment_command(png: Path, hold_s: float, output: Path) -> tuple[str, ...]:
    """A square or wide image, centred and cropped to the frame, with silence."""
    return (
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-loop",
        "1",
        "-t",
        f"{hold_s:.3f}",
        "-i",
        str(png),
        "-f",
        "lavfi",
        "-t",
        f"{hold_s:.3f}",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-vf",
        f"scale={DEMO_WIDTH}:{DEMO_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={DEMO_WIDTH}:{DEMO_HEIGHT},fps={DEMO_FPS},format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        str(output),
    )


def excerpt_segment_command(film: Path, excerpt: Excerpt, output: Path) -> tuple[str, ...]:
    return (
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{excerpt.start_s:.3f}",
        "-t",
        f"{excerpt.duration_s:.3f}",
        "-i",
        str(film),
        "-vf",
        f"scale={DEMO_WIDTH}:{DEMO_HEIGHT},fps={DEMO_FPS},format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(output),
    )


def captioned_excerpt_segment_command(
    film: Path, segment: CaptionedExcerpt, caption_png: Path, output: Path
) -> tuple[str, ...]:
    """Cut the excerpt and lay its caption over the lower third, fading both in and out.

    Mirrors app.story_film's chapter lower third: the caption is drawn on
    black, cropped down to the band and then to the strip, and keyed by
    brightness so only the white text survives; a translucent strip darkens
    the band under it. Both fade in together and, if `caption_hold_s` is
    shorter than the excerpt, fade out and let the footage play on alone --
    `eof_action=pass` on both overlays means once the short caption clip
    ends, the base video passes through unchanged for the rest of the cut.
    """
    strip_height = round(DEMO_HEIGHT * LOWER_THIRD_HEIGHT_SHARE)
    top = DEMO_HEIGHT - strip_height
    hold = f"{segment.hold_s:.3f}"
    fade_out_at = f"{max(0.0, segment.hold_s - LOWER_THIRD_FADE_S):.3f}"
    fades = ",".join(
        (
            f"fade=t=in:st=0:d={LOWER_THIRD_FADE_S}:alpha=1",
            f"fade=t=out:st={fade_out_at}:d={LOWER_THIRD_FADE_S}:alpha=1",
        )
    )
    filter_complex = ";".join(
        (
            f"[0:v]scale={DEMO_WIDTH}:{DEMO_HEIGHT},fps={DEMO_FPS},format=yuv420p[base]",
            f"[1:v]crop=iw:iw*{DEMO_HEIGHT}/{DEMO_WIDTH},"
            f"crop=iw:ih*{LOWER_THIRD_HEIGHT_SHARE:.6f}:0:ih*{1 - LOWER_THIRD_HEIGHT_SHARE:.6f},"
            f"scale={DEMO_WIDTH}:{strip_height},fps={DEMO_FPS},format=rgba,"
            f"colorchannelmixer=aa=0:ar=0.299:ag=0.587:ab=0.114,{fades}[text]",
            f"color=c=black@{LOWER_THIRD_STRIP_OPACITY}:s={DEMO_WIDTH}x{strip_height}:"
            f"r={DEMO_FPS}:d={hold},format=rgba,{fades}[strip]",
            f"[base][strip]overlay=0:{top}:eof_action=pass:repeatlast=0[u]",
            f"[u][text]overlay=0:{top}:eof_action=pass:repeatlast=0[v]",
        )
    )
    return (
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{segment.start_s:.3f}",
        "-t",
        f"{segment.duration_s:.3f}",
        "-i",
        str(film),
        "-loop",
        "1",
        "-t",
        hold,
        "-i",
        str(caption_png),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-shortest",
        str(output),
    )


def concat_command(list_file: Path, output: Path) -> tuple[str, ...]:
    return (
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output),
    )


def assemble_demo(
    package_directory: Path,
    *,
    bob_png: Path,
    subtitles: Path,
    chapter_cards: tuple[Path, Path],
    excerpt_start_s: float,
    film: Path | None = None,
    rasteriser: CardRasteriser = QUICK_LOOK,
    runner: Runner = subprocess.run,
    overwrite: bool = False,
) -> Path:
    """Draw the cards, cut the excerpt, and join them into one file.

    Written beside the package under `demo/`, wholly or not at all: the
    segments are built in a scratch directory and the joined file is moved
    into place only when it is complete.
    """
    # The published demo is cut from the film whose plates are blurred, when
    # one has been made (app.plate_blur); the package's own scored film is the
    # default because most packages are never published.
    film = film if film is not None else package_directory / SCORED_FILM_FILE_NAME
    if not _usable(film):
        raise DemoAssemblyError("the package has no finished film to excerpt")
    for image in (bob_png, *chapter_cards):
        if not image.is_file() or image.is_symlink():
            raise DemoAssemblyError("an image the demo needs is missing")
    if not subtitles.is_file():
        raise DemoAssemblyError("the subtitle file is missing")

    out_dir = package_directory / DEMO_DIRECTORY_NAME
    destination = out_dir / DEMO_FILE_NAME
    if destination.exists() and not overwrite:
        raise FileExistsError("a demo already exists here; pass overwrite=True to replace it")
    out_dir.mkdir(parents=True, exist_ok=True)

    console = PrivateJourneyConsole.from_directory(package_directory).payload()
    work = Path(mkdtemp(dir=out_dir, prefix=".assembling-"))
    try:
        shutil.copy(chapter_cards[0], work / "_chapter_a.png")
        shutil.copy(chapter_cards[1], work / "_chapter_b.png")
        shutil.copy(bob_png, work / bob_png.name)
        segments = demo_timeline(
            console, excerpt_start_s=excerpt_start_s, bob_png=work / bob_png.name
        )
        assert_no_private_text(segments, forbidden=(str(package_directory), package_directory.name))

        parts: list[Path] = []
        for index, segment in enumerate(segments):
            part = work / f"part-{index:02d}.mp4"
            if isinstance(segment, Card):
                png = rasterise_card(segment, work, rasteriser=rasteriser, runner=runner)
                _run(
                    still_segment_command(png, segment.hold_s, part),
                    runner=runner,
                    what="card segment",
                )
            elif isinstance(segment, Still):
                _run(
                    still_segment_command(segment.path, segment.hold_s, part),
                    runner=runner,
                    what="still segment",
                )
            elif isinstance(segment, CaptionedExcerpt):
                png = rasterise_caption(segment, work, rasteriser=rasteriser, runner=runner)
                _run(
                    captioned_excerpt_segment_command(film, segment, png, part),
                    runner=runner,
                    what="captioned excerpt",
                )
            else:
                _run(excerpt_segment_command(film, segment, part), runner=runner, what="excerpt")
            parts.append(part)

        list_file = work / "parts.txt"
        list_file.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        joined = work / DEMO_FILE_NAME
        _run(concat_command(list_file, joined), runner=runner, what="join")
        if not joined.is_file() or joined.stat().st_size == 0:
            raise DemoAssemblyError("the demo was not written")
        os.replace(joined, destination)
        # The subtitles are written from the timeline, so they cannot drift
        # from the captions the demo actually shows.
        (out_dir / subtitles.name).write_text(demo_subtitles(segments), encoding="utf-8")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return destination


def _usable(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def chapter_cards_in(
    directory: Path, first: str | None = None, second: str | None = None
) -> tuple[Path, Path]:
    """Two of the film's own chapter cards: the ones named, or its first and last.

    A day has as many cards as it has chapters, so a fixed pair of names
    fits some packages and not others. Named cards are taken as given;
    otherwise the first and last full card of the package are used, which
    exist for every film with at least two chapters.
    """
    if first and second:
        return (directory / first, directory / second)
    whole = sorted(
        path
        for path in directory.glob("card-*.html.png")
        if not path.is_symlink() and "-f" not in path.name
    )
    if len(whole) < 2:
        raise DemoAssemblyError("the package has fewer than two chapter cards to show")
    return (directory / first if first else whole[0], directory / second if second else whole[-1])


def main(argv: list[str] | None = None) -> None:
    """Assemble the demo for one package; pick a different stretch of film with a flag."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m app.submission.demo_assembly",
        description=(
            "Assemble the three-minute demo locally from a finished package. "
            "Publishes nothing; check the footage for faces and plates before you do."
        ),
    )
    parser.add_argument("package", type=Path, help="a package with a scored film")
    parser.add_argument(
        "--excerpt-start-s",
        type=float,
        default=20.4,
        help="where in the film the five narrated stretches begin, cut back to back",
    )
    parser.add_argument("--chapter-card-a", default=None)
    parser.add_argument("--chapter-card-b", default=None)
    parser.add_argument(
        "--bob-png",
        type=Path,
        default=Path("docs/submission/assets/06-ibm-bob-video-evidence-gate.png"),
    )
    parser.add_argument(
        "--subtitles", type=Path, default=Path("docs/submission/demo-subtitles-en.srt")
    )
    parser.add_argument(
        "--film",
        type=Path,
        default=None,
        help="the film to excerpt; defaults to the package's scored film",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    cards = args.package / "story-cards"
    try:
        # The film first: a package without one cannot be demoed whatever
        # cards it has, and that is the more useful thing to be told.
        if not _usable(args.film or args.package / SCORED_FILM_FILE_NAME):
            raise DemoAssemblyError("the package has no finished film to excerpt")
        chosen = chapter_cards_in(cards, args.chapter_card_a, args.chapter_card_b)
        out = assemble_demo(
            args.package,
            bob_png=args.bob_png,
            subtitles=args.subtitles,
            chapter_cards=chosen,
            excerpt_start_s=args.excerpt_start_s,
            film=args.film,
            overwrite=args.overwrite,
        )
    except (DemoAssemblyError, FileExistsError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(out)


if __name__ == "__main__":
    main()
