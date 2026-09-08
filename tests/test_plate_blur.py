"""Synthetic-fixture tests for blurring plates and finding faces. Nothing runs Vision."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.plate_blur import (
    PlateBlurError,
    Region,
    as_video_box,
    blur_command,
    blur_filter,
    blur_plates,
    blur_until_clean,
    clear_of_faces,
    face_seconds,
    looks_like_a_plate,
    plate_regions,
    radius_for,
    sample_command,
    video_size,
)
from app.video.vision_boxes import FrameBoxes, VisionBox


def _text(said: str, *, x: float = 0.5, y: float = 0.5, w: float = 0.05, h: float = 0.02):
    return VisionBox(x=x, y=y, width=w, height=h, confidence=1.0, text=said)


def _face(*, height: float = 0.05, x: float = 0.5, y: float = 0.5):
    return VisionBox(x=x, y=y, width=height, height=height, confidence=0.9)


def _runner(returncode: int = 0, stdout: str = ""):
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, returncode, stdout, "")

    run.calls = calls  # type: ignore[attr-defined]
    return run


# --- what a plate looks like ----------------------------------------------------


def test_the_plates_read_off_one_real_film_are_recognised() -> None:
    """Every string here was read by Vision from a real ride's own footage."""
    for said in ("QHF65", "FUH958", "FUH950", "ANT-09", "NNT685", "DWE65"):
        assert looks_like_a_plate(said), said


def test_the_signs_read_off_the_same_film_are_not() -> None:
    """Vision found 1,031 pieces of text in that film and 17 were plates."""
    for said in ("73km", "34km", "STOP", "100", "Kingsford Nth", "KFC", "SH 1", "GIVE WAY"):
        assert not looks_like_a_plate(said), said


def test_garbled_sign_text_is_not_a_plate() -> None:
    """A film cut from blurred clips still produced these, and a looser rule
    counted them as plates and blurred a road sign for nothing."""
    for said in ("3ta3", "Esk StI", "Ouos", "1VINANN", "STIRING", "SPOT"):
        assert not looks_like_a_plate(said), said


def test_the_letters_and_the_digits_have_to_be_contiguous() -> None:
    assert looks_like_a_plate("ABC123")
    assert looks_like_a_plate("123ABC")
    assert not looks_like_a_plate("A1B2C3")
    assert not looks_like_a_plate("1A23B")


def test_a_plate_needs_both_letters_and_digits() -> None:
    assert not looks_like_a_plate("ABCDEF")
    assert not looks_like_a_plate("123456")
    assert not looks_like_a_plate("A1")


# --- from Vision's coordinates to the video's -----------------------------------


def test_the_box_is_flipped_because_vision_counts_from_the_bottom() -> None:
    """Vision's origin is the bottom left; a video filter counts from the top."""
    box = VisionBox(x=0.25, y=0.75, width=0.1, height=0.1, confidence=1.0, text="ABC123")

    x, y, width, height = as_video_box(box, width=1000, height=1000, pad_share=0.0, pad_pixels=0)

    assert (x, y) == (250, 150)
    assert (width, height) == (100, 100)


def test_the_box_is_padded_clamped_and_even() -> None:
    box = VisionBox(x=0.0, y=0.0, width=0.02, height=0.02, confidence=1.0, text="ABC123")

    x, y, width, height = as_video_box(box, width=999, height=999)

    assert x == 0 and y >= 0
    assert width % 2 == 0 and height % 2 == 0
    assert x + width <= 999 and y + height <= 999


def test_a_frame_with_no_size_is_refused() -> None:
    with pytest.raises(PlateBlurError):
        as_video_box(_text("ABC123"), width=0, height=100)


# --- what to blur ----------------------------------------------------------------


def test_only_the_plate_shaped_text_becomes_a_region() -> None:
    frames = (FrameBoxes(index=0, text=(_text("ABC123"), _text("GIVE WAY"), _text("73km"))),)

    regions = plate_regions(frames, fps=10.0, width=1920, height=1080)

    assert len(regions) == 1


def test_a_plate_seen_once_is_blurred_either_side_of_the_frame_it_was_seen_in() -> None:
    """The frames between samples are never looked at, so the hold covers them."""
    frames = (FrameBoxes(index=50, text=(_text("ABC123"),)),)

    region = plate_regions(frames, fps=10.0, width=1920, height=1080, hold_s=0.6)[0]

    assert region.start_s == pytest.approx(4.4)
    assert region.end_s == pytest.approx(5.6)


def test_the_same_plate_across_frames_becomes_one_widening_region() -> None:
    frames = (
        FrameBoxes(index=0, text=(_text("ABC123", x=0.50),)),
        FrameBoxes(index=1, text=(_text("ABC123", x=0.52),)),
        FrameBoxes(index=2, text=(_text("ABC123", x=0.54),)),
    )

    regions = plate_regions(frames, fps=10.0, width=1920, height=1080)

    assert len(regions) == 1
    assert regions[0].width > int(0.05 * 1920)


def test_plates_far_apart_stay_separate() -> None:
    frames = (
        FrameBoxes(index=0, text=(_text("ABC123", x=0.05, y=0.9),)),
        FrameBoxes(index=300, text=(_text("XYZ789", x=0.80, y=0.1),)),
    )

    assert len(plate_regions(frames, fps=10.0, width=1920, height=1080)) == 2


def test_a_sampling_rate_of_zero_is_refused() -> None:
    with pytest.raises(PlateBlurError):
        plate_regions((), fps=0.0, width=1920, height=1080)


# --- where the faces are ---------------------------------------------------------


def test_a_face_big_enough_to_recognise_is_reported() -> None:
    frames = (
        FrameBoxes(index=0, faces=(_face(height=0.05),)),
        FrameBoxes(index=10, faces=(_face(height=0.001),)),
        FrameBoxes(index=20),
    )

    assert face_seconds(frames, fps=10.0) == (0.0,)


def test_the_stretches_between_faces_are_what_may_be_published() -> None:
    """The owner's rule (2026-09-08): drop that footage rather than blur the person."""
    frames = (FrameBoxes(index=1000, faces=(_face(),)),)

    spans = clear_of_faces(frames, fps=10.0, length_s=30.0, total_s=300.0)

    assert spans == ((0.0, 99.0), (101.0, 300.0))


def test_a_film_with_no_face_is_one_clear_stretch() -> None:
    assert clear_of_faces((), fps=10.0, length_s=30.0, total_s=300.0) == ((0.0, 300.0),)


def test_a_stretch_shorter_than_asked_for_is_not_offered() -> None:
    frames = (FrameBoxes(index=100, faces=(_face(),)),)

    assert clear_of_faces(frames, fps=10.0, length_s=60.0, total_s=70.0) == ()


# --- the filter graph -------------------------------------------------------------


def test_nothing_to_blur_is_an_empty_graph_and_a_copy() -> None:
    assert blur_filter(()) == ""
    command = blur_command(Path("in.mp4"), Path("out.mp4"), ())
    assert "-c" in command and "copy" in command
    assert "-filter_complex" not in command


def test_each_region_is_cropped_blurred_and_overlaid_for_its_own_seconds() -> None:
    """boxblur alone would soften the whole picture, not one number plate."""
    region = Region(start_s=1.0, end_s=2.0, x=10, y=20, width=120, height=80)

    graph = blur_filter((region,), radius=9)

    assert "split=2" in graph
    assert "crop=120:80:10:20" in graph
    assert "boxblur=9" in graph
    assert "overlay=10:20:enable='between(t,1.000,2.000)'" in graph
    assert graph.endswith("[out]")


def test_a_small_region_takes_the_strongest_blur_it_can_hold() -> None:
    """boxblur refuses a radius reaching past the middle of the chroma plane,
    which on a 4:2:0 stream is a quarter of the region."""
    small = Region(start_s=0.0, end_s=1.0, x=0, y=0, width=48, height=28)

    assert radius_for(small, wanted=12) == 6
    assert radius_for(Region(start_s=0.0, end_s=1.0, x=0, y=0, width=4, height=4)) == 1
    assert "boxblur=6:2" in blur_filter((small,), radius=12)


def test_a_plate_box_is_grown_to_a_size_worth_blurring() -> None:
    """A box hugging four characters leaves a legible edge and too little room
    for a strong blur."""
    tiny = VisionBox(x=0.5, y=0.5, width=0.004, height=0.002, confidence=1.0, text="ABC123")

    _, _, width, height = as_video_box(tiny, width=1920, height=1080)

    assert width >= 48 and height >= 28


def test_the_command_keeps_the_sound_and_names_the_blurred_stream() -> None:
    region = Region(start_s=1.0, end_s=2.0, x=10, y=20, width=30, height=40)

    command = blur_command(Path("in.mp4"), Path("out.mp4"), (region,))

    assert "[out]" in command
    assert "0:a?" in command
    assert "copy" in command


def test_a_radius_below_one_pixel_is_refused() -> None:
    with pytest.raises(PlateBlurError):
        blur_filter((Region(start_s=0.0, end_s=1.0, x=0, y=0, width=2, height=2),), radius=0)


# --- writing the file --------------------------------------------------------------


def test_the_blurred_copy_is_written_whole_or_not_at_all(tmp_path: Path) -> None:
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")
    output = tmp_path / "out.mp4"

    with pytest.raises(PlateBlurError):
        blur_plates(source, output, (), runner=_runner(returncode=1))

    assert not output.exists()
    assert not list(tmp_path.glob("*.part*"))


def test_the_part_file_keeps_the_real_suffix(tmp_path: Path) -> None:
    """ffmpeg picks its container from the name, and ".mp4.part" is not one."""
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")
    run = _runner()

    def writing(command, **kwargs):
        Path(command[-1]).write_bytes(b"y")
        return run(command, **kwargs)

    blur_plates(source, tmp_path / "out.mp4", (), runner=writing)

    assert (tmp_path / "out.mp4").is_file()
    assert run.calls[0][-1].endswith(".part.mp4")  # type: ignore[attr-defined]


def test_footage_that_is_not_there_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PlateBlurError):
        blur_plates(tmp_path / "absent.mp4", tmp_path / "out.mp4", ())


# --- asking about the footage -------------------------------------------------------


def test_the_sampling_command_writes_numbered_frames(tmp_path: Path) -> None:
    command = sample_command(Path("in.mp4"), tmp_path, fps=10.0, width=1280)

    assert "fps=10.0,scale=1280:-2" in command
    assert command[-1].endswith("f%06d.jpg")


def test_the_picture_size_comes_from_ffprobe() -> None:
    assert video_size(Path("in.mp4"), runner=_runner(stdout="1920x1080\n")) == (1920, 1080)


def test_a_size_ffprobe_cannot_report_is_refused() -> None:
    with pytest.raises(PlateBlurError):
        video_size(Path("in.mp4"), runner=_runner(stdout="what?\n"))
    with pytest.raises(PlateBlurError):
        video_size(Path("in.mp4"), runner=_runner(returncode=1))


def test_each_pass_blurs_the_original_with_everything_found_so_far(tmp_path: Path) -> None:
    """Iterating on the blurred copy would re-encode once per pass and lose a
    little each time; a reader that missed a plate in one encode can read it in
    the next, so the regions accumulate and the source is blurred once a pass."""
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")
    output = tmp_path / "out.mp4"
    sources_blurred: list[str] = []
    seen = [
        (FrameBoxes(index=0, text=(_text("ABC123", x=0.1),)),),
        (FrameBoxes(index=0, text=(_text("XYZ789", x=0.8),)),),
        (),
    ]

    def looks(*args, **kwargs):
        return seen.pop(0) if seen else ()

    def blur(source_path, output_path, regions, **kwargs):
        sources_blurred.append(str(source_path))
        output_path.write_bytes(b"y")
        blur.regions = list(regions)  # type: ignore[attr-defined]
        return output_path

    import app.plate_blur as module

    original_inspect, original_blur = module.inspect_footage, module.blur_plates
    module.inspect_footage = lambda *a, **k: (  # type: ignore[assignment]
        plate_regions(looks(), fps=10.0, width=1920, height=1080),
        (),
    )
    module.blur_plates = blur  # type: ignore[assignment]
    try:
        regions, faces = module.blur_until_clean(
            source, output, probe_path=tmp_path / "p", work=tmp_path / "w", passes=4
        )
    finally:
        module.inspect_footage, module.blur_plates = original_inspect, original_blur

    # Two plates found across two passes; a third pass found nothing and stopped.
    assert len(regions) == 2
    assert faces == ()
    # Every blur read the original, never the blurred copy.
    assert set(sources_blurred) == {str(source)}
    assert len(sources_blurred) == 2


def test_a_run_of_no_passes_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PlateBlurError):
        blur_until_clean(
            tmp_path / "in.mp4", tmp_path / "out.mp4", probe_path=tmp_path, work=tmp_path, passes=0
        )


def test_a_single_frames_read_can_be_asked_to_reproduce() -> None:
    """Blurring wants one sighting; checking wants two, because a read that
    does not reproduce is the reader's noise and a check that counts it never
    reports a clean film."""
    once = (FrameBoxes(index=0, text=(_text("ABC123", x=0.1),)),)
    twice = (
        FrameBoxes(index=0, text=(_text("ABC123", x=0.1),)),
        FrameBoxes(index=1, text=(_text("ABC123", x=0.1),)),
    )

    assert len(plate_regions(once, fps=10.0, width=1920, height=1080)) == 1
    assert plate_regions(once, fps=10.0, width=1920, height=1080, minimum_hits=2) == ()
    assert len(plate_regions(twice, fps=10.0, width=1920, height=1080, minimum_hits=2)) == 1
