"""Synthetic-fixture tests for the small copies that get judged."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.analysis_proxy import (
    DEFAULT_PROXY_FPS,
    DEFAULT_PROXY_HEIGHT,
    AnalysisProxyError,
    AnalysisWindow,
    build_proxy_clip_command,
    build_still_frames_command,
    write_proxy_clip,
    write_still_frames,
)


def _window(tmp_path: Path, *, start_s: float = 3_600.0, duration_s: float = 12.0):
    source = tmp_path / "GH010001.MP4"
    source.write_bytes(b"a recording")
    return AnalysisWindow(source_path=source, start_s=start_s, duration_s=duration_s)


def _ok(*_args, **_kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=0, stdout="", stderr="")


# --- what the commands ask for ----------------------------------------------


def test_the_proxy_is_cut_from_the_window_not_the_whole_recording(tmp_path: Path) -> None:
    command = build_proxy_clip_command(_window(tmp_path), tmp_path / "proxy.mp4")

    # Seeking before the input makes FFmpeg jump rather than decode its way in.
    assert command.index("-ss") < command.index("-i")
    assert command[command.index("-ss") + 1] == "3600.000"
    assert command[command.index("-t") + 1] == "12.000"


def test_the_proxy_is_encoded_at_the_rate_the_model_samples(tmp_path: Path) -> None:
    """Thirty frames a second would send thirty times the data to be sampled away."""
    command = build_proxy_clip_command(_window(tmp_path), tmp_path / "proxy.mp4")
    filters = command[command.index("-vf") + 1]

    assert f"fps={DEFAULT_PROXY_FPS}" in filters
    assert DEFAULT_PROXY_FPS == 1


def test_the_proxy_is_scaled_down_and_silent(tmp_path: Path) -> None:
    command = build_proxy_clip_command(_window(tmp_path), tmp_path / "proxy.mp4")
    filters = command[command.index("-vf") + 1]

    assert f"scale=-2:{DEFAULT_PROXY_HEIGHT}" in filters
    # Audio is engine noise, is charged by the second, and nothing listens.
    assert "-an" in command


def test_stills_are_spread_across_the_window(tmp_path: Path) -> None:
    """A candidate's first moment is not representative of it."""
    command = build_still_frames_command(
        _window(tmp_path, duration_s=12.0), str(tmp_path / "frame-%03d.jpg"), count=3
    )
    filters = command[command.index("-vf") + 1]

    # One frame every four seconds across a twelve-second window.
    assert "fps=1/4.000000" in filters
    assert command[command.index("-frames:v") + 1] == "3"


def test_no_proxy_file_is_looked_for_anywhere(tmp_path: Path) -> None:
    """The point of this module: it reads the recording the camera wrote."""
    source = tmp_path / "GH010001.MP4"
    source.write_bytes(b"a recording")
    window = AnalysisWindow(source_path=source, start_s=0.0, duration_s=12.0)

    command = build_proxy_clip_command(window, tmp_path / "proxy.mp4")

    assert command[command.index("-i") + 1] == str(source)
    assert not any(".lrv" in part.lower() for part in command)


def test_impossible_windows_and_sizes_are_refused(tmp_path: Path) -> None:
    source = tmp_path / "a.mp4"
    source.write_bytes(b"x")

    with pytest.raises(ValueError, match="before its recording"):
        AnalysisWindow(source_path=source, start_s=-1.0, duration_s=12.0)
    with pytest.raises(ValueError, match="positive duration"):
        AnalysisWindow(source_path=source, start_s=0.0, duration_s=0.0)
    with pytest.raises(AnalysisProxyError, match="positive height and frame rate"):
        build_proxy_clip_command(_window(tmp_path), tmp_path / "p.mp4", fps=0)
    with pytest.raises(AnalysisProxyError, match="at least one frame"):
        build_still_frames_command(_window(tmp_path), "f-%03d.jpg", count=0)


# --- running them -----------------------------------------------------------


def test_a_written_proxy_lands_only_when_whole(tmp_path: Path) -> None:
    window = _window(tmp_path)
    output = tmp_path / "out" / "proxy.mp4"

    def runner(command, **_kwargs) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"proxy")
        return _ok()

    assert write_proxy_clip(window, output, runner=runner) == output
    assert output.is_file()
    assert list(output.parent.glob(".*partial*")) == []


def test_an_interrupted_proxy_leaves_nothing_behind(tmp_path: Path) -> None:
    window = _window(tmp_path)
    output = tmp_path / "proxy.mp4"

    def dying(command, **_kwargs) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"half")
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=1.0)

    with pytest.raises(AnalysisProxyError, match="timed out"):
        write_proxy_clip(window, output, runner=dying)

    assert not output.exists()


def test_a_missing_recording_stops_before_ffmpeg(tmp_path: Path) -> None:
    window = AnalysisWindow(source_path=tmp_path / "gone.mp4", start_s=0.0, duration_s=12.0)

    with pytest.raises(AnalysisProxyError, match="recording to copy from is unavailable"):
        write_proxy_clip(window, tmp_path / "proxy.mp4", runner=_ok)


def test_a_symlinked_recording_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real.mp4"
    real.write_bytes(b"x")
    link = tmp_path / "link.mp4"
    link.symlink_to(real)
    window = AnalysisWindow(source_path=link, start_s=0.0, duration_s=12.0)

    with pytest.raises(AnalysisProxyError, match="unavailable"):
        write_proxy_clip(window, tmp_path / "proxy.mp4", runner=_ok)


def test_stills_arrive_all_together_or_not_at_all(tmp_path: Path) -> None:
    window = _window(tmp_path)
    directory = tmp_path / "stills"

    def runner(command, **_kwargs) -> subprocess.CompletedProcess[str]:
        pattern = Path(command[-1])
        for index in range(1, 4):
            pattern.with_name(f"frame-{index:03d}.jpg").write_bytes(b"jpg")
        return _ok()

    frames = write_still_frames(window, directory, count=3, runner=runner)

    assert len(frames) == 3
    assert all(frame.parent == directory for frame in frames)


def test_a_short_set_of_stills_is_refused_rather_than_kept(tmp_path: Path) -> None:
    """A half-set would be mistaken for a complete one by the screening stage."""
    window = _window(tmp_path)
    directory = tmp_path / "stills"

    def stingy(command, **_kwargs) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).with_name("frame-001.jpg").write_bytes(b"jpg")
        return _ok()

    with pytest.raises(AnalysisProxyError, match="every screening still"):
        write_still_frames(window, directory, count=3, runner=stingy)

    assert not directory.exists()
    assert list(tmp_path.glob(".stills-*")) == []


def test_a_missing_ffmpeg_is_reported_plainly(tmp_path: Path) -> None:
    def absent(*_args, **_kwargs):
        raise FileNotFoundError("ffmpeg")

    with pytest.raises(AnalysisProxyError, match="ffmpeg is required"):
        write_proxy_clip(_window(tmp_path), tmp_path / "p.mp4", runner=absent)


def test_a_failed_run_is_reported(tmp_path: Path) -> None:
    def failing(*_args, **_kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=(), returncode=1, stdout="", stderr="bad")

    with pytest.raises(AnalysisProxyError, match="could not make"):
        write_proxy_clip(_window(tmp_path), tmp_path / "p.mp4", runner=failing)
