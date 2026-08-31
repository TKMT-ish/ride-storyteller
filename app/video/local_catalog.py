"""Build a private timestamp catalog from local video container metadata.

The catalog builder is intentionally local-only. It opens source containers via
the injected metadata probe, never decodes frames, and never contacts a network
service. Camera-to-GPS clock alignment must be explicitly confirmed before any
catalog entry is produced.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Callable

from .catalog import VideoCatalog, VideoCatalogEntry
from .inventory import LocalVideoInventoryEntry, build_local_video_inventory
from .probe import LocalVideoMetadata, VideoProbeError, probe_local_video_metadata

LOCAL_VIDEO_CATALOG_SCHEMA_VERSION = "local-video-catalog-v2"
SOURCE_VIDEO_SUFFIXES = frozenset({".mov", ".mp4"})
_GOPRO_CHAPTER_PATTERN = re.compile(
    r"^G(?P<family>[XH])(?P<chapter>[0-9]{2})(?P<recording>[0-9]{4})$",
    re.IGNORECASE,
)
_GOPRO_CREATION_TIME_TOLERANCE_S = 2.0


class LocalCatalogIssueCode(StrEnum):
    """Safe issue codes that do not reveal a private filesystem path."""

    MISSING_RECORDED_START_TIME = "missing_recorded_start_time"
    PROBE_FAILED = "probe_failed"
    INVALID_GOPRO_CHAPTER_SEQUENCE = "invalid_gopro_chapter_sequence"


@dataclass(frozen=True)
class LocalCatalogIssue:
    asset_id: str
    code: LocalCatalogIssueCode

    def to_dict(self) -> dict[str, str]:
        return {"asset_id": self.asset_id, "code": self.code.value}


@dataclass(frozen=True)
class LocalVideoCatalogBuild:
    """Catalog result plus path-free build diagnostics."""

    catalog: VideoCatalog
    inventory_video_count: int
    source_video_count: int
    skipped_proxy_count: int
    logical_recording_count: int
    adjusted_chapter_count: int
    issues: tuple[LocalCatalogIssue, ...]

    def __post_init__(self) -> None:
        values = (
            self.inventory_video_count,
            self.source_video_count,
            self.skipped_proxy_count,
            self.logical_recording_count,
            self.adjusted_chapter_count,
        )
        if min(values) < 0:
            raise ValueError("catalog build counts must not be negative")
        if self.source_video_count + self.skipped_proxy_count != self.inventory_video_count:
            raise ValueError("source and skipped counts must cover the inventory")
        if len(self.catalog.entries) + len(self.issues) != self.source_video_count:
            raise ValueError("every source video must become a catalog entry or an issue")
        if self.logical_recording_count > len(self.catalog.entries):
            raise ValueError("logical recordings cannot exceed catalog entries")
        if self.adjusted_chapter_count > len(self.catalog.entries):
            raise ValueError("adjusted chapters cannot exceed catalog entries")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": LOCAL_VIDEO_CATALOG_SCHEMA_VERSION,
            "summary": {
                "inventory_video_count": self.inventory_video_count,
                "source_video_count": self.source_video_count,
                "catalog_entry_count": len(self.catalog.entries),
                "skipped_proxy_count": self.skipped_proxy_count,
                "logical_recording_count": self.logical_recording_count,
                "adjusted_chapter_count": self.adjusted_chapter_count,
                "issue_count": len(self.issues),
            },
            "video_to_gps_offset_s": self.catalog.video_to_gps_offset_s,
            "entries": [entry.to_dict() for entry in self.catalog.entries],
            "issues": [issue.to_dict() for issue in self.issues],
        }


def build_local_video_catalog(
    root: Path,
    *,
    video_to_gps_offset_s: float,
    clock_offset_confirmed: bool,
    probe: Callable[[Path], LocalVideoMetadata] = probe_local_video_metadata,
) -> LocalVideoCatalogBuild:
    """Probe local source containers after explicit clock-alignment confirmation.

    MP4 and MOV files become source candidates. LRV files remain useful private
    inventory entries, but are excluded from the source catalog to avoid treating
    a GoPro low-resolution proxy as an independent recording.
    """
    if not clock_offset_confirmed:
        raise ValueError("camera-to-GPS clock offset must be explicitly confirmed")
    if not math.isfinite(video_to_gps_offset_s):
        raise ValueError("video_to_gps_offset_s must be finite")

    inventory = build_local_video_inventory(root)
    resolved_root = root.resolve()
    entries: list[VideoCatalogEntry] = []
    issues: list[LocalCatalogIssue] = []
    skipped_proxy_count = 0
    source_items: list[LocalVideoInventoryEntry] = []
    probed: dict[str, LocalVideoMetadata] = {}

    for item in inventory.entries:
        if item.extension not in SOURCE_VIDEO_SUFFIXES:
            skipped_proxy_count += 1
            continue
        source_items.append(item)
        local_path = resolved_root.joinpath(*item.relative_path.split("/"))
        try:
            metadata = probe(local_path)
        except (OSError, ValueError, VideoProbeError):
            issues.append(LocalCatalogIssue(item.asset_id, LocalCatalogIssueCode.PROBE_FAILED))
            continue
        if metadata.recorded_start_time is None:
            issues.append(
                LocalCatalogIssue(
                    item.asset_id,
                    LocalCatalogIssueCode.MISSING_RECORDED_START_TIME,
                )
            )
            continue
        probed[item.asset_id] = metadata

    logical_recording_count = 0
    adjusted_chapter_count = 0
    grouped_items: dict[
        tuple[str, str, str], list[tuple[int, LocalVideoInventoryEntry]]
    ] = {}
    independent_items: list[LocalVideoInventoryEntry] = []
    for item in source_items:
        identity = _gopro_chapter_identity(item.file_name)
        if identity is None:
            independent_items.append(item)
            continue
        family, chapter, recording = identity
        parent = PurePosixPath(item.relative_path).parent.as_posix()
        grouped_items.setdefault((parent, family, recording), []).append((chapter, item))

    for item in independent_items:
        metadata = probed.get(item.asset_id)
        if metadata is None:
            continue
        entries.append(_catalog_entry(item.asset_id, item.file_name, metadata))
        logical_recording_count += 1

    for group in grouped_items.values():
        expected_chapters = list(range(1, len(group) + 1))
        chapters = sorted(chapter for chapter, _item in group)
        successful = [
            (chapter, item, probed[item.asset_id])
            for chapter, item in group
            if item.asset_id in probed
        ]
        complete = len(successful) == len(group)
        valid_sequence = chapters == expected_chapters
        creation_times = [metadata.recorded_start_time for _, _, metadata in successful]
        common_creation_time = bool(creation_times) and (
            max(value.timestamp() for value in creation_times)
            - min(value.timestamp() for value in creation_times)
            <= _GOPRO_CREATION_TIME_TOLERANCE_S
        )
        if not complete or not valid_sequence or not common_creation_time:
            issues.extend(
                LocalCatalogIssue(
                    item.asset_id,
                    LocalCatalogIssueCode.INVALID_GOPRO_CHAPTER_SEQUENCE,
                )
                for _chapter, item, _metadata in successful
            )
            continue

        logical_recording_count += 1
        cumulative_duration_s = 0.0
        for chapter, item, metadata in sorted(successful, key=lambda value: value[0]):
            assert metadata.recorded_start_time is not None
            entries.append(
                VideoCatalogEntry(
                    asset_id=item.asset_id,
                    file_name=item.file_name,
                    recorded_start_time=(
                        metadata.recorded_start_time
                        + timedelta(seconds=cumulative_duration_s)
                    ),
                    duration_s=metadata.duration_s,
                )
            )
            if chapter > 1:
                adjusted_chapter_count += 1
            cumulative_duration_s += metadata.duration_s

    source_video_count = len(inventory.entries) - skipped_proxy_count
    return LocalVideoCatalogBuild(
        catalog=VideoCatalog(
            entries=tuple(
                sorted(entries, key=lambda entry: (entry.recorded_start_time, entry.file_name))
            ),
            video_to_gps_offset_s=video_to_gps_offset_s,
        ),
        inventory_video_count=len(inventory.entries),
        source_video_count=source_video_count,
        skipped_proxy_count=skipped_proxy_count,
        logical_recording_count=logical_recording_count,
        adjusted_chapter_count=adjusted_chapter_count,
        issues=tuple(issues),
    )


def _gopro_chapter_identity(file_name: str) -> tuple[str, int, str] | None:
    match = _GOPRO_CHAPTER_PATTERN.fullmatch(Path(file_name).stem)
    if match is None:
        return None
    return (
        match.group("family").upper(),
        int(match.group("chapter")),
        match.group("recording"),
    )


def _catalog_entry(
    asset_id: str,
    file_name: str,
    metadata: LocalVideoMetadata,
) -> VideoCatalogEntry:
    assert metadata.recorded_start_time is not None
    return VideoCatalogEntry(
        asset_id=asset_id,
        file_name=file_name,
        recorded_start_time=metadata.recorded_start_time,
        duration_s=metadata.duration_s,
    )


def export_local_video_catalog(build: LocalVideoCatalogBuild) -> str:
    """Serialize a private catalog without adding an absolute root path."""
    return json.dumps(build.to_dict(), ensure_ascii=False, indent=2) + "\n"


def write_local_video_catalog(
    output_path: Path,
    build: LocalVideoCatalogBuild,
    *,
    overwrite: bool = False,
) -> Path:
    """Write a catalog only to an explicit private path."""
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            "catalog output already exists; choose a new path or pass overwrite=True"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(export_local_video_catalog(build), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a private local video catalog after clock alignment confirmation."
    )
    parser.add_argument("video_root", type=Path, help="private root directory containing videos")
    parser.add_argument("--output", type=Path, required=True, help="private catalog JSON path")
    parser.add_argument(
        "--clock-offset-s",
        type=float,
        required=True,
        help="confirmed seconds added to camera time to obtain GPS time",
    )
    parser.add_argument(
        "--clock-offset-confirmed",
        action="store_true",
        help="confirm that the supplied camera-to-GPS offset was checked locally",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace the explicit output")
    args = parser.parse_args()
    build = build_local_video_catalog(
        args.video_root,
        video_to_gps_offset_s=args.clock_offset_s,
        clock_offset_confirmed=args.clock_offset_confirmed,
    )
    write_local_video_catalog(args.output, build, overwrite=args.overwrite)
    print(
        "Created local-only video catalog: "
        f"{len(build.catalog.entries)} entries, {len(build.issues)} issues, "
        f"{build.skipped_proxy_count} proxies skipped."
    )


if __name__ == "__main__":
    main()
