import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.video.inventory import (
    INVENTORY_SCHEMA_VERSION,
    LocalVideoInventory,
    LocalVideoInventoryEntry,
    build_local_video_inventory,
    export_local_video_inventory,
    write_local_video_inventory,
)


def test_inventory_scans_recursively_without_absolute_paths(tmp_path: Path) -> None:
    root = tmp_path / "private-ride"
    nested = root / "south-island"
    nested.mkdir(parents=True)
    (root / "GX010001.MP4").write_bytes(b"a" * 3)
    (nested / "GX010002.mov").write_bytes(b"b" * 5)
    (nested / "GX010003.LRV").write_bytes(b"c" * 7)
    (nested / "notes.txt").write_text("not a video")

    inventory = build_local_video_inventory(root)
    payload = export_local_video_inventory(inventory)

    assert inventory.root_label == "private-ride"
    assert [entry.relative_path for entry in inventory.entries] == [
        "GX010001.MP4",
        "south-island/GX010002.mov",
        "south-island/GX010003.LRV",
    ]
    assert inventory.total_size_bytes == 15
    assert inventory.count_by_extension == {".lrv": 1, ".mov": 1, ".mp4": 1}
    assert str(root) not in payload
    assert str(tmp_path) not in payload
    assert json.loads(payload)["schema_version"] == INVENTORY_SCHEMA_VERSION


def test_inventory_asset_ids_are_deterministic_for_unchanged_relative_paths(tmp_path: Path) -> None:
    root = tmp_path / "private-ride"
    root.mkdir()
    (root / "GX010001.MP4").write_bytes(b"source")

    first = build_local_video_inventory(root)
    second = build_local_video_inventory(root)

    assert first.entries[0].asset_id == second.entries[0].asset_id


def test_inventory_rejects_a_missing_or_non_directory_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="existing directory"):
        build_local_video_inventory(tmp_path / "missing")

    a_file = tmp_path / "not-a-directory.mp4"
    a_file.write_bytes(b"source")
    with pytest.raises(ValueError, match="existing directory"):
        build_local_video_inventory(a_file)


@pytest.mark.parametrize("relative_path", ["/private/ride/GX010001.MP4", "../GX010001.MP4"])
def test_inventory_entry_rejects_an_absolute_or_parent_path(relative_path: str) -> None:
    with pytest.raises(ValueError, match="safe relative path"):
        LocalVideoInventoryEntry(
            asset_id="local-video-example",
            relative_path=relative_path,
            file_name="GX010001.MP4",
            file_size_bytes=1,
            modified_time=datetime(2026, 8, 16, tzinfo=UTC),
            extension=".mp4",
        )


def test_inventory_skips_symlinked_source_files(tmp_path: Path) -> None:
    root = tmp_path / "private-ride"
    outside = tmp_path / "outside.mp4"
    root.mkdir()
    (root / "GX010001.MP4").write_bytes(b"source")
    outside.write_bytes(b"outside")
    (root / "linked.mp4").symlink_to(outside)

    inventory = build_local_video_inventory(root)

    assert [entry.file_name for entry in inventory.entries] == ["GX010001.MP4"]


def test_inventory_write_requires_explicit_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "private-ride"
    root.mkdir()
    (root / "GX010001.MP4").write_bytes(b"source")
    output = tmp_path / "private-output" / "inventory.json"
    inventory = build_local_video_inventory(root)

    assert write_local_video_inventory(output, inventory) == output
    with pytest.raises(FileExistsError, match="already exists"):
        write_local_video_inventory(output, inventory)
    assert write_local_video_inventory(output, inventory, overwrite=True) == output


def test_inventory_rejects_duplicate_asset_ids() -> None:
    entry = LocalVideoInventoryEntry(
        asset_id="local-video-example",
        relative_path="GX010001.MP4",
        file_name="GX010001.MP4",
        file_size_bytes=1,
        modified_time=datetime(2026, 8, 16, tzinfo=UTC),
        extension=".mp4",
    )
    with pytest.raises(ValueError, match="must be unique"):
        LocalVideoInventory(root_label="private-ride", entries=(entry, entry))
