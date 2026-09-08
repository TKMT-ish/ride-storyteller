from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.video.catalog import VideoCatalog, VideoCatalogEntry
from app.video.local_catalog import (
    LocalCatalogIssue,
    LocalCatalogIssueCode,
    LocalVideoCatalogBuild,
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
        issue.code is LocalCatalogIssueCode.INVALID_GOPRO_CHAPTER_SEQUENCE for issue in build.issues
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


def test_catalog_accepts_gopro_chapter_names_case_insensitively(tmp_path: Path) -> None:
    for name in ("gx010001.mp4", "gx020001.mp4"):
        (tmp_path / name).write_bytes(b"source")
    base = datetime(2026, 8, 10, 1, 42, tzinfo=UTC)

    build = build_local_video_catalog(
        tmp_path,
        video_to_gps_offset_s=0.0,
        clock_offset_confirmed=True,
        probe=lambda path: _metadata(path, duration_s=10.0, start=base),
    )

    assert build.logical_recording_count == 1
    assert build.adjusted_chapter_count == 1
    assert build.issues == ()


def test_catalog_rejects_true_duplicate_chapter_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.video.local_catalog as local_catalog

    for name in ("GX010001.MP4", "GX020001.MP4"):
        (tmp_path / name).write_bytes(b"source")

    # Force both files to resolve to chapter 1 of the same logical recording,
    # producing the sequence [1, 1] instead of the expected [1, 2].
    monkeypatch.setattr(
        local_catalog,
        "_gopro_chapter_identity",
        lambda file_name: ("X", 1, "0001"),
    )

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
        issue.code is LocalCatalogIssueCode.INVALID_GOPRO_CHAPTER_SEQUENCE for issue in build.issues
    )
    assert str(tmp_path) not in payload


def test_catalog_accepts_creation_times_at_the_tolerance_boundary(tmp_path: Path) -> None:
    for name in ("GX010001.MP4", "GX020001.MP4"):
        (tmp_path / name).write_bytes(b"source")
    base = datetime(2026, 8, 10, 1, 42, tzinfo=UTC)
    starts = {
        "GX010001.MP4": base,
        "GX020001.MP4": base + timedelta(seconds=2.0),
    }

    build = build_local_video_catalog(
        tmp_path,
        video_to_gps_offset_s=0.0,
        clock_offset_confirmed=True,
        probe=lambda path: _metadata(path, duration_s=10.0, start=starts[path.name]),
    )

    assert build.logical_recording_count == 1
    assert build.issues == ()


def test_catalog_rejects_creation_times_just_past_the_tolerance_boundary(
    tmp_path: Path,
) -> None:
    for name in ("GX010001.MP4", "GX020001.MP4"):
        (tmp_path / name).write_bytes(b"source")
    base = datetime(2026, 8, 10, 1, 42, tzinfo=UTC)
    starts = {
        "GX010001.MP4": base,
        "GX020001.MP4": base + timedelta(seconds=2.01),
    }

    build = build_local_video_catalog(
        tmp_path,
        video_to_gps_offset_s=0.0,
        clock_offset_confirmed=True,
        probe=lambda path: _metadata(path, duration_s=10.0, start=starts[path.name]),
    )

    assert build.catalog.entries == ()
    assert len(build.issues) == 2
    assert all(
        issue.code is LocalCatalogIssueCode.INVALID_GOPRO_CHAPTER_SEQUENCE for issue in build.issues
    )


def test_catalog_marks_probed_siblings_invalid_when_one_chapter_fails_to_probe(
    tmp_path: Path,
) -> None:
    for name in ("GX010001.MP4", "GX020001.MP4"):
        (tmp_path / name).write_bytes(b"source")
    base = datetime(2026, 8, 10, 1, 42, tzinfo=UTC)

    def probe(path: Path) -> LocalVideoMetadata:
        if path.name == "GX020001.MP4":
            raise VideoProbeError("boom")
        return _metadata(path, start=base)

    build = build_local_video_catalog(
        tmp_path,
        video_to_gps_offset_s=0.0,
        clock_offset_confirmed=True,
        probe=probe,
    )

    assert build.catalog.entries == ()
    # One PROBE_FAILED issue for the chapter that could not be read, plus one
    # INVALID_GOPRO_CHAPTER_SEQUENCE issue for its sibling: an incomplete
    # chapter group cannot become a logical recording even when the other
    # chapter probed cleanly.
    codes = sorted(issue.code for issue in build.issues)
    assert codes == sorted(
        [
            LocalCatalogIssueCode.PROBE_FAILED,
            LocalCatalogIssueCode.INVALID_GOPRO_CHAPTER_SEQUENCE,
        ]
    )
    assert build.logical_recording_count == 0


def test_catalog_sorts_independent_and_grouped_entries_together(tmp_path: Path) -> None:
    for name in ("GX010001.MP4", "GX020001.MP4", "clip.mov"):
        (tmp_path / name).write_bytes(b"source")
    base = datetime(2026, 8, 10, 1, 42, tzinfo=UTC)
    starts = {
        # The independent clip starts before the grouped recording's first
        # chapter, so it must sort ahead of both grouped entries.
        "clip.mov": base - timedelta(minutes=5),
        "GX010001.MP4": base,
        "GX020001.MP4": base,
    }

    build = build_local_video_catalog(
        tmp_path,
        video_to_gps_offset_s=0.0,
        clock_offset_confirmed=True,
        probe=lambda path: _metadata(path, duration_s=10.0, start=starts[path.name]),
    )

    assert [entry.file_name for entry in build.catalog.entries] == [
        "clip.mov",
        "GX010001.MP4",
        "GX020001.MP4",
    ]


def test_issue_to_dict_is_path_free() -> None:
    issue = LocalCatalogIssue("local-video-abc123", LocalCatalogIssueCode.PROBE_FAILED)
    assert issue.to_dict() == {"asset_id": "local-video-abc123", "code": "probe_failed"}


def _valid_entry() -> VideoCatalogEntry:
    return VideoCatalogEntry(
        asset_id="local-video-abc123",
        file_name="GX010001.MP4",
        recorded_start_time=datetime(2026, 8, 10, 1, 42, tzinfo=UTC),
        duration_s=10.0,
    )


def test_build_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        LocalVideoCatalogBuild(
            catalog=VideoCatalog(entries=()),
            inventory_video_count=-1,
            source_video_count=0,
            skipped_proxy_count=0,
            logical_recording_count=0,
            adjusted_chapter_count=0,
            issues=(),
        )


def test_build_rejects_source_and_skipped_counts_not_covering_inventory() -> None:
    with pytest.raises(ValueError, match="must cover the inventory"):
        LocalVideoCatalogBuild(
            catalog=VideoCatalog(entries=()),
            inventory_video_count=5,
            source_video_count=2,
            skipped_proxy_count=2,
            logical_recording_count=0,
            adjusted_chapter_count=0,
            issues=(),
        )


def test_build_rejects_entries_and_issues_not_matching_source_count() -> None:
    with pytest.raises(ValueError, match="catalog entry or an issue"):
        LocalVideoCatalogBuild(
            catalog=VideoCatalog(entries=(_valid_entry(),)),
            inventory_video_count=1,
            source_video_count=1,
            skipped_proxy_count=0,
            logical_recording_count=1,
            adjusted_chapter_count=0,
            issues=(LocalCatalogIssue("local-video-def456", LocalCatalogIssueCode.PROBE_FAILED),),
        )


def test_build_rejects_logical_recording_count_over_entry_count() -> None:
    with pytest.raises(ValueError, match="logical recordings cannot exceed"):
        LocalVideoCatalogBuild(
            catalog=VideoCatalog(entries=(_valid_entry(),)),
            inventory_video_count=1,
            source_video_count=1,
            skipped_proxy_count=0,
            logical_recording_count=2,
            adjusted_chapter_count=0,
            issues=(),
        )


def test_build_rejects_adjusted_chapter_count_over_entry_count() -> None:
    with pytest.raises(ValueError, match="adjusted chapters cannot exceed"):
        LocalVideoCatalogBuild(
            catalog=VideoCatalog(entries=(_valid_entry(),)),
            inventory_video_count=1,
            source_video_count=1,
            skipped_proxy_count=0,
            logical_recording_count=1,
            adjusted_chapter_count=2,
            issues=(),
        )
