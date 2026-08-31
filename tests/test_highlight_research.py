from pathlib import Path

import pytest

from app.video.highlight_research import (
    _build_diversity_pool,
    _remap_vision_distance,
    build_contact_sheet_command,
    build_frame_extraction_command,
    run_local_highlight_research,
)


def test_frame_extraction_command_uses_one_local_proxy_and_three_quarter_safe_output(
    tmp_path: Path,
) -> None:
    proxy = tmp_path / "proxy file.lrv"
    output = tmp_path / "frame.jpg"

    command = build_frame_extraction_command(
        proxy,
        output,
        time_s=12.5,
        overwrite=False,
    )

    assert command[command.index("-i") + 1] == str(proxy)
    assert command[command.index("-ss") + 1] == "12.5"
    assert "scale=640:-2" in command
    assert command[-1] == str(output)


def test_frame_extraction_rejects_negative_time(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        build_frame_extraction_command(
            tmp_path / "proxy.lrv",
            tmp_path / "frame.jpg",
            time_s=-1,
            overwrite=False,
        )


def test_contact_sheet_command_calculates_grid_without_shell_glob(tmp_path: Path) -> None:
    command = build_contact_sheet_command(
        tmp_path / "thumbnails",
        tmp_path / "sheet.jpg",
        thumbnail_count=12,
        overwrite=True,
    )

    assert command[command.index("-pattern_type") + 1] == "glob"
    assert command[command.index("-i") + 1].endswith("*.jpg")
    assert "tile=5x3" in command[command.index("-vf") + 1]


def test_research_rejects_public_repository_output() -> None:
    repository_root = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="ignored private directory"):
        run_local_highlight_research(
            Path("missing.gpx"),
            Path("missing-video"),
            Path("missing-catalog.json"),
            repository_root / "unsafe-research-output",
        )


def test_remapped_vision_distance_rejects_candidates_outside_bounded_pool() -> None:
    def distance(first: int, second: int) -> float:
        return abs(first - second) / 10

    remapped = _remap_vision_distance((10, 20, 30), distance)

    assert remapped(10, 30) == pytest.approx(0.2)
    with pytest.raises(KeyError, match="outside the diversity pool"):
        remapped(10, 40)


def test_diversity_pool_requires_positive_limit() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        _build_diversity_pool((), per_method=0)
