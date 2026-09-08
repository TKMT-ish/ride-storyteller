"""Measure what a window looks like, so two alike are not shown in a row.

The owner's first note on the films was monotony: minutes of the same
picture. The selection told windows apart by the model's label for the
road, and a label is not a look -- twenty windows of "highway" can be one
picture or twenty. The research names it the first cause of a boring
touring film: the same view, the same framing, the same subject, again.

The look is read off the copy already made for the judgement, the 480p
one-frame-a-second proxy, with FFmpeg's `signalstats`: the mean luma and
chroma of the frames, and the mean change between consecutive frames.
Four numbers a window -- brightness, two colour axes, motion -- enough to
say that a grey road under a grey sky is not a green valley, and that a
window where the picture barely moves is not one where it flies past.
It is measured once and kept in the package beside the judgement, like
the ranking, because nothing about a window's look changes.

Nothing here judges. It says how far apart two windows look, and the
selection decides what to do with that.
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkstemp

from app.analysis_run import PROXY_DIRECTORY_NAME

WINDOW_LOOK_FILE_NAME = "analysis-look.json"
WINDOW_LOOK_SCHEMA_VERSION = "window-look-v1"

# Below this distance two windows are the same picture. Luma and chroma
# are on 0..1 after dividing by 255; motion by 64, a frame difference
# that on real rides marks the fastest scenery.
LOOK_ALIKE = 0.05

_STAT = re.compile(r"lavfi\.signalstats\.(YAVG|UAVG|VAVG|YDIF)=([-\d.]+)")


class AnalysisLookError(RuntimeError):
    """Raised when a window's look cannot be measured or read."""


@dataclass(frozen=True)
class WindowLook:
    """Brightness, colour and motion of one window, from its proxy."""

    luma: float
    chroma_u: float
    chroma_v: float
    motion: float
    # The frame-to-frame difference second by second, when the look was
    # measured with it kept: what decides which half of a window moves more
    # (E-2, app.story_hold). Empty for a look measured before it was kept.
    motion_series: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        for value in (self.luma, self.chroma_u, self.chroma_v, self.motion):
            if not math.isfinite(value) or value < 0:
                raise ValueError("a look is four finite non-negative numbers")
        for value in self.motion_series:
            if not math.isfinite(value) or value < 0:
                raise ValueError("a motion series is finite non-negative readings")

    @property
    def has_series(self) -> bool:
        return bool(self.motion_series)

    def distance(self, other: WindowLook) -> float:
        return math.sqrt(
            ((self.luma - other.luma) / 255.0) ** 2
            + ((self.chroma_u - other.chroma_u) / 255.0) ** 2
            + ((self.chroma_v - other.chroma_v) / 255.0) ** 2
            + ((self.motion - other.motion) / 64.0) ** 2
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "luma": round(self.luma, 3),
            "chroma_u": round(self.chroma_u, 3),
            "chroma_v": round(self.chroma_v, 3),
            "motion": round(self.motion, 3),
        }
        if self.motion_series:
            payload["motion_series"] = [round(v, 3) for v in self.motion_series]
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> WindowLook:
        series = payload.get("motion_series") or ()
        return cls(
            luma=float(payload["luma"]),  # type: ignore[arg-type]
            chroma_u=float(payload["chroma_u"]),  # type: ignore[arg-type]
            chroma_v=float(payload["chroma_v"]),  # type: ignore[arg-type]
            motion=float(payload["motion"]),  # type: ignore[arg-type]
            motion_series=tuple(float(v) for v in series),  # type: ignore[union-attr]
        )


Runner = Callable[..., subprocess.CompletedProcess[str]]


def measure_look(proxy: Path, *, runner: Runner = subprocess.run) -> WindowLook:
    """Read one proxy's look with FFmpeg. Opens the local copy only."""
    if proxy.is_symlink() or not proxy.is_file():
        raise AnalysisLookError("a window's copy is missing; run preflight first")
    completed = runner(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(proxy),
            "-vf",
            "signalstats,metadata=print:file=-",
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AnalysisLookError("FFmpeg could not read a window's copy")
    series: dict[str, list[float]] = {"YAVG": [], "UAVG": [], "VAVG": [], "YDIF": []}
    for match in _STAT.finditer(completed.stdout):
        series[match.group(1)].append(float(match.group(2)))
    if not series["YAVG"]:
        raise AnalysisLookError("FFmpeg reported no frames for a window's copy")
    # The first frame has nothing before it to differ from.
    motion = series["YDIF"][1:] or series["YDIF"]
    return WindowLook(
        luma=statistics.mean(series["YAVG"]),
        chroma_u=statistics.mean(series["UAVG"]),
        chroma_v=statistics.mean(series["VAVG"]),
        motion=statistics.mean(motion),
        motion_series=tuple(motion),
    )


def looks_for(
    package_directory: Path,
    event_ids: tuple[str, ...],
    *,
    runner: Runner = subprocess.run,
    need_series: bool = False,
) -> dict[str, WindowLook]:
    """The look of every window asked for, measured once and kept in the package.

    With `need_series`, a look kept from before the motion series was
    recorded is measured again, so the caller can rely on every look it
    gets back carrying one.
    """
    path = package_directory / WINDOW_LOOK_FILE_NAME
    known: dict[str, WindowLook] = {}
    if path.exists():
        if path.is_symlink():
            raise AnalysisLookError("the look record path is unsafe")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != WINDOW_LOOK_SCHEMA_VERSION:
            raise AnalysisLookError("unsupported window look schema")
        known = {k: WindowLook.from_dict(v) for k, v in payload.get("looks", {}).items()}
    proxies = package_directory / PROXY_DIRECTORY_NAME
    missing = [
        event_id
        for event_id in event_ids
        if event_id not in known or (need_series and not known[event_id].has_series)
    ]
    for event_id in missing:
        known[event_id] = measure_look(proxies / f"{event_id}.mp4", runner=runner)
    if missing:
        _write(path, known)
    return {event_id: known[event_id] for event_id in event_ids}


def _write(path: Path, looks: Mapping[str, WindowLook]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = mkstemp(dir=path.parent, prefix=".look-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(
                {
                    "schema_version": WINDOW_LOOK_SCHEMA_VERSION,
                    "looks": {k: v.to_dict() for k, v in sorted(looks.items())},
                },
                stream,
                indent=2,
            )
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
