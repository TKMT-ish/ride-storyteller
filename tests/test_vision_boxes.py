"""Synthetic-fixture tests for the on-device boxes helper. Vision is never run."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.video.apple_vision import AppleVisionError
from app.video.vision_boxes import (
    VISION_BOXES_SOURCE,
    FrameBoxes,
    VisionBox,
    build_vision_boxes_probe,
    detect_boxes,
    detect_boxes_in_batches,
    parse_vision_boxes,
)


def _answer(*frames: dict) -> str:
    return json.dumps(list(frames))


def _frame(index: int, *, text: list | None = None, faces: list | None = None) -> dict:
    return {"index": index, "text": text or [], "faces": faces or []}


def _box(**fields) -> dict:
    return {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4, "confidence": 0.9, **fields}


def _runner(stdout: str = "[]", returncode: int = 0):
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, returncode, stdout, "")

    run.calls = calls  # type: ignore[attr-defined]
    return run


# --- the helper itself -------------------------------------------------------


def test_the_helper_source_is_in_the_repository() -> None:
    assert VISION_BOXES_SOURCE.is_file()
    source = VISION_BOXES_SOURCE.read_text(encoding="utf-8")
    assert "VNRecognizeTextRequest" in source
    assert "VNDetectFaceRectanglesRequest" in source


def test_the_helper_is_compiled_into_a_private_cache(tmp_path: Path) -> None:
    """The build refuses anywhere the repository would publish."""
    with pytest.raises(ValueError):
        build_vision_boxes_probe(Path("app/vision-boxes"), runner=_runner())


# --- reading what it says ----------------------------------------------------


def test_boxes_and_their_text_are_parsed() -> None:
    raw = _answer(_frame(0, text=[_box(text="ABC123")], faces=[_box()]))

    frames = parse_vision_boxes(raw)

    assert len(frames) == 1
    assert frames[0].text[0].text == "ABC123"
    assert frames[0].faces[0].height == pytest.approx(0.4)


def test_an_answer_that_is_not_json_is_refused() -> None:
    with pytest.raises(AppleVisionError):
        parse_vision_boxes("<html>no</html>")


def test_an_answer_that_is_not_a_list_of_frames_is_refused() -> None:
    with pytest.raises(AppleVisionError):
        parse_vision_boxes('{"index": 0}')
    with pytest.raises(AppleVisionError):
        parse_vision_boxes("[1, 2]")


def test_a_frame_missing_its_index_is_refused() -> None:
    with pytest.raises(AppleVisionError):
        parse_vision_boxes(json.dumps([{"text": [], "faces": []}]))


def test_a_box_with_no_size_is_refused() -> None:
    with pytest.raises(AppleVisionError):
        parse_vision_boxes(_answer(_frame(0, text=[_box(width=0.0)])))


def test_a_confidence_outside_zero_to_one_is_refused() -> None:
    with pytest.raises(AppleVisionError):
        VisionBox(x=0.0, y=0.0, width=0.1, height=0.1, confidence=1.5)


def test_a_negative_frame_index_is_refused() -> None:
    with pytest.raises(AppleVisionError):
        FrameBoxes(index=-1)


# --- asking it ----------------------------------------------------------------


def test_no_images_is_no_question_asked(tmp_path: Path) -> None:
    run = _runner()

    assert detect_boxes((), tmp_path / "probe", runner=run) == ()
    assert run.calls == []  # type: ignore[attr-defined]


def test_a_missing_helper_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AppleVisionError):
        detect_boxes((tmp_path / "a.jpg",), tmp_path / "absent", runner=_runner())


def test_a_helper_that_fails_is_not_read(tmp_path: Path) -> None:
    probe = tmp_path / "probe"
    probe.write_bytes(b"x")

    with pytest.raises(AppleVisionError):
        detect_boxes((tmp_path / "a.jpg",), probe, runner=_runner(returncode=1))


def test_an_answer_about_a_different_number_of_images_is_refused(tmp_path: Path) -> None:
    """A helper that skipped an image would silently shift every frame's time."""
    probe = tmp_path / "probe"
    probe.write_bytes(b"x")

    with pytest.raises(AppleVisionError):
        detect_boxes(
            (tmp_path / "a.jpg", tmp_path / "b.jpg"), probe, runner=_runner(_answer(_frame(0)))
        )


def test_batches_count_the_frame_index_across_them_all(tmp_path: Path) -> None:
    probe = tmp_path / "probe"
    probe.write_bytes(b"x")
    images = tuple(tmp_path / f"{index}.jpg" for index in range(4))
    run = _runner(_answer(_frame(0), _frame(1)))

    frames = detect_boxes_in_batches(images, probe, batch=2, runner=run)

    assert [frame.index for frame in frames] == [0, 1, 2, 3]
    assert len(run.calls) == 2  # type: ignore[attr-defined]


def test_a_batch_of_nothing_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AppleVisionError):
        detect_boxes_in_batches((tmp_path / "a.jpg",), tmp_path / "probe", batch=0)
