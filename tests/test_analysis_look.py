"""Tests for reading a window's look off its proxy and keeping it in the package."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.analysis_look import (
    WINDOW_LOOK_FILE_NAME,
    AnalysisLookError,
    WindowLook,
    looks_for,
    measure_look,
)
from app.analysis_run import PROXY_DIRECTORY_NAME


def _ffmpeg_output(frames: list[tuple[float, float, float, float]]) -> str:
    lines = []
    for index, (y, u, v, d) in enumerate(frames):
        lines.append(f"frame:{index} pts:{index} pts_time:{index}")
        lines.append(f"lavfi.signalstats.YAVG={y}")
        lines.append(f"lavfi.signalstats.UAVG={u}")
        lines.append(f"lavfi.signalstats.VAVG={v}")
        lines.append(f"lavfi.signalstats.YDIF={d}")
    return "\n".join(lines) + "\n"


def _runner(stdout: str, returncode: int = 0):
    calls: list[list[str]] = []

    def run(command, **_kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_a_look_is_the_mean_of_the_frames_with_the_first_difference_dropped(tmp_path: Path) -> None:
    proxy = tmp_path / "w.mp4"
    proxy.write_bytes(b"copy")
    run = _runner(_ffmpeg_output([(100, 128, 128, 0), (120, 130, 126, 10), (140, 132, 124, 20)]))

    look = measure_look(proxy, runner=run)

    assert look == WindowLook(
        luma=120.0, chroma_u=130.0, chroma_v=126.0, motion=15.0, motion_series=(10.0, 20.0)
    )
    assert "signalstats" in " ".join(run.calls[0])
    assert str(proxy) in run.calls[0]


def test_a_missing_or_unreadable_copy_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(AnalysisLookError, match="missing"):
        measure_look(tmp_path / "absent.mp4", runner=_runner(""))
    proxy = tmp_path / "w.mp4"
    proxy.write_bytes(b"copy")
    with pytest.raises(AnalysisLookError, match="could not read"):
        measure_look(proxy, runner=_runner("", returncode=1))
    with pytest.raises(AnalysisLookError, match="no frames"):
        measure_look(proxy, runner=_runner("nothing here"))


def test_distance_tells_a_grey_road_from_a_green_valley_and_alike_from_alike() -> None:
    grey = WindowLook(110, 128, 128, 12)
    green = WindowLook(120, 110, 100, 14)
    same = WindowLook(111, 128, 127, 12.5)

    assert grey.distance(green) > 0.1
    assert grey.distance(same) < 0.05
    assert grey.distance(grey) == 0.0


def test_looks_are_measured_once_and_kept_in_the_package(tmp_path: Path) -> None:
    package = tmp_path / "package"
    (package / PROXY_DIRECTORY_NAME).mkdir(parents=True)
    for name in ("a", "b"):
        (package / PROXY_DIRECTORY_NAME / f"{name}.mp4").write_bytes(b"copy")
    run = _runner(_ffmpeg_output([(100, 128, 128, 0), (100, 128, 128, 8)]))

    first = looks_for(package, ("a", "b"), runner=run)
    assert set(first) == {"a", "b"}
    assert len(run.calls) == 2

    written = json.loads((package / WINDOW_LOOK_FILE_NAME).read_text())
    assert written["schema_version"] == "window-look-v1"
    assert set(written["looks"]) == {"a", "b"}

    again = looks_for(package, ("a", "b"), runner=run)
    assert again == first
    assert len(run.calls) == 2, "a kept look is not measured again"


def test_a_look_is_four_finite_non_negative_numbers() -> None:
    with pytest.raises(ValueError):
        WindowLook(-1, 0, 0, 0)
    with pytest.raises(ValueError):
        WindowLook(float("nan"), 0, 0, 0)


def test_a_look_kept_without_its_series_is_measured_again_only_when_asked(tmp_path: Path) -> None:
    import json

    from app.analysis_look import WINDOW_LOOK_FILE_NAME, WINDOW_LOOK_SCHEMA_VERSION, looks_for

    (tmp_path / "analysis-proxies").mkdir()
    (tmp_path / "analysis-proxies" / "w.mp4").write_bytes(b"copy")
    (tmp_path / WINDOW_LOOK_FILE_NAME).write_text(
        json.dumps(
            {
                "schema_version": WINDOW_LOOK_SCHEMA_VERSION,
                "looks": {"w": {"luma": 1.0, "chroma_u": 2.0, "chroma_v": 3.0, "motion": 4.0}},
            }
        ),
        encoding="utf-8",
    )
    run = _runner(_ffmpeg_output([(100, 128, 128, 0), (120, 130, 126, 10), (140, 132, 124, 20)]))

    kept = looks_for(tmp_path, ("w",), runner=run)
    assert kept["w"].motion == 4.0 and not kept["w"].has_series and not run.calls

    fresh = looks_for(tmp_path, ("w",), runner=run, need_series=True)
    assert fresh["w"].motion_series == (10.0, 20.0) and len(run.calls) == 1

    again = looks_for(tmp_path, ("w",), runner=run, need_series=True)
    assert again["w"].motion_series == (10.0, 20.0) and len(run.calls) == 1, "kept this time"


def test_a_motion_series_round_trips_and_must_be_finite() -> None:
    look = WindowLook(luma=1.0, chroma_u=2.0, chroma_v=3.0, motion=4.0, motion_series=(1.0, 7.0))

    assert WindowLook.from_dict(look.to_dict()) == look
    with pytest.raises(ValueError, match="series"):
        WindowLook(luma=1.0, chroma_u=2.0, chroma_v=3.0, motion=4.0, motion_series=(-1.0,))


def test_to_dict_omits_the_series_key_when_there_is_no_series() -> None:
    look = WindowLook(luma=1.0, chroma_u=2.0, chroma_v=3.0, motion=4.0)

    assert "motion_series" not in look.to_dict()


def test_a_single_frame_window_uses_its_own_difference_as_motion(tmp_path: Path) -> None:
    # There is nothing before the first frame to differ from, so the usual
    # "drop the first reading" rule would leave an empty series; a
    # one-frame window falls back to keeping it instead of averaging nothing.
    proxy = tmp_path / "w.mp4"
    proxy.write_bytes(b"copy")
    run = _runner(_ffmpeg_output([(100, 128, 128, 5)]))

    look = measure_look(proxy, runner=run)

    assert look.motion == 5.0
    assert look.motion_series == (5.0,)


def test_a_symlinked_proxy_copy_is_treated_as_missing(tmp_path: Path) -> None:
    real = tmp_path / "real.mp4"
    real.write_bytes(b"copy")
    link = tmp_path / "w.mp4"
    link.symlink_to(real)

    with pytest.raises(AnalysisLookError, match="missing"):
        measure_look(link, runner=_runner(""))


def test_distance_is_symmetric() -> None:
    grey = WindowLook(110, 128, 128, 12)
    green = WindowLook(120, 110, 100, 14)

    assert grey.distance(green) == green.distance(grey)


def test_a_symlinked_look_record_is_refused(tmp_path: Path) -> None:
    package = tmp_path / "package"
    (package / PROXY_DIRECTORY_NAME).mkdir(parents=True)
    real = tmp_path / "elsewhere.json"
    real.write_text(json.dumps({"schema_version": "window-look-v1", "looks": {}}), encoding="utf-8")
    (package / WINDOW_LOOK_FILE_NAME).symlink_to(real)

    with pytest.raises(AnalysisLookError, match="unsafe"):
        looks_for(package, ("a",), runner=_runner(""))


def test_an_unsupported_schema_version_is_refused(tmp_path: Path) -> None:
    package = tmp_path / "package"
    (package / PROXY_DIRECTORY_NAME).mkdir(parents=True)
    (package / WINDOW_LOOK_FILE_NAME).write_text(
        json.dumps({"schema_version": "window-look-v0", "looks": {}}), encoding="utf-8"
    )

    with pytest.raises(AnalysisLookError, match="schema"):
        looks_for(package, ("a",), runner=_runner(""))


def test_asking_for_no_windows_returns_empty_and_writes_nothing(tmp_path: Path) -> None:
    package = tmp_path / "package"
    (package / PROXY_DIRECTORY_NAME).mkdir(parents=True)
    run = _runner("")

    result = looks_for(package, (), runner=run)

    assert result == {}
    assert not run.calls
    assert not (package / WINDOW_LOOK_FILE_NAME).exists()


def test_a_write_failure_leaves_no_temporary_file_behind(tmp_path: Path, monkeypatch) -> None:
    import app.analysis_look as analysis_look

    package = tmp_path / "package"
    (package / PROXY_DIRECTORY_NAME).mkdir(parents=True)
    (package / PROXY_DIRECTORY_NAME / "a.mp4").write_bytes(b"copy")
    run = _runner(_ffmpeg_output([(100, 128, 128, 0), (100, 128, 128, 8)]))

    def _broken_dump(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(analysis_look.json, "dump", _broken_dump)

    with pytest.raises(OSError, match="disk full"):
        looks_for(package, ("a",), runner=run)

    assert not (package / WINDOW_LOOK_FILE_NAME).exists()
    assert list(package.glob(".look-*")) == []
