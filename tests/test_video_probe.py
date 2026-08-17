import json
import subprocess
from pathlib import Path

import pytest

from app.video.probe import (
    LocalVideoMetadata,
    VideoProbeError,
    export_local_video_metadata,
    probe_local_video_metadata,
    write_local_video_metadata,
)


def _ffprobe_payload(**overrides: object) -> str:
    payload: dict[str, object] = {
        "format": {
            "duration": "12.5",
            "tags": {"creation_time": "2026-08-10T01:42:00Z"},
        },
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
                "avg_frame_rate": "60000/1001",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }
    payload.update(overrides)
    return json.dumps(payload)


def _video_path(tmp_path: Path, name: str = "GX010001.MP4") -> Path:
    path = tmp_path / name
    path.write_bytes(b"not read by the fake ffprobe runner")
    return path


def test_probe_reads_local_technical_metadata_without_a_shell(tmp_path: Path) -> None:
    video = _video_path(tmp_path)
    received: dict[str, object] = {}

    def fake_runner(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        received["command"] = command
        received["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, _ffprobe_payload(), "")

    metadata = probe_local_video_metadata(video, runner=fake_runner)

    assert metadata.file_name == "GX010001.MP4"
    assert metadata.duration_s == 12.5
    assert metadata.recorded_start_time is not None
    assert metadata.recorded_start_time.isoformat() == "2026-08-10T01:42:00+00:00"
    assert metadata.video_codec == "hevc"
    assert (metadata.width, metadata.height) == (3840, 2160)
    assert metadata.frames_per_second == pytest.approx(60_000 / 1_001)
    assert metadata.has_audio is True
    assert received["command"][0] == "ffprobe"  # type: ignore[index]
    assert received["kwargs"] == {
        "check": False,
        "capture_output": True,
        "text": True,
        "timeout": 30,
    }


def test_probe_keeps_missing_camera_time_unknown(tmp_path: Path) -> None:
    video = _video_path(tmp_path)

    def fake_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, _ffprobe_payload(format={"duration": "12.5"}), "")

    metadata = probe_local_video_metadata(video, runner=fake_runner)

    assert metadata.recorded_start_time is None


def test_probe_rejects_unsafe_input_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="existing file"):
        probe_local_video_metadata(tmp_path / "missing.mp4")

    unsupported = _video_path(tmp_path, "notes.txt")
    with pytest.raises(ValueError, match="supported video suffix"):
        probe_local_video_metadata(unsupported)


def test_probe_rejects_missing_ffprobe_without_exposing_the_path(tmp_path: Path) -> None:
    video = _video_path(tmp_path)

    def missing_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    with pytest.raises(VideoProbeError, match="ffprobe is required") as error:
        probe_local_video_metadata(video, runner=missing_runner)

    assert str(video) not in str(error.value)


def test_probe_rejects_invalid_or_incomplete_metadata(tmp_path: Path) -> None:
    video = _video_path(tmp_path)

    def invalid_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, "{}", "")

    with pytest.raises(VideoProbeError, match="valid video duration"):
        probe_local_video_metadata(video, runner=invalid_runner)


def test_probe_output_requires_explicit_overwrite(tmp_path: Path) -> None:
    metadata = LocalVideoMetadata(
        file_name="GX010001.MP4",
        duration_s=12.5,
        recorded_start_time=None,
        video_codec="hevc",
        width=3840,
        height=2160,
        frames_per_second=60.0,
        has_audio=True,
    )
    output = tmp_path / "private-media" / "metadata.json"

    payload = json.loads(export_local_video_metadata(metadata))
    assert payload["schema_version"] == "local-video-metadata-v1"
    assert write_local_video_metadata(output, metadata) == output
    with pytest.raises(FileExistsError, match="already exists"):
        write_local_video_metadata(output, metadata)
    assert write_local_video_metadata(output, metadata, overwrite=True) == output
