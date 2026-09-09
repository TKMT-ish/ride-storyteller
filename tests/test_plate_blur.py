"""Synthetic-fixture tests for blurring plates and finding faces. Nothing runs Vision."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

import app.plate_blur as module
from app.plate_blur import (
    PlateBlurError,
    Region,
    _at_least,
    as_video_box,
    blur_command,
    blur_filter,
    blur_plates,
    blur_until_clean,
    clear_of_faces,
    face_seconds,
    inspect_footage,
    looks_like_a_plate,
    main,
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


# --- a region's own shape ---------------------------------------------------------


def test_a_region_must_cover_a_positive_span_of_time() -> None:
    with pytest.raises(PlateBlurError):
        Region(start_s=1.0, end_s=1.0, x=0, y=0, width=1, height=1)
    with pytest.raises(PlateBlurError):
        Region(start_s=2.0, end_s=1.0, x=0, y=0, width=1, height=1)


def test_a_region_must_have_a_positive_size() -> None:
    with pytest.raises(PlateBlurError):
        Region(start_s=0.0, end_s=1.0, x=0, y=0, width=0, height=1)
    with pytest.raises(PlateBlurError):
        Region(start_s=0.0, end_s=1.0, x=0, y=0, width=1, height=0)


def test_a_region_must_lie_inside_the_frame() -> None:
    with pytest.raises(PlateBlurError):
        Region(start_s=0.0, end_s=1.0, x=-1, y=0, width=1, height=1)
    with pytest.raises(PlateBlurError):
        Region(start_s=0.0, end_s=1.0, x=0, y=-1, width=1, height=1)


def test_regions_touching_at_the_instant_they_change_still_overlap() -> None:
    """`end_s < other.start_s` is a strict inequality, so a region that ends
    exactly when another starts is treated as sharing that instant."""
    before = Region(start_s=0.0, end_s=1.0, x=0, y=0, width=10, height=10)
    after = Region(start_s=1.0, end_s=2.0, x=0, y=0, width=10, height=10)

    assert before.overlaps(after)


def test_regions_apart_in_space_do_not_overlap_even_at_the_same_time() -> None:
    left = Region(start_s=0.0, end_s=1.0, x=0, y=0, width=10, height=10)
    right = Region(start_s=0.0, end_s=1.0, x=100, y=100, width=10, height=10)

    assert not left.overlaps(right)


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


def test_negative_padding_is_refused() -> None:
    with pytest.raises(PlateBlurError):
        as_video_box(_text("ABC123"), width=100, height=100, pad_share=-0.1)
    with pytest.raises(PlateBlurError):
        as_video_box(_text("ABC123"), width=100, height=100, pad_pixels=-1)


def test_a_box_wholly_outside_the_frame_is_refused() -> None:
    """A box Vision placed past the edge pads to nothing inside the picture."""
    with pytest.raises(PlateBlurError):
        as_video_box(_text("ABC123", x=1.5), width=100, height=100)


def test_a_box_smaller_than_the_minimum_is_grown_about_its_own_middle() -> None:
    """`_at_least` clamps the minimum to the frame rather than overflow it."""
    x, y, right, bottom = _at_least(4, 4, 6, 6, width=10, height=10, least=(48, 28))

    assert (x, y, right, bottom) == (0, 0, 10, 10)


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


def test_a_hold_of_zero_is_refused() -> None:
    with pytest.raises(PlateBlurError):
        plate_regions((), fps=10.0, width=1920, height=1080, hold_s=0.0)


# --- where the faces are ---------------------------------------------------------


def test_a_face_big_enough_to_recognise_is_reported() -> None:
    frames = (
        FrameBoxes(index=0, faces=(_face(height=0.05),)),
        FrameBoxes(index=10, faces=(_face(height=0.001),)),
        FrameBoxes(index=20),
    )

    assert face_seconds(frames, fps=10.0) == (0.0,)


def test_a_sampling_rate_of_zero_is_refused_for_faces_too() -> None:
    with pytest.raises(PlateBlurError):
        face_seconds((), fps=0.0)


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


def test_the_stretch_and_the_whole_must_be_positive() -> None:
    with pytest.raises(PlateBlurError):
        clear_of_faces((), fps=10.0, length_s=0.0, total_s=10.0)
    with pytest.raises(PlateBlurError):
        clear_of_faces((), fps=10.0, length_s=1.0, total_s=0.0)


def test_two_faces_within_the_margin_of_each_other_do_not_reopen_a_stretch() -> None:
    """`start` only ever moves forward, so a face seen again inside the margin
    of the last one does not carve out a spurious clear stretch before it."""
    frames = (
        FrameBoxes(index=100, faces=(_face(),)),  # at 10.0s
        FrameBoxes(index=105, faces=(_face(),)),  # at 10.5s, inside the 1.0s margin
    )

    spans = clear_of_faces(frames, fps=10.0, length_s=5.0, total_s=30.0)

    assert spans == ((0.0, 9.0), (11.5, 30.0))


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


def test_two_regions_chain_through_the_same_base_picture() -> None:
    """Each region overlays onto the previous stage's output, not the raw base,
    so a second plate's blur does not erase the first's."""
    first = Region(start_s=1.0, end_s=2.0, x=10, y=20, width=120, height=80)
    second = Region(start_s=3.0, end_s=4.0, x=200, y=200, width=100, height=60)

    graph = blur_filter((first, second), radius=9)

    assert "split=3" in graph
    assert "[base0][blur0]overlay=10:20:enable='between(t,1.000,2.000)'[over0]" in graph
    assert "[over0][blur1]overlay=200:200:enable='between(t,3.000,4.000)'[over1]" in graph
    assert graph.endswith("[over1]null[out]")


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


def test_a_symlinked_source_is_refused(tmp_path: Path) -> None:
    """`is_file()` alone follows a symlink to the real footage; the check
    beside it is what actually stops one."""
    real = tmp_path / "real.mp4"
    real.write_bytes(b"x")
    link = tmp_path / "in.mp4"
    link.symlink_to(real)

    with pytest.raises(PlateBlurError):
        blur_plates(link, tmp_path / "out.mp4", ())


def test_ffmpeg_failing_to_start_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")

    def cannot_run(command, **kwargs):
        raise OSError("no ffmpeg on this machine")

    with pytest.raises(PlateBlurError):
        blur_plates(source, tmp_path / "out.mp4", (), runner=cannot_run)
    assert not list(tmp_path.glob("*.part*"))


def test_a_clean_exit_that_wrote_nothing_is_still_refused(tmp_path: Path) -> None:
    """ffmpeg can return zero without writing the file it was asked for."""
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")

    with pytest.raises(PlateBlurError):
        blur_plates(source, tmp_path / "out.mp4", (), runner=_runner(returncode=0))


# --- asking about the footage -------------------------------------------------------


def test_the_sampling_command_writes_numbered_frames(tmp_path: Path) -> None:
    command = sample_command(Path("in.mp4"), tmp_path, fps=10.0, width=1280)

    assert "fps=10.0,scale=1280:-2" in command
    assert command[-1].endswith("f%06d.jpg")


def test_the_sampling_rate_and_width_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(PlateBlurError):
        sample_command(Path("in.mp4"), tmp_path, fps=0.0, width=1280)
    with pytest.raises(PlateBlurError):
        sample_command(Path("in.mp4"), tmp_path, fps=10.0, width=0)


def test_the_picture_size_comes_from_ffprobe() -> None:
    assert video_size(Path("in.mp4"), runner=_runner(stdout="1920x1080\n")) == (1920, 1080)


def test_a_size_ffprobe_cannot_report_is_refused() -> None:
    with pytest.raises(PlateBlurError):
        video_size(Path("in.mp4"), runner=_runner(stdout="what?\n"))
    with pytest.raises(PlateBlurError):
        video_size(Path("in.mp4"), runner=_runner(returncode=1))


def test_ffprobe_failing_to_start_is_refused() -> None:
    def cannot_run(command, **kwargs):
        raise FileNotFoundError("no ffprobe on this machine")

    with pytest.raises(PlateBlurError):
        video_size(Path("in.mp4"), runner=cannot_run)


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


# --- the whole "sample, read, judge" walk over one file ---------------------------
#
# `inspect_footage` is the only place that actually wires `video_size`,
# `sample_command` and `detect_boxes_in_batches` together over a real runner;
# every test above exercises those parts alone. `detect_boxes_in_batches` is
# stubbed out here (it shells out to the compiled Vision helper), but the
# ffprobe/ffmpeg calls run through the same fake runner `blur_plates` above
# uses, and the frames it is asked to write are written for real so the
# `work.glob("f*.jpg")` the function does is exercised too.


def _fake_ffmpeg_ffprobe_runner(frame_names: Sequence[str] = ("f000001.jpg",)):
    def run(command, **kwargs):
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, "1920x1080\n", "")
        directory = Path(command[-1]).parent
        for name in frame_names:
            (directory / name).write_bytes(b"x")
        return subprocess.CompletedProcess(command, 0, "", "")

    return run


def test_inspect_footage_wires_sampling_ffprobe_and_the_reader_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = (
        FrameBoxes(index=1, text=(_text("ABC123"),)),
        FrameBoxes(index=2, faces=(_face(),)),
    )
    monkeypatch.setattr(module, "detect_boxes_in_batches", lambda frames, probe, runner=None: found)

    regions, faces = inspect_footage(
        tmp_path / "in.mp4",
        probe_path=tmp_path / "probe",
        work=tmp_path / "work",
        fps=10.0,
        runner=_fake_ffmpeg_ffprobe_runner(),
    )

    assert len(regions) == 1
    assert faces == (0.2,)


def test_inspect_footage_refuses_when_sampling_writes_no_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "detect_boxes_in_batches", lambda frames, probe, runner=None: ())

    with pytest.raises(PlateBlurError):
        inspect_footage(
            tmp_path / "in.mp4",
            probe_path=tmp_path / "probe",
            work=tmp_path / "work",
            fps=10.0,
            runner=_fake_ffmpeg_ffprobe_runner(frame_names=()),
        )


def test_inspect_footage_refuses_when_sampling_itself_fails(tmp_path: Path) -> None:
    def failing(command, **kwargs):
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, "1920x1080\n", "")
        return subprocess.CompletedProcess(command, 1, "", "no ffmpeg")

    with pytest.raises(PlateBlurError):
        inspect_footage(
            tmp_path / "in.mp4",
            probe_path=tmp_path / "probe",
            work=tmp_path / "work",
            fps=10.0,
            runner=failing,
        )


# --- the command line -------------------------------------------------------------


def test_main_blurs_the_file_and_reports_the_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")
    output = tmp_path / "out.mp4"
    probe = tmp_path / "probe"
    probe.write_bytes(b"p")
    calls: list[tuple[Path, Path, tuple]] = []

    def fake_blur(src, out, regions, **kwargs):
        calls.append((src, out, regions))
        out.write_bytes(b"y")
        return out

    monkeypatch.setattr(module, "inspect_footage", lambda *a, **k: ((), ()))
    monkeypatch.setattr(module, "blur_plates", fake_blur)

    rc = main([str(source), str(output), "--probe", str(probe), "--passes", "1"])

    assert rc == 0
    assert output.exists()
    assert calls == [(source, output, ())]


def test_main_refuses_footage_a_face_appears_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")
    output = tmp_path / "out.mp4"
    probe = tmp_path / "probe"
    probe.write_bytes(b"p")

    def not_reached(*a, **k):
        raise AssertionError("blur_plates must not run when a face was found")

    monkeypatch.setattr(module, "inspect_footage", lambda *a, **k: ((), (1.0, 2.0)))
    monkeypatch.setattr(module, "blur_plates", not_reached)

    rc = main([str(source), str(output), "--probe", str(probe), "--passes", "1"])

    assert rc == 1
    assert not output.exists()


def test_main_allow_faces_writes_the_file_anyway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")
    output = tmp_path / "out.mp4"
    probe = tmp_path / "probe"
    probe.write_bytes(b"p")

    def fake_blur(src, out, regions, **k):
        out.write_bytes(b"y")
        return out

    monkeypatch.setattr(module, "inspect_footage", lambda *a, **k: ((), (1.0,)))
    monkeypatch.setattr(module, "blur_plates", fake_blur)

    rc = main([str(source), str(output), "--probe", str(probe), "--passes", "1", "--allow-faces"])

    assert rc == 0
    assert output.exists()


def test_main_builds_the_probe_when_it_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")
    output = tmp_path / "out.mp4"
    probe = tmp_path / "probe"  # deliberately not created
    built: list[Path] = []

    def fake_build(path):
        built.append(path)
        path.write_bytes(b"p")
        return path

    def fake_blur(src, out, regions, **k):
        out.write_bytes(b"y")
        return out

    monkeypatch.setattr(module, "build_vision_boxes_probe", fake_build)
    monkeypatch.setattr(module, "inspect_footage", lambda *a, **k: ((), ()))
    monkeypatch.setattr(module, "blur_plates", fake_blur)

    rc = main([str(source), str(output), "--probe", str(probe), "--passes", "1"])

    assert rc == 0
    assert built == [probe]


def test_main_reports_a_plate_blur_error_and_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")
    output = tmp_path / "out.mp4"
    probe = tmp_path / "probe"
    probe.write_bytes(b"p")

    def refuses(*a, **k):
        raise PlateBlurError("the footage produced no frames to inspect")

    monkeypatch.setattr(module, "inspect_footage", refuses)

    rc = main([str(source), str(output), "--probe", str(probe), "--passes", "1"])

    assert rc == 1
    assert not output.exists()
