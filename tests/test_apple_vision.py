import json
import subprocess
from pathlib import Path

import pytest

from app.video.apple_vision import (
    AppleVisionError,
    analyze_images_with_apple_vision_in_batches,
    parse_apple_vision_output,
)


def _payload() -> str:
    return json.dumps(
        {
            "schemaVersion": "ride-apple-vision-v1",
            "items": [
                {
                    "index": 0,
                    "aestheticScore": 0.4,
                    "isUtility": False,
                    "classifications": [
                        {"identifier": "landscape", "confidence": 0.8}
                    ],
                },
                {
                    "index": 1,
                    "aestheticScore": -0.1,
                    "isUtility": True,
                    "classifications": [],
                },
            ],
            "distances": [
                {"firstIndex": 0, "secondIndex": 1, "distance": 0.75}
            ],
        }
    )


def test_apple_vision_parser_reads_quality_semantics_and_distance() -> None:
    result = parse_apple_vision_output(_payload(), expected_count=2)

    assert result.items[0].aesthetic_score == pytest.approx(0.4)
    assert result.items[0].classifications[0].identifier == "landscape"
    assert result.items[1].is_utility is True
    assert result.distance(0, 1) == pytest.approx(0.75)
    assert result.distance(1, 1) == 0


def test_apple_vision_parser_rejects_incomplete_distance_matrix() -> None:
    payload = json.loads(_payload())
    payload["distances"] = []

    with pytest.raises(AppleVisionError, match="matrix is incomplete"):
        parse_apple_vision_output(json.dumps(payload), expected_count=2)


def test_apple_vision_parser_allows_distance_free_quality_batch() -> None:
    payload = json.loads(_payload())
    payload["distances"] = []

    result = parse_apple_vision_output(
        json.dumps(payload),
        expected_count=2,
        require_distances=False,
    )

    assert len(result.items) == 2
    with pytest.raises(KeyError, match="unavailable"):
        result.distance(0, 1)


def test_apple_vision_parser_rejects_noncontiguous_indices() -> None:
    payload = json.loads(_payload())
    payload["items"][1]["index"] = 3

    with pytest.raises(AppleVisionError, match="indices are not contiguous"):
        parse_apple_vision_output(json.dumps(payload), expected_count=2)


def test_probe_source_contains_no_external_network_or_upload_call() -> None:
    source = Path(__file__).resolve().parents[1] / "tools" / "apple_vision_probe.m"
    content = source.read_text(encoding="utf-8")

    assert "NSURLSession" not in content
    assert "http://" not in content
    assert "https://" not in content


def test_batched_analysis_uses_distance_free_commands_and_global_indices(
    tmp_path: Path,
) -> None:
    probe = tmp_path / "private-probe"
    probe.write_text("", encoding="utf-8")
    image_paths = tuple(
        (tmp_path / f"frame-{index}.jpg") for index in range(5)
    )
    for path in image_paths:
        path.write_bytes(b"image")
    commands: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        images = command[2:]
        payload = {
            "schemaVersion": "ride-apple-vision-v1",
            "items": [
                {
                    "index": index,
                    "aestheticScore": 0.1,
                    "isUtility": False,
                    "classifications": [],
                }
                for index, _path in enumerate(images)
            ],
            "distances": [],
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    items = analyze_images_with_apple_vision_in_batches(
        image_paths,
        probe,
        batch_size=2,
        runner=runner,
    )

    assert [item.index for item in items] == [0, 1, 2, 3, 4]
    assert len(commands) == 3
    assert all(command[1] == "--no-distances" for command in commands)
