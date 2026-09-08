"""Where text and faces are in an image, found on this machine by Apple Vision.

The film publishes real footage of public roads. Two things have to be found
in it before it can be published (the owner's rule, 2026-09-08): number
plates, which are blurred, and faces, whose windows are dropped. Both come
from the same on-device pass, over frames already written to a private
directory. Nothing is uploaded, and nothing here decides what a plate is:
this reports boxes and the text inside them, and `app.plate_blur` judges.

Coordinates are Vision's own, normalised to the image with the origin at the
**bottom** left. Video filters count from the top, so a caller drawing on a
frame has to flip y. `app.plate_blur.as_video_box` does that once.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.video.apple_vision import AppleVisionError, build_apple_vision_probe

VISION_BOXES_SOURCE = Path("tools/apple_vision_boxes.m")
# Vision is asked about this many frames per process. The helper holds every
# answer in memory before printing, so a whole film at once is a large string
# for no gain; a few hundred keeps each run short and its output small.
DEFAULT_BATCH = 200

__all__ = [
    "VISION_BOXES_SOURCE",
    "FrameBoxes",
    "VisionBox",
    "build_vision_boxes_probe",
    "detect_boxes",
    "detect_boxes_in_batches",
    "parse_vision_boxes",
]


@dataclass(frozen=True)
class VisionBox:
    """One box Vision found, in its own bottom-left normalised coordinates."""

    x: float
    y: float
    width: float
    height: float
    confidence: float = 0.0
    text: str = ""

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise AppleVisionError("a Vision box must have a positive size")
        if not 0.0 <= self.confidence <= 1.0:
            raise AppleVisionError("a Vision confidence must be between zero and one")


@dataclass(frozen=True)
class FrameBoxes:
    """What Vision found in one frame."""

    index: int
    text: tuple[VisionBox, ...] = ()
    faces: tuple[VisionBox, ...] = ()

    def __post_init__(self) -> None:
        if self.index < 0:
            raise AppleVisionError("a frame index cannot be negative")


def build_vision_boxes_probe(
    output_path: Path,
    *,
    source_path: Path = VISION_BOXES_SOURCE,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    """Compile the boxes helper into a private cache, the way the probe is built."""
    return build_apple_vision_probe(source_path, output_path, runner=runner)


def parse_vision_boxes(raw: str) -> tuple[FrameBoxes, ...]:
    """The helper's JSON, refused rather than guessed at when it is not what it claims."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise AppleVisionError("Vision boxes did not come back as JSON") from error
    if not isinstance(payload, list):
        raise AppleVisionError("Vision boxes must be a list of frames")
    frames: list[FrameBoxes] = []
    for item in payload:
        if not isinstance(item, Mapping):
            raise AppleVisionError("a Vision frame must be an object")
        try:
            frames.append(
                FrameBoxes(
                    index=int(item["index"]),
                    text=tuple(_box(entry) for entry in item.get("text", ())),
                    faces=tuple(_box(entry) for entry in item.get("faces", ())),
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AppleVisionError("a Vision frame is malformed") from error
    return tuple(frames)


def _box(entry: object) -> VisionBox:
    if not isinstance(entry, Mapping):
        raise AppleVisionError("a Vision box must be an object")
    return VisionBox(
        x=float(entry["x"]),
        y=float(entry["y"]),
        width=float(entry["width"]),
        height=float(entry["height"]),
        confidence=float(entry.get("confidence", 0.0)),
        text=str(entry.get("text", "")),
    )


def detect_boxes(
    image_paths: Sequence[Path],
    probe_path: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout_s: float = 600.0,
) -> tuple[FrameBoxes, ...]:
    """Ask Vision about these images, in one run, in the order given."""
    if not image_paths:
        return ()
    if not probe_path.is_file() or probe_path.is_symlink():
        raise AppleVisionError("the Vision boxes helper is unavailable")
    command = (str(probe_path), *(str(path) for path in image_paths))
    try:
        completed = runner(command, check=False, capture_output=True, text=True, timeout=timeout_s)
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise AppleVisionError("the Vision boxes helper could not run") from error
    if completed.returncode != 0:
        raise AppleVisionError("the Vision boxes helper failed")
    frames = parse_vision_boxes(completed.stdout)
    if len(frames) != len(image_paths):
        raise AppleVisionError("Vision answered about a different number of images")
    return frames


def detect_boxes_in_batches(
    image_paths: Sequence[Path],
    probe_path: Path,
    *,
    batch: int = DEFAULT_BATCH,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout_s: float = 600.0,
) -> tuple[FrameBoxes, ...]:
    """The same, in runs of `batch`, with the frame index counted across them all."""
    if batch < 1:
        raise AppleVisionError("a Vision batch must hold at least one image")
    found: list[FrameBoxes] = []
    for start in range(0, len(image_paths), batch):
        chunk = image_paths[start : start + batch]
        for frame in detect_boxes(chunk, probe_path, runner=runner, timeout_s=timeout_s):
            found.append(FrameBoxes(index=start + frame.index, text=frame.text, faces=frame.faces))
    return tuple(found)
