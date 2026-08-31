import subprocess
from pathlib import Path

import pytest

from app.video import ResolvedCandidateClip, VideoMatchStatus
from app.video.local_clips import (
    LocalClipExtractionError,
    LocalReviewClip,
    extract_local_review_clips,
    load_local_review_clip_manifest,
    write_local_review_clip_manifest,
)


def _matched(asset_id: str, *, event_id: str = "event_001") -> ResolvedCandidateClip:
    return ResolvedCandidateClip(
        chapter_id="chapter_01",
        event_id=event_id,
        status=VideoMatchStatus.MATCHED,
        asset_id=asset_id,
        file_name="source.mp4",
        start_offset_s=2.0,
        end_offset_s=7.0,
        reason="test",
    )


def _source(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "source"
    root.mkdir()
    video = root / "source.mp4"
    video.write_bytes(b"source")
    from app.video import build_local_video_inventory

    return root, build_local_video_inventory(root).entries[0].asset_id


def test_extract_review_clip_uses_ffmpeg_without_shell(tmp_path: Path) -> None:
    root, asset_id = _source(tmp_path)
    received: dict[str, object] = {}

    def runner(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        received["command"] = command
        received["kwargs"] = kwargs
        Path(command[-1]).write_bytes(b"review")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = extract_local_review_clips(
        (_matched(asset_id),),
        video_root=root,
        output_directory=tmp_path / "reviews",
        runner=runner,
    )

    command = received["command"]
    assert isinstance(command, tuple)
    assert command[0] == "ffmpeg"
    assert "-ss" in command and "-t" in command
    assert "scale=-2:720" in command
    assert received["kwargs"] == {
        "check": False,
        "capture_output": True,
        "text": True,
        "timeout": 60.0,
    }
    assert result[0].output_file_name == "review-001.mp4"
    assert result[0].duration_s == 5.0


def test_extract_review_clip_refuses_unmatched_candidate(tmp_path: Path) -> None:
    unmatched = ResolvedCandidateClip(
        chapter_id="chapter_01",
        event_id="event_001",
        status=VideoMatchStatus.NOT_FOUND,
        asset_id=None,
        file_name=None,
        start_offset_s=None,
        end_offset_s=None,
        reason="missing",
    )

    with pytest.raises(ValueError, match="timestamp matched"):
        extract_local_review_clips(
            (unmatched,),
            video_root=tmp_path,
            output_directory=tmp_path / "reviews",
        )


def test_extract_review_clip_refuses_missing_asset_without_path(tmp_path: Path) -> None:
    root, _asset_id = _source(tmp_path)

    with pytest.raises(LocalClipExtractionError, match="source asset is unavailable") as error:
        extract_local_review_clips(
            (_matched("missing-asset"),),
            video_root=root,
            output_directory=tmp_path / "reviews",
        )

    assert str(root) not in str(error.value)


def test_extract_review_clip_requires_explicit_overwrite(tmp_path: Path) -> None:
    root, asset_id = _source(tmp_path)
    output = tmp_path / "reviews"
    output.mkdir()
    (output / "review-001.mp4").write_bytes(b"existing")

    with pytest.raises(FileExistsError, match="already exists"):
        extract_local_review_clips(
            (_matched(asset_id),),
            video_root=root,
            output_directory=output,
        )


def test_extract_review_clip_hides_ffmpeg_error_details(tmp_path: Path) -> None:
    root, asset_id = _source(tmp_path)

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", f"private path: {root}")

    with pytest.raises(LocalClipExtractionError, match="could not create") as error:
        extract_local_review_clips(
            (_matched(asset_id),),
            video_root=root,
            output_directory=tmp_path / "reviews",
            runner=runner,
        )

    assert str(root) not in str(error.value)


def test_review_clip_manifest_round_trip_and_overwrite_guard(tmp_path: Path) -> None:
    path = tmp_path / "review-clip-manifest.json"
    clips = (LocalReviewClip("event_001", "asset_001", "review-001.mp4", 5.0),)

    assert write_local_review_clip_manifest(path, clips) == path
    assert load_local_review_clip_manifest(path) == clips
    with pytest.raises(FileExistsError, match="already exists"):
        write_local_review_clip_manifest(path, clips)
    assert write_local_review_clip_manifest(path, clips, overwrite=True) == path
