"""Create a private, local-only inventory of source video files.

This module deliberately records filesystem metadata only.  It neither probes
video contents nor contacts any external service.  In particular, an inventory
is not a timestamp-matching video catalog: duration and camera clock data must
be validated in a later, explicit step before a catalog is created.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

SUPPORTED_VIDEO_SUFFIXES = frozenset({".lrv", ".mov", ".mp4"})
INVENTORY_SCHEMA_VERSION = "local-video-inventory-v1"


@dataclass(frozen=True)
class LocalVideoInventoryEntry:
    """Filesystem metadata for one private source-video file."""

    asset_id: str
    relative_path: str
    file_name: str
    file_size_bytes: int
    modified_time: datetime
    extension: str

    def __post_init__(self) -> None:
        relative_path = PurePosixPath(self.relative_path)
        if not self.asset_id or not self.file_name:
            raise ValueError("asset_id and file_name are required")
        if (
            not self.relative_path
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or relative_path.name != self.file_name
        ):
            raise ValueError("relative_path must be a safe relative path ending in file_name")
        if self.file_size_bytes < 0:
            raise ValueError("file_size_bytes must not be negative")
        if self.modified_time.tzinfo is None:
            raise ValueError("modified_time must be timezone-aware")
        if self.extension not in SUPPORTED_VIDEO_SUFFIXES:
            raise ValueError("extension must be a supported video suffix")

    def to_dict(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "relative_path": self.relative_path,
            "file_name": self.file_name,
            "file_size_bytes": self.file_size_bytes,
            "modified_time": _isoformat_utc(self.modified_time),
            "extension": self.extension,
        }


@dataclass(frozen=True)
class LocalVideoInventory:
    """A private inventory with no absolute filesystem paths or video contents."""

    root_label: str
    entries: tuple[LocalVideoInventoryEntry, ...]

    def __post_init__(self) -> None:
        if not self.root_label:
            raise ValueError("root_label is required")
        identifiers = [entry.asset_id for entry in self.entries]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("local video inventory asset_id values must be unique")

    @property
    def total_size_bytes(self) -> int:
        return sum(entry.file_size_bytes for entry in self.entries)

    @property
    def count_by_extension(self) -> dict[str, int]:
        counts = Counter(entry.extension for entry in self.entries)
        return {extension: counts[extension] for extension in sorted(counts)}

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": INVENTORY_SCHEMA_VERSION,
            "root_label": self.root_label,
            "summary": {
                "video_file_count": len(self.entries),
                "total_size_bytes": self.total_size_bytes,
                "count_by_extension": self.count_by_extension,
            },
            "entries": [entry.to_dict() for entry in self.entries],
        }


def build_local_video_inventory(root: Path) -> LocalVideoInventory:
    """Scan a user-selected directory recursively without following symlinks.

    Only file name, relative path, size, modified time, and extension are
    recorded.  Files are never opened, uploaded, or hashed by content.
    """
    if not root.is_dir():
        raise ValueError("video root must be an existing directory")

    root = root.resolve()
    entries: list[LocalVideoInventoryEntry] = []
    for directory, subdirectories, file_names in os.walk(root, followlinks=False):
        current_directory = Path(directory)
        subdirectories[:] = sorted(
            name for name in subdirectories if not (current_directory / name).is_symlink()
        )
        for file_name in sorted(file_names):
            path = current_directory / file_name
            if path.is_symlink() or not path.is_file():
                continue
            extension = path.suffix.lower()
            if extension not in SUPPORTED_VIDEO_SUFFIXES:
                continue
            stat = path.stat()
            relative_path = path.relative_to(root).as_posix()
            entries.append(
                LocalVideoInventoryEntry(
                    asset_id=_asset_id(relative_path),
                    relative_path=relative_path,
                    file_name=file_name,
                    file_size_bytes=stat.st_size,
                    modified_time=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    extension=extension,
                )
            )
    return LocalVideoInventory(root_label=root.name, entries=tuple(entries))


def export_local_video_inventory(inventory: LocalVideoInventory) -> str:
    """Serialize a private inventory without emitting an absolute root path."""
    return json.dumps(inventory.to_dict(), ensure_ascii=False, indent=2) + "\n"


def write_local_video_inventory(
    output_path: Path, inventory: LocalVideoInventory, *, overwrite: bool = False
) -> Path:
    """Write to an explicit private path, preserving an existing file by default."""
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            "inventory output already exists; choose a new path or pass overwrite=True"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(export_local_video_inventory(inventory), encoding="utf-8")
    return output_path


def _asset_id(relative_path: str) -> str:
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]
    return f"local-video-{digest}"


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a local-only inventory of GoPro video filesystem metadata."
    )
    parser.add_argument("video_root", type=Path, help="private root directory containing videos")
    parser.add_argument("--output", type=Path, required=True, help="private JSON output path")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing inventory file at the explicit output path",
    )
    args = parser.parse_args()

    inventory = build_local_video_inventory(args.video_root)
    write_local_video_inventory(args.output, inventory, overwrite=args.overwrite)
    print(
        "Created local-only inventory: "
        f"{len(inventory.entries)} video files, {inventory.total_size_bytes} bytes."
    )


if __name__ == "__main__":
    main()
