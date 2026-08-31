from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.video.local_catalog import (
    LocalCatalogIssueCode,
    build_local_video_catalog,
    export_local_video_catalog,
    write_local_video_catalog,
)
from app.video.probe import LocalVideoMetadata, VideoProbeError


def _metadata(
    path: Path,
    *,
    recorded: bool = True,
    duration_s: float = 120.0,
    start: datetime | None = None,
) -> LocalVideoMetadata:
    return LocalVideoMetadata(
        file_name=path.name,
        duration_s=duration_s,
        recorded_start_time=(
            start or datetime(2026, 8, 10, 1, 42, tzinfo=UTC) if recorded else None
        ),
        video_codec="hevc",
        width=3840,
        height=2160,
        frames_per_second=60.0,
        has_audio=True,
    )


def test_catalog_requires_explicit_clock_confirmation_before_probe(tmp_path: Path) -> None:
    video = tmp_path / "GX010001.MP4"
    video.write_bytes(b"source")
    calls: list[Path] = []

    def probe(path: Path) -> LocalVideoMetadata:
        calls.append(path)
        return _metadata(path)

    with pytest.raises(ValueError, match="explicitly confirmed"):
        build_local_video_catalog(
            tmp_path,
            video_to_gps_offset_s=0.0,
            clock_offset_confirmed=False,
            probe=probe,
        )

    assert calls == []


def test_catalog_builds_sources_and_skips_lrv_proxy(tmp_path: Path) -> None:
    (tmp_path / "GX010001.MP4").write_bytes(b"source")
    (tmp_path / "clip.mov").write_bytes(b"source")
    (tmp_path / "GL010001.LRV").write_bytes(b"proxy")

    build = build_local_video_catalog(
        tmp_path,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        probe=_metadata,
    )

    assert len(build.catalog.entries) == 2
    assert build.catalog.video_to_gps_offset_s == 5.0
    assert build.inventory_video_count == 3
    assert build.source_video_count == 2
    assert build.skipped_proxy_count == 1
    assert build.logical_recording_count == 2
    assert build.adjusted_chapter_count == 0
    assert build.issues == ()


def test_catalog_adjusts_gopro_chapter_start_times_cumulatively(tmp_path: Path) -> None:
    for name in ("GX010001.MP4", "GX020001.MP4", "GX030001.MP4"):
        (tmp_path / name).write_bytes(b"source")
    base = datetime(2026, 8, 10, 1, 42, tzinfo=UTC)
    durations = {
        "GX010001.MP4": 10.0,
        "GX020001.MP4": 20.0,
        "GX030001.MP4": 30.0,
    }

    build = build_local_video_catalog(
        tmp_path,
        video_to_gps_offset_s=0.0,
        clock_offset_confirmed=True,
        probe=lambda path: _metadata(path, duration_s=durations[path.name], start=base),
    )

    assert [entry.recorded_start_time for entry in build.catalog.entries] == [
        base,
        base + timedelta(seconds=10),
        base + timedelta(seconds=30),
    ]
    assert build.logical_recording_count == 1
    assert build.adjusted_chapter_count == 2
    assert build.issues == ()


def test_catalog_rejects_incomplete_gopro_chapter_group_without_paths(
    tmp_path: Path,
) -> None:
    for name in ("GX010001.MP4", "GX030001.MP4"):
        (tmp_path / name).write_bytes(b"source")

    build = build_local_video_catalog(
        tmp_path,
        video_to_gps_offset_s=0.0,
        clock_offset_confirmed=True,
        probe=_metadata,
    )
    payload = export_local_video_catalog(build)

    assert build.catalog.entries == ()
    assert len(build.issues) == 2
    assert all(
        issue.code is LocalCatalogIssueCode.INVALID_GOPRO_CHAPTER_SEQUENCE
        for issue in build.issues
    )
    assert str(tmp_path) not in payload


def test_catalog_records_missing_creation_time_without_registering_entry(
    tmp_path: Path,
) -> None:
    (tmp_path / "GX010001.MP4").write_bytes(b"source")

    build = build_local_video_catalog(
        tmp_path,
        video_to_gps_offset_s=0.0,
        clock_offset_confirmed=True,
        probe=lambda path: _metadata(path, recorded=False),
    )

    assert build.catalog.entries == ()
    assert build.issues[0].code is LocalCatalogIssueCode.MISSING_RECORDED_START_TIME


def test_catalog_turns_probe_failure_into_path_free_issue(tmp_path: Path) -> None:
    video = tmp_path / "GX010001.MP4"
    video.write_bytes(b"source")

    def failing_probe(_path: Path) -> LocalVideoMetadata:
        raise VideoProbeError(f"could not read {video}")

    build = build_local_video_catalog(
        tmp_path,
        video_to_gps_offset_s=0.0,
        clock_offset_confirmed=True,
        probe=failing_probe,
    )
    payload = export_local_video_catalog(build)

    assert build.issues[0].code is LocalCatalogIssueCode.PROBE_FAILED
    assert str(tmp_path) not in payload


@pytest.mark.parametrize("offset", [float("nan"), float("inf"), float("-inf")])
def test_catalog_rejects_nonfinite_clock_offset(tmp_path: Path, offset: float) -> None:
    with pytest.raises(ValueError, match="must be finite"):
        build_local_video_catalog(
            tmp_path,
            video_to_gps_offset_s=offset,
            clock_offset_confirmed=True,
            probe=_metadata,
        )


def test_catalog_write_requires_explicit_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "GX010001.MP4").write_bytes(b"source")
    build = build_local_video_catalog(
        source,
        video_to_gps_offset_s=0.0,
        clock_offset_confirmed=True,
        probe=_metadata,
    )
    output = tmp_path / "private" / "catalog.json"

    assert write_local_video_catalog(output, build) == output
    with pytest.raises(FileExistsError, match="already exists"):
        write_local_video_catalog(output, build)
    assert write_local_video_catalog(output, build, overwrite=True) == output
