"""Make the small copies of a candidate that get judged, from any recording.

Judging real footage means sending it somewhere, and a ride's own files are
far too large for that: one real day is 68.1 GiB. So each candidate window is
copied down to something small enough to send and still good enough to judge,
here, from whatever the camera actually wrote.

**No proxy is assumed.** GoPro writes an LRV beside each recording, most
cameras do not, and a product that processes other people's rides cannot
depend on one existing. Everything here reads the source file it is given.

Three things make the copy small without making it worse to judge:

- **Frame rate.** Gemini samples video at about one frame per second, so
  encoding at that rate costs nothing in analysis and removes almost all of
  the bytes. Encoding at 30 fps would send thirty times the data to be
  sampled away.
- **Resolution.** At low media resolution a frame is tokenised at a flat 66
  tokens whatever its size, so pixels beyond what makes road and scenery
  legible buy nothing.
- **Audio.** Dropped. It is engine and wind noise, it is charged at 32 tokens
  a second, and nothing in the judgement listens to it.

Stills are cut from the same window for the screening stage, which looks at a
few frames rather than watching the clip (see `app.analysis_budget`).

Everything is local. This module builds and runs FFmpeg commands; it opens no
network client and uploads nothing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

ANALYSIS_PROXY_SCHEMA_VERSION = "analysis-proxy-v1"

# One frame per second: what the model samples anyway.
DEFAULT_PROXY_FPS = 1
# Short side. Enough to read road, sky, and terrain; far below the source.
DEFAULT_PROXY_HEIGHT = 480
# Quality is not the constraint here, size is; this is well above legible.
DEFAULT_PROXY_CRF = 30
DEFAULT_STILL_COUNT = 3


class AnalysisProxyError(RuntimeError):
    """Raised when a candidate cannot be copied down for judging."""


@dataclass(frozen=True)
class AnalysisWindow:
    """One candidate: where it lives, where it starts, and how long it runs."""

    source_path: Path
    start_s: float
    duration_s: float

    def __post_init__(self) -> None:
        if self.start_s < 0:
            raise ValueError("a window cannot start before its recording")
        if self.duration_s <= 0:
            raise ValueError("a window must cover a positive duration")

    def validated_source(self) -> Path:
        if self.source_path.is_symlink() or not self.source_path.is_file():
            raise AnalysisProxyError("the recording to copy from is unavailable")
        return self.source_path


def build_proxy_clip_command(
    window: AnalysisWindow,
    output_path: Path,
    *,
    height: int = DEFAULT_PROXY_HEIGHT,
    fps: int = DEFAULT_PROXY_FPS,
    crf: int = DEFAULT_PROXY_CRF,
) -> tuple[str, ...]:
    """Build the command that copies one window down to a judgeable clip."""
    if height <= 0 or fps <= 0:
        raise AnalysisProxyError("a proxy needs a positive height and frame rate")
    return (
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        # Seeking before the input makes FFmpeg jump rather than decode its
        # way to a window that may be an hour in.
        "-ss",
        f"{window.start_s:.3f}",
        "-t",
        f"{window.duration_s:.3f}",
        "-i",
        str(window.source_path),
        "-vf",
        f"fps={fps},scale=-2:{height}",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    )


def build_still_frames_command(
    window: AnalysisWindow,
    output_pattern: str,
    *,
    count: int = DEFAULT_STILL_COUNT,
    height: int = DEFAULT_PROXY_HEIGHT,
) -> tuple[str, ...]:
    """Build the command that takes a few frames spread across the window.

    The frames are evenly spaced rather than taken from the opening seconds,
    because a candidate's first moment is not representative of it.
    """
    if count <= 0:
        raise AnalysisProxyError("a screening pass needs at least one frame")
    if height <= 0:
        raise AnalysisProxyError("a still needs a positive height")
    spacing = window.duration_s / count
    return (
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{window.start_s:.3f}",
        "-t",
        f"{window.duration_s:.3f}",
        "-i",
        str(window.source_path),
        "-vf",
        f"fps=1/{spacing:.6f},scale=-2:{height}",
        "-frames:v",
        str(count),
        "-an",
        output_pattern,
    )


def write_proxy_clip(
    window: AnalysisWindow,
    output_path: Path,
    *,
    height: int = DEFAULT_PROXY_HEIGHT,
    fps: int = DEFAULT_PROXY_FPS,
    crf: int = DEFAULT_PROXY_CRF,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    """Write one proxy clip, and only put it in place once it is whole."""
    window.validated_source()
    if output_path.is_symlink():
        raise AnalysisProxyError("the proxy output path is unsafe")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial = output_path.with_name(
        f".{output_path.stem}.partial-{os.getpid()}{output_path.suffix}"
    )
    partial.unlink(missing_ok=True)
    command = build_proxy_clip_command(window, partial, height=height, fps=fps, crf=crf)
    _run(command, runner=runner, what="proxy clip")
    if not partial.is_file():
        raise AnalysisProxyError("ffmpeg did not create the expected proxy clip")
    os.replace(partial, output_path)
    return output_path


def write_still_frames(
    window: AnalysisWindow,
    output_directory: Path,
    *,
    count: int = DEFAULT_STILL_COUNT,
    height: int = DEFAULT_PROXY_HEIGHT,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[Path, ...]:
    """Write the screening stills for one window, all of them or none.

    They are written into a scratch directory and moved across together, so a
    failure part-way leaves no half-set that a later stage would mistake for
    a complete one.
    """
    window.validated_source()
    if output_directory.is_symlink():
        raise AnalysisProxyError("the stills output path is unsafe")
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(mkdtemp(dir=output_directory.parent, prefix=".stills-"))
    try:
        command = build_still_frames_command(
            window, str(scratch / "frame-%03d.jpg"), count=count, height=height
        )
        _run(command, runner=runner, what="screening stills")
        frames = sorted(scratch.glob("frame-*.jpg"))
        if len(frames) != count:
            raise AnalysisProxyError("ffmpeg did not produce every screening still")
        if output_directory.exists():
            shutil.rmtree(output_directory)
        os.replace(scratch, output_directory)
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
    return tuple(sorted(output_directory.glob("frame-*.jpg")))


def _run(
    command: tuple[str, ...],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    what: str,
) -> None:
    try:
        completed = runner(command, check=False, capture_output=True, text=True, timeout=300)
    except FileNotFoundError as error:
        raise AnalysisProxyError(f"ffmpeg is required to make the {what}") from error
    except subprocess.TimeoutExpired as error:
        raise AnalysisProxyError(f"making the {what} timed out") from error
    if completed.returncode != 0:
        raise AnalysisProxyError(f"ffmpeg could not make the {what}")
