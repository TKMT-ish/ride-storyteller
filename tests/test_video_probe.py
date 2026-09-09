import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.video.probe as probe_module
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


def _valid_metadata_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "file_name": "GX010001.MP4",
        "duration_s": 12.5,
        "recorded_start_time": None,
        "video_codec": "hevc",
        "width": 3840,
        "height": 2160,
        "frames_per_second": 60.0,
        "has_audio": True,
    }
    kwargs.update(overrides)
    return kwargs


def test_local_video_metadata_rejects_an_empty_file_name() -> None:
    with pytest.raises(ValueError, match="file_name is required"):
        LocalVideoMetadata(**_valid_metadata_kwargs(file_name=""))


def test_local_video_metadata_rejects_non_positive_duration() -> None:
    with pytest.raises(ValueError, match="duration_s must be positive"):
        LocalVideoMetadata(**_valid_metadata_kwargs(duration_s=0))


def test_local_video_metadata_rejects_a_naive_recorded_start_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        LocalVideoMetadata(
            **_valid_metadata_kwargs(recorded_start_time=datetime(2026, 8, 10, 1, 42, 0))
        )


def test_local_video_metadata_rejects_one_sided_dimensions() -> None:
    with pytest.raises(ValueError, match="both present or both absent"):
        LocalVideoMetadata(**_valid_metadata_kwargs(width=3840, height=None))
    with pytest.raises(ValueError, match="both present or both absent"):
        LocalVideoMetadata(**_valid_metadata_kwargs(width=None, height=2160))


def test_local_video_metadata_rejects_non_positive_dimensions() -> None:
    with pytest.raises(ValueError, match="width and height must be positive"):
        LocalVideoMetadata(**_valid_metadata_kwargs(width=0, height=2160))
    with pytest.raises(ValueError, match="width and height must be positive"):
        LocalVideoMetadata(**_valid_metadata_kwargs(width=3840, height=0))


def test_local_video_metadata_rejects_non_positive_frame_rate() -> None:
    with pytest.raises(ValueError, match="frames_per_second must be positive"):
        LocalVideoMetadata(**_valid_metadata_kwargs(frames_per_second=0))


def test_probe_rejects_a_symlink_input_path(tmp_path: Path) -> None:
    real = _video_path(tmp_path, "real.MP4")
    link = tmp_path / "link.MP4"
    link.symlink_to(real)

    with pytest.raises(ValueError, match="must not be a symlink"):
        probe_local_video_metadata(link)


def test_probe_rejects_a_timeout(tmp_path: Path) -> None:
    video = _video_path(tmp_path)

    def timeout_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=30)

    with pytest.raises(VideoProbeError, match="timed out"):
        probe_local_video_metadata(video, runner=timeout_runner)


def test_probe_rejects_a_nonzero_exit_code(tmp_path: Path) -> None:
    video = _video_path(tmp_path)

    def failing_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 1, "", "no such stream")

    with pytest.raises(VideoProbeError, match="could not read local video metadata"):
        probe_local_video_metadata(video, runner=failing_runner)


def test_probe_rejects_invalid_json_output(tmp_path: Path) -> None:
    video = _video_path(tmp_path)

    def garbled_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, "not json", "")

    with pytest.raises(VideoProbeError, match="invalid metadata"):
        probe_local_video_metadata(video, runner=garbled_runner)


def test_probe_rejects_a_non_positive_duration_string(tmp_path: Path) -> None:
    video = _video_path(tmp_path)

    def zero_duration_runner(
        *_args: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, _ffprobe_payload(format={"duration": "0"}), "")

    with pytest.raises(VideoProbeError, match="valid video duration"):
        probe_local_video_metadata(video, runner=zero_duration_runner)


def test_probe_treats_a_missing_video_stream_as_no_dimensions_or_frame_rate(
    tmp_path: Path,
) -> None:
    video = _video_path(tmp_path)

    def audio_only_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            [],
            0,
            _ffprobe_payload(streams=[{"codec_type": "audio", "codec_name": "aac"}]),
            "",
        )

    metadata = probe_local_video_metadata(video, runner=audio_only_runner)

    assert (metadata.width, metadata.height) == (None, None)
    assert metadata.frames_per_second is None
    assert metadata.video_codec is None
    assert metadata.has_audio is True


def test_probe_rejects_incomplete_video_dimensions(tmp_path: Path) -> None:
    video = _video_path(tmp_path)

    def one_sided_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            [],
            0,
            _ffprobe_payload(streams=[{"codec_type": "video", "width": 1920}]),
            "",
        )

    with pytest.raises(VideoProbeError, match="incomplete video dimensions"):
        probe_local_video_metadata(video, runner=one_sided_runner)


def test_probe_rejects_a_non_numeric_dimension(tmp_path: Path) -> None:
    video = _video_path(tmp_path)

    def bad_width_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            [],
            0,
            _ffprobe_payload(
                streams=[{"codec_type": "video", "width": "abc", "height": 1080}]
            ),
            "",
        )

    with pytest.raises(VideoProbeError, match="invalid video dimensions"):
        probe_local_video_metadata(video, runner=bad_width_runner)


def test_probe_rejects_a_non_positive_dimension(tmp_path: Path) -> None:
    video = _video_path(tmp_path)

    def zero_width_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            [],
            0,
            _ffprobe_payload(streams=[{"codec_type": "video", "width": 0, "height": 1080}]),
            "",
        )

    with pytest.raises(VideoProbeError, match="invalid video dimensions"):
        probe_local_video_metadata(video, runner=zero_width_runner)


def test_probe_rejects_a_non_numeric_frame_rate(tmp_path: Path) -> None:
    video = _video_path(tmp_path)

    def bad_rate_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            [],
            0,
            _ffprobe_payload(
                streams=[
                    {
                        "codec_type": "video",
                        "width": 1920,
                        "height": 1080,
                        "avg_frame_rate": "not-a-rate",
                    }
                ]
            ),
            "",
        )

    with pytest.raises(VideoProbeError, match="invalid frame rate"):
        probe_local_video_metadata(video, runner=bad_rate_runner)


def test_probe_rejects_a_non_positive_frame_rate(tmp_path: Path) -> None:
    video = _video_path(tmp_path)

    def zero_rate_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            [],
            0,
            _ffprobe_payload(
                streams=[
                    {
                        "codec_type": "video",
                        "width": 1920,
                        "height": 1080,
                        "avg_frame_rate": "0/1",
                    }
                ]
            ),
            "",
        )

    with pytest.raises(VideoProbeError, match="invalid frame rate"):
        probe_local_video_metadata(video, runner=zero_rate_runner)


def test_probe_rejects_an_invalid_creation_time_string(tmp_path: Path) -> None:
    video = _video_path(tmp_path)

    def bad_time_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            [],
            0,
            _ffprobe_payload(format={"duration": "12.5", "tags": {"creation_time": "nonsense"}}),
            "",
        )

    with pytest.raises(VideoProbeError, match="invalid creation time"):
        probe_local_video_metadata(video, runner=bad_time_runner)


def test_probe_rejects_a_naive_creation_time(tmp_path: Path) -> None:
    video = _video_path(tmp_path)

    def naive_time_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            [],
            0,
            _ffprobe_payload(
                format={"duration": "12.5", "tags": {"creation_time": "2026-08-10T01:42:00"}}
            ),
            "",
        )

    with pytest.raises(VideoProbeError, match="must include a timezone"):
        probe_local_video_metadata(video, runner=naive_time_runner)


def test_export_converts_a_non_utc_recorded_start_time_to_utc_z_suffix() -> None:
    jst = timezone(timedelta(hours=9))
    metadata = LocalVideoMetadata(
        **_valid_metadata_kwargs(recorded_start_time=datetime(2026, 8, 10, 13, 42, 0, tzinfo=jst))
    )

    payload = json.loads(export_local_video_metadata(metadata))

    assert payload["metadata"]["recorded_start_time"] == "2026-08-10T04:42:00Z"


def test_main_writes_metadata_and_prints_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    video = _video_path(tmp_path)
    output = tmp_path / "private-media" / "metadata.json"
    fake_metadata = LocalVideoMetadata(**_valid_metadata_kwargs())
    monkeypatch.setattr(probe_module, "probe_local_video_metadata", lambda path: fake_metadata)
    monkeypatch.setattr(sys, "argv", ["probe", str(video), "--output", str(output)])

    probe_module.main()

    out = capsys.readouterr().out
    assert "Created local-only technical metadata record." in out
    payload = json.loads(output.read_text())
    assert payload["metadata"]["file_name"] == "GX010001.MP4"
