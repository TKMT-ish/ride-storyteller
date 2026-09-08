import json
import subprocess
from pathlib import Path

import pytest

from app.video.apple_vision import (
    AppleVisionError,
    analyze_images_with_apple_vision,
    analyze_images_with_apple_vision_in_batches,
    build_apple_vision_probe,
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
                    "classifications": [{"identifier": "landscape", "confidence": 0.8}],
                },
                {
                    "index": 1,
                    "aestheticScore": -0.1,
                    "isUtility": True,
                    "classifications": [],
                },
            ],
            "distances": [{"firstIndex": 0, "secondIndex": 1, "distance": 0.75}],
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
    image_paths = tuple((tmp_path / f"frame-{index}.jpg") for index in range(5))
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


def test_parse_apple_vision_output_rejects_invalid_json() -> None:
    with pytest.raises(AppleVisionError, match="invalid JSON"):
        parse_apple_vision_output("not json", expected_count=1)


def test_parse_apple_vision_output_rejects_unsupported_schema() -> None:
    payload = json.loads(_payload())
    payload["schemaVersion"] = "ride-apple-vision-v2"

    with pytest.raises(AppleVisionError, match="schema is unsupported"):
        parse_apple_vision_output(json.dumps(payload), expected_count=2)


def test_parse_apple_vision_output_rejects_wrong_item_count() -> None:
    with pytest.raises(AppleVisionError, match="incomplete item set"):
        parse_apple_vision_output(_payload(), expected_count=3)


def test_parse_apple_vision_output_rejects_out_of_order_distance_indices() -> None:
    payload = json.loads(_payload())
    payload["distances"] = [{"firstIndex": 1, "secondIndex": 0, "distance": 0.5}]

    with pytest.raises(AppleVisionError, match="distance indices are invalid"):
        parse_apple_vision_output(json.dumps(payload), expected_count=2)


def test_parse_apple_vision_output_rejects_negative_distance() -> None:
    payload = json.loads(_payload())
    payload["distances"] = [{"firstIndex": 0, "secondIndex": 1, "distance": -0.1}]

    with pytest.raises(AppleVisionError, match="must not be negative"):
        parse_apple_vision_output(json.dumps(payload), expected_count=2)


def test_build_apple_vision_probe_rejects_non_objc_source(tmp_path: Path) -> None:
    source = tmp_path / "probe.txt"
    source.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="Objective-C"):
        build_apple_vision_probe(source, tmp_path / "probe")


def test_build_apple_vision_probe_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Objective-C"):
        build_apple_vision_probe(tmp_path / "missing.m", tmp_path / "probe")


def test_build_apple_vision_probe_rejects_output_outside_private_or_temp(
    tmp_path: Path,
) -> None:
    source = tmp_path / "probe.m"
    source.write_text("", encoding="utf-8")
    repository_root = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="private cache"):
        build_apple_vision_probe(source, repository_root / "app" / "probe")


def test_build_apple_vision_probe_compiles_into_private_cache(tmp_path: Path) -> None:
    source = tmp_path / "probe.m"
    source.write_text("", encoding="utf-8")
    output_path = tmp_path / "cache" / "probe"

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"")  # the command's trailing "-o <output_path>"
        return subprocess.CompletedProcess(command, 0, "", "")

    result = build_apple_vision_probe(source, output_path, runner=runner)

    assert result == output_path
    assert output_path.is_file()
    assert (output_path.parent / "clang-module-cache").is_dir()


def test_build_apple_vision_probe_raises_on_nonzero_return(tmp_path: Path) -> None:
    source = tmp_path / "probe.m"
    source.write_text("", encoding="utf-8")

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "compiler error")

    with pytest.raises(AppleVisionError, match="compilation failed"):
        build_apple_vision_probe(source, tmp_path / "probe", runner=runner)


def test_build_apple_vision_probe_raises_when_output_was_not_written(tmp_path: Path) -> None:
    source = tmp_path / "probe.m"
    source.write_text("", encoding="utf-8")

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "", "")  # never writes the output file

    with pytest.raises(AppleVisionError, match="compilation failed"):
        build_apple_vision_probe(source, tmp_path / "probe", runner=runner)


def test_build_apple_vision_probe_raises_when_compiler_is_missing(tmp_path: Path) -> None:
    source = tmp_path / "probe.m"
    source.write_text("", encoding="utf-8")

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("xcrun")

    with pytest.raises(AppleVisionError, match="could not run"):
        build_apple_vision_probe(source, tmp_path / "probe", runner=runner)


def test_build_apple_vision_probe_raises_on_timeout(tmp_path: Path) -> None:
    source = tmp_path / "probe.m"
    source.write_text("", encoding="utf-8")

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=command, timeout=120)

    with pytest.raises(AppleVisionError, match="could not run"):
        build_apple_vision_probe(source, tmp_path / "probe", runner=runner)


def test_analyze_images_with_apple_vision_rejects_empty_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one image"):
        analyze_images_with_apple_vision((), tmp_path / "probe")


def test_analyze_images_with_apple_vision_rejects_missing_probe(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"image")

    with pytest.raises(ValueError, match="probe executable is unavailable"):
        analyze_images_with_apple_vision((image,), tmp_path / "missing-probe")


def test_analyze_images_with_apple_vision_rejects_symlink_probe(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"image")
    real_probe = tmp_path / "real-probe"
    real_probe.write_bytes(b"")
    linked_probe = tmp_path / "linked-probe"
    linked_probe.symlink_to(real_probe)

    with pytest.raises(ValueError, match="probe executable is unavailable"):
        analyze_images_with_apple_vision((image,), linked_probe)


def test_analyze_images_with_apple_vision_rejects_non_image_suffix(tmp_path: Path) -> None:
    probe = tmp_path / "probe"
    probe.write_bytes(b"")
    not_an_image = tmp_path / "frame.gif"
    not_an_image.write_bytes(b"image")

    with pytest.raises(ValueError, match="existing non-symlink images"):
        analyze_images_with_apple_vision((not_an_image,), probe)


def test_analyze_images_with_apple_vision_rejects_symlink_image(tmp_path: Path) -> None:
    probe = tmp_path / "probe"
    probe.write_bytes(b"")
    real_image = tmp_path / "real-frame.jpg"
    real_image.write_bytes(b"image")
    linked_image = tmp_path / "linked-frame.jpg"
    linked_image.symlink_to(real_image)

    with pytest.raises(ValueError, match="existing non-symlink images"):
        analyze_images_with_apple_vision((linked_image,), probe)


def test_analyze_images_with_apple_vision_raises_on_nonzero_return(tmp_path: Path) -> None:
    probe = tmp_path / "probe"
    probe.write_bytes(b"")
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"image")

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "vision error")

    with pytest.raises(AppleVisionError, match="analysis failed"):
        analyze_images_with_apple_vision((image,), probe, runner=runner)


def test_analyze_images_with_apple_vision_raises_when_probe_is_missing(tmp_path: Path) -> None:
    probe = tmp_path / "probe"
    probe.write_bytes(b"")
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"image")

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("probe")

    with pytest.raises(AppleVisionError, match="could not run"):
        analyze_images_with_apple_vision((image,), probe, runner=runner)


def test_batched_analysis_rejects_nonpositive_batch_size(tmp_path: Path) -> None:
    probe = tmp_path / "probe"
    probe.write_bytes(b"")
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"image")

    with pytest.raises(ValueError, match="batch size must be positive"):
        analyze_images_with_apple_vision_in_batches((image,), probe, batch_size=0)
