"""Blur the number plates in footage, and say where a face appears.

The owner's rule (2026-09-08): other people's cars may stay in the film, but
their number plates are blurred, and a window in which a person could be
identified is dropped rather than blurred. This module does the first and
reports what the second needs.

Plates are found by reading the text in sampled frames on this machine
(`app.video.vision_boxes`) and keeping only what is shaped like a plate. That
filter matters: on one real film Vision found 1,031 pieces of text and 17 of
them were plates. Blurring all text would blur every road sign the film is
about.

**This is best effort, not a guarantee.** A plate the reader cannot make out
is a plate that is not blurred, and frames between samples are never looked
at. What it does is remove the plates a viewer could actually read, so that
the last check a person makes is short rather than impossible.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.video.apple_vision import AppleVisionError
from app.video.vision_boxes import (
    FrameBoxes,
    VisionBox,
    build_vision_boxes_probe,
    detect_boxes_in_batches,
)

# A plate is a run of letters beside a run of digits: New Zealand issues three
# letters and three digits, and older ones are two letters and four. Requiring
# the runs to be contiguous is what separates a plate from garbled sign text --
# a film cut from blurred clips still produced "3ta3" and "Esk StI", which a
# looser rule counted as plates and blurred for nothing.
_PLATE = re.compile(r"^(?:[A-Z]{2,3}[ -]?[0-9]{2,4}|[0-9]{2,4}[ -]?[A-Z]{2,3})$")
# Plates are read in capitals. Mixed case is a word, and usually a misread one.
_LOWER = re.compile(r"[a-z]")
# Things shaped like a plate that are not one: distances, speeds, heights.
_UNITS = re.compile(r"(KM|M|KG|T|MPH|KMH|%)$")

# How far round a plate the blur reaches, as a share of the box and as a floor
# in pixels. A plate box hugs the characters; the plate itself is wider.
PAD_SHARE = 0.6
PAD_PIXELS = 12
# A plate seen in one sampled frame is blurred for this long either side, so
# the frames between samples are covered.
HOLD_S = 0.6
# How hard the blur is. Enough that a plate cannot be read at full resolution.
# The radius a region can actually take is bounded by its own size: boxblur
# refuses a radius that reaches past the middle of the chroma plane, which on
# a 4:2:0 stream is a quarter of the region.
BLUR_RADIUS = 12
# A plate box hugs a few characters. Blurring exactly that leaves a legible
# edge and too small a region to blur hard, so every region is at least this.
MIN_BOX_WIDTH = 48
MIN_BOX_HEIGHT = 28
# A face this tall, as a share of the frame, is a face someone could be
# recognised from.
FACE_HEIGHT_SHARE = 0.015
# A window is dropped if a face appears anywhere within this of it.
FACE_MARGIN_S = 1.0
# How the footage is sampled before it is read. Ten frames a second leaves a
# tenth of a second unlooked-at, which the hold above covers; the width is
# what the reader needs, not what the film is.
SAMPLE_FPS = 10.0
SAMPLE_WIDTH = 1280


class PlateBlurError(RuntimeError):
    """Raised when the blur cannot be planned or applied."""


@dataclass(frozen=True)
class Region:
    """A rectangle of video, in pixels from the top left, over a span of time."""

    start_s: float
    end_s: float
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.end_s <= self.start_s:
            raise PlateBlurError("a blurred region must cover a positive time")
        if self.width <= 0 or self.height <= 0:
            raise PlateBlurError("a blurred region must have a positive size")
        if self.x < 0 or self.y < 0:
            raise PlateBlurError("a blurred region must lie inside the frame")

    def overlaps(self, other: Region) -> bool:
        """Whether the two regions share both time and space."""
        if self.end_s < other.start_s or other.end_s < self.start_s:
            return False
        return not (
            self.x + self.width < other.x
            or other.x + other.width < self.x
            or self.y + self.height < other.y
            or other.y + other.height < self.y
        )

    def joined(self, other: Region) -> Region:
        """The region covering both."""
        x = min(self.x, other.x)
        y = min(self.y, other.y)
        return Region(
            start_s=min(self.start_s, other.start_s),
            end_s=max(self.end_s, other.end_s),
            x=x,
            y=y,
            width=max(self.x + self.width, other.x + other.width) - x,
            height=max(self.y + self.height, other.y + other.height) - y,
        )


def looks_like_a_plate(text: str) -> bool:
    """Whether this piece of read text is shaped like a number plate."""
    said = " ".join(text.split())
    if _LOWER.search(said):
        return False
    bare = said.replace(" ", "").replace("-", "")
    if not 4 <= len(bare) <= 8:
        return False
    if not _PLATE.match(said.upper()):
        return False
    return not _UNITS.search(bare.upper())


def as_video_box(
    box: VisionBox,
    *,
    width: int,
    height: int,
    pad_share: float = PAD_SHARE,
    pad_pixels: int = PAD_PIXELS,
) -> tuple[int, int, int, int]:
    """One Vision box as pixels from the top left, padded and clamped to the frame.

    Vision counts from the bottom left and the video counts from the top, so
    the flip happens here, once.
    """
    if width <= 0 or height <= 0:
        raise PlateBlurError("a frame must have a positive size")
    if pad_share < 0 or pad_pixels < 0:
        raise PlateBlurError("the padding cannot be negative")
    left = box.x * width
    top = (1.0 - box.y - box.height) * height
    across = box.width * width
    down = box.height * height
    pad_x = max(across * pad_share, pad_pixels)
    pad_y = max(down * pad_share, pad_pixels)
    x = max(0, int(left - pad_x))
    y = max(0, int(top - pad_y))
    right = min(width, int(left + across + pad_x))
    bottom = min(height, int(top + down + pad_y))
    if right <= x or bottom <= y:
        raise PlateBlurError("a padded box fell outside the frame")
    x, y, right, bottom = _at_least(
        x, y, right, bottom, width=width, height=height, least=(MIN_BOX_WIDTH, MIN_BOX_HEIGHT)
    )
    # Even numbers, because a filter cropping an odd width on a chroma-
    # subsampled stream is a filter that refuses to run.
    return x - x % 2, y - y % 2, (right - x) - (right - x) % 2, (bottom - y) - (bottom - y) % 2


def _at_least(
    x: int,
    y: int,
    right: int,
    bottom: int,
    *,
    width: int,
    height: int,
    least: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Grow a box to a minimum size about its own middle, without leaving the frame."""
    want_across, want_down = min(least[0], width), min(least[1], height)
    if right - x < want_across:
        middle = (x + right) // 2
        x = max(0, min(width - want_across, middle - want_across // 2))
        right = x + want_across
    if bottom - y < want_down:
        middle = (y + bottom) // 2
        y = max(0, min(height - want_down, middle - want_down // 2))
        bottom = y + want_down
    return x, y, right, bottom


def radius_for(region: Region, *, wanted: int = BLUR_RADIUS) -> int:
    """The strongest blur this region can take.

    boxblur refuses a radius that reaches past the middle of a plane, and on a
    4:2:0 stream the chroma planes are half the size of the picture. A quarter
    of the smaller side, less one, is inside both limits.
    """
    room = min(region.width, region.height) // 4 - 1
    return max(1, min(wanted, room))


def plate_regions(
    frames: Sequence[FrameBoxes],
    *,
    fps: float,
    width: int,
    height: int,
    hold_s: float = HOLD_S,
    pad_share: float = PAD_SHARE,
    minimum_hits: int = 1,
) -> tuple[Region, ...]:
    """Every plate seen in the sampled frames, as regions to blur, merged.

    A plate seen in one frame is blurred for `hold_s` either side of it, which
    covers the frames nobody looked at. Regions that share time and space
    become one, so a plate crossing the frame is a single widening box rather
    than a flicker of small ones.

    `minimum_hits` asks for a region to have been seen that many times before
    it counts. Blurring wants one: a plate read once is a plate. **Checking**
    wants two, because a single frame's read that does not reproduce is the
    reader's noise, and a check that counts it never reports a clean film.
    """
    if fps <= 0:
        raise PlateBlurError("the sampling rate must be positive")
    if hold_s <= 0:
        raise PlateBlurError("the hold must be positive")
    found: list[Region] = []
    for frame in frames:
        at = frame.index / fps
        for box in frame.text:
            if not looks_like_a_plate(box.text):
                continue
            x, y, across, down = as_video_box(box, width=width, height=height, pad_share=pad_share)
            found.append(
                Region(
                    start_s=max(0.0, at - hold_s),
                    end_s=at + hold_s,
                    x=x,
                    y=y,
                    width=across,
                    height=down,
                )
            )
    return _merged(found, minimum_hits=minimum_hits)


def _merged(regions: list[Region], *, minimum_hits: int = 1) -> tuple[Region, ...]:
    """Regions sharing time and space folded together until none do."""
    kept: list[Region] = []
    hits: list[int] = []
    for region in sorted(regions, key=lambda r: (r.start_s, r.x)):
        for index, already in enumerate(kept):
            if already.overlaps(region):
                kept[index] = already.joined(region)
                hits[index] += 1
                break
        else:
            kept.append(region)
            hits.append(1)
    enough = [region for region, seen in zip(kept, hits, strict=True) if seen >= minimum_hits]
    return tuple(sorted(enough, key=lambda r: r.start_s))


def face_seconds(
    frames: Sequence[FrameBoxes],
    *,
    fps: float,
    minimum_height: float = FACE_HEIGHT_SHARE,
) -> tuple[float, ...]:
    """The moments a face big enough to recognise appears, in ride order."""
    if fps <= 0:
        raise PlateBlurError("the sampling rate must be positive")
    return tuple(
        frame.index / fps
        for frame in frames
        if any(face.height >= minimum_height for face in frame.faces)
    )


def clear_of_faces(
    frames: Sequence[FrameBoxes],
    *,
    fps: float,
    length_s: float,
    total_s: float,
    minimum_height: float = FACE_HEIGHT_SHARE,
    margin_s: float = FACE_MARGIN_S,
) -> tuple[tuple[float, float], ...]:
    """The stretches of at least `length_s` in which no face appears.

    Used to choose what to publish: the owner's rule is to drop the footage
    rather than blur the person, so the excerpt is taken from between them.
    """
    if length_s <= 0 or total_s <= 0:
        raise PlateBlurError("the stretch and the whole must be positive")
    seen = face_seconds(frames, fps=fps, minimum_height=minimum_height)
    spans: list[tuple[float, float]] = []
    start = 0.0
    for at in (*seen, total_s):
        end = at - margin_s if at < total_s else total_s
        if end - start >= length_s:
            spans.append((start, end))
        start = max(start, at + margin_s)
    return tuple(spans)


def blur_filter(regions: Sequence[Region], *, radius: int = BLUR_RADIUS) -> str:
    """The ffmpeg filter graph that blurs each region while it is on screen.

    A blur that covers part of the picture is a crop, a blur and an overlay;
    `boxblur` alone would take the whole frame. The overlay is switched on
    only for the region's own seconds, so nothing else in the film softens.
    """
    if radius < 1:
        raise PlateBlurError("the blur radius must be at least one pixel")
    if not regions:
        return ""
    parts = [
        f"[0:v]split={len(regions) + 1}" + "".join(f"[base{i}]" for i in range(len(regions) + 1))
    ]
    current = "base0"
    for index, region in enumerate(regions):
        source = f"base{index + 1}"
        parts.append(
            f"[{source}]crop={region.width}:{region.height}:{region.x}:{region.y},"
            f"boxblur={radius_for(region, wanted=radius)}:2[blur{index}]"
        )
        out = f"over{index}"
        parts.append(
            f"[{current}][blur{index}]overlay={region.x}:{region.y}:"
            f"enable='between(t,{region.start_s:.3f},{region.end_s:.3f})'[{out}]"
        )
        current = out
    return ";".join(parts) + f";[{current}]null[out]"


def blur_command(
    source: Path,
    output: Path,
    regions: Sequence[Region],
    *,
    radius: int = BLUR_RADIUS,
    crf: int = 18,
) -> tuple[str, ...]:
    """The one command that writes the blurred copy, audio carried across untouched."""
    graph = blur_filter(regions, radius=radius)
    if not graph:
        return (
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-c", "copy", str(output),
        )  # fmt: skip
    return (
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-filter_complex", graph,
        "-map", "[out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-c:a", "copy",
        str(output),
    )  # fmt: skip


def blur_plates(
    source: Path,
    output: Path,
    regions: Sequence[Region],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    radius: int = BLUR_RADIUS,
) -> Path:
    """Write the blurred copy beside its destination, wholly or not at all."""
    if not source.is_file() or source.is_symlink():
        raise PlateBlurError("the footage to blur is unavailable")
    # The part file keeps the real suffix: ffmpeg picks its container from the
    # name, and ".mp4.part" is a container it has never heard of.
    temporary = output.with_name(f"{output.stem}.part{output.suffix}")
    command = blur_command(source, temporary, regions, radius=radius)
    try:
        completed = runner(command, check=False, capture_output=True, text=True)
    except (FileNotFoundError, OSError) as error:
        temporary.unlink(missing_ok=True)
        raise PlateBlurError("ffmpeg could not run") from error
    if completed.returncode != 0 or not temporary.is_file():
        temporary.unlink(missing_ok=True)
        raise PlateBlurError("ffmpeg could not write the blurred copy")
    temporary.replace(output)
    return output


def sample_command(source: Path, directory: Path, *, fps: float, width: int) -> tuple[str, ...]:
    """The command that writes the frames Vision will read."""
    if fps <= 0 or width <= 0:
        raise PlateBlurError("the sampling rate and width must be positive")
    return (
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-vf", f"fps={fps},scale={width}:-2",
        "-q:v", "3",
        str(directory / "f%06d.jpg"),
    )  # fmt: skip


def video_size(
    source: Path, *, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
) -> tuple[int, int]:
    """How big the picture is, asked of ffprobe."""
    command = (
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(source),
    )  # fmt: skip
    try:
        completed = runner(command, check=False, capture_output=True, text=True)
    except (FileNotFoundError, OSError) as error:
        raise PlateBlurError("ffprobe could not run") from error
    if completed.returncode != 0:
        raise PlateBlurError("ffprobe could not read the footage")
    try:
        across, down = completed.stdout.strip().splitlines()[0].split("x")
        return int(across), int(down)
    except (IndexError, ValueError) as error:
        raise PlateBlurError("ffprobe did not report a picture size") from error


def inspect_footage(
    source: Path,
    *,
    probe_path: Path,
    work: Path,
    fps: float = SAMPLE_FPS,
    sample_width: int = SAMPLE_WIDTH,
    minimum_hits: int = 1,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[tuple[Region, ...], tuple[float, ...]]:
    """Sample the footage, read it on this machine, and say what has to change.

    Returns the plate regions to blur and the moments a face appears. The
    frames are written under `work`, which the caller owns and should remove:
    they are stills of private footage.
    """
    work.mkdir(parents=True, exist_ok=True)
    width, height = video_size(source, runner=runner)
    completed = runner(
        sample_command(source, work, fps=fps, width=sample_width),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise PlateBlurError("the frames to inspect could not be written")
    frames = sorted(path for path in work.glob("f*.jpg") if path.is_file())
    if not frames:
        raise PlateBlurError("the footage produced no frames to inspect")
    found = detect_boxes_in_batches(frames, probe_path, runner=runner)
    regions = plate_regions(found, fps=fps, width=width, height=height, minimum_hits=minimum_hits)
    return regions, face_seconds(found, fps=fps)


def blur_until_clean(
    source: Path,
    output: Path,
    *,
    probe_path: Path,
    work: Path,
    fps: float = SAMPLE_FPS,
    passes: int = 4,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[tuple[Region, ...], tuple[float, ...]]:
    """Blur, look again, and blur the original with everything found so far.

    A re-encode moves pixels slightly, and a reader that missed a plate in one
    encode can read it in the next. Iterating on the blurred copy would
    re-encode the film once per pass and lose a little each time, so every
    pass instead applies the regions found so far to the **original**: one
    encode from the source, whatever the pass number. It stops when a pass
    finds nothing new, or after `passes`.

    Returns the regions applied and the face moments seen in the source.
    """
    if passes < 1:
        raise PlateBlurError("there must be at least one pass")
    found, faces = inspect_footage(source, probe_path=probe_path, work=work, fps=fps, runner=runner)
    regions = list(found)
    blur_plates(source, output, regions, runner=runner)
    for _ in range(passes - 1):
        again, _ = inspect_footage(output, probe_path=probe_path, work=work, fps=fps, runner=runner)
        if not again:
            break
        regions = list(_merged([*regions, *again]))
        blur_plates(source, output, regions, runner=runner)
    return tuple(regions), faces


def main(argv: list[str] | None = None) -> int:
    """Blur the plates in one file, and refuse it outright when a face appears."""
    import argparse
    import shutil
    from tempfile import mkdtemp

    parser = argparse.ArgumentParser(
        prog="python -m app.plate_blur",
        description=(
            "Blur the number plates in a video, on this machine. Reports where faces "
            "appear rather than blurring them: the owner's rule is to drop that footage."
        ),
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--fps", type=float, default=SAMPLE_FPS)
    parser.add_argument(
        "--passes",
        type=int,
        default=4,
        help="look again at the blurred copy this many times, blurring the original each time",
    )
    parser.add_argument(
        "--allow-faces",
        action="store_true",
        help="write the file even though a face appears; the faces are still not blurred",
    )
    parser.add_argument(
        "--probe",
        type=Path,
        default=Path("private-media/cache/vision-boxes"),
        help="where the compiled Vision helper lives; it is built if absent",
    )
    args = parser.parse_args(argv)

    try:
        probe = args.probe
        if not probe.is_file():
            build_vision_boxes_probe(probe)
        work = Path(mkdtemp(prefix=".plate-frames-", dir=args.output.parent))
        try:
            if args.passes == 1:
                regions, faces = inspect_footage(
                    args.source, probe_path=probe, work=work, fps=args.fps
                )
                if faces and not args.allow_faces:
                    _refuse(faces)
                blur_plates(args.source, args.output, regions)
            else:
                looked, faces = inspect_footage(
                    args.source, probe_path=probe, work=work, fps=args.fps
                )
                if faces and not args.allow_faces:
                    _refuse(faces)
                del looked
                regions, faces = blur_until_clean(
                    args.source,
                    args.output,
                    probe_path=probe,
                    work=work,
                    fps=args.fps,
                    passes=args.passes,
                )
        finally:
            shutil.rmtree(work, ignore_errors=True)
    except (PlateBlurError, AppleVisionError) as error:
        print(f"plate blur failed: {error}", file=sys.stderr)
        return 1
    print(f"{args.output}: {len(regions)} plate regions blurred, {len(faces)} face frames seen")
    return 0


def _refuse(faces: Sequence[float]) -> None:
    first = ", ".join(f"{at:.1f}s" for at in faces[:8])
    raise PlateBlurError(f"a face appears at {first}; this footage is not to be published")


__all__ = [
    "PlateBlurError",
    "blur_until_clean",
    "inspect_footage",
    "main",
    "Region",
    "as_video_box",
    "blur_command",
    "blur_filter",
    "blur_plates",
    "radius_for",
    "clear_of_faces",
    "face_seconds",
    "looks_like_a_plate",
    "plate_regions",
    "sample_command",
    "video_size",
]


if __name__ == "__main__":
    raise SystemExit(main())
