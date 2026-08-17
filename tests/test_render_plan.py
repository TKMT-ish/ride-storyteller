import pytest

from app.edit import build_ffmpeg_render_plan
from app.video import ResolvedCandidateClip, VideoMatchStatus


def _clip(event_id: str = "event_001") -> ResolvedCandidateClip:
    return ResolvedCandidateClip(
        chapter_id="chapter_01",
        event_id=event_id,
        status=VideoMatchStatus.MATCHED,
        asset_id="gopro_001",
        file_name="GX010001.MP4",
        start_offset_s=10,
        end_offset_s=30,
        reason="test",
    )


def test_render_plan_requires_explicit_visual_evidence_confirmation() -> None:
    plan = build_ffmpeg_render_plan((_clip(),))

    assert plan.status.value == "needs_human_review"
    assert plan.command is None
    assert "映像証拠" in " ".join(plan.reasons)


def test_render_plan_creates_an_inspectable_ffmpeg_command_after_confirmation() -> None:
    plan = build_ffmpeg_render_plan(
        (_clip(),), visual_evidence_confirmed_event_ids=("event_001",)
    )

    assert plan.status.value == "ready_for_ffmpeg"
    assert plan.command is not None
    assert plan.command[0] == "ffmpeg"
    assert "GX010001.MP4" in plan.command


def test_render_plan_rejects_source_paths() -> None:
    unsafe = ResolvedCandidateClip(
        chapter_id="chapter_01",
        event_id="event_001",
        status=VideoMatchStatus.MATCHED,
        asset_id="gopro_001",
        file_name="../private.mp4",
        start_offset_s=10,
        end_offset_s=30,
        reason="test",
    )

    with pytest.raises(ValueError, match="file names only"):
        build_ffmpeg_render_plan((unsafe,), visual_evidence_confirmed_event_ids=("event_001",))


@pytest.mark.parametrize(
    "unsafe_name",
    (
        r"folder\clip.mp4",
        r"C:\private\clip.mp4",
        "/private/clip.mp4",
        "folder/clip.mp4",
        "unsafe\x00clip.mp4",
    ),
)
def test_render_plan_rejects_cross_platform_paths(unsafe_name: str) -> None:
    unsafe = ResolvedCandidateClip(
        chapter_id="chapter_01",
        event_id="event_001",
        status=VideoMatchStatus.MATCHED,
        asset_id="gopro_001",
        file_name=unsafe_name,
        start_offset_s=10,
        end_offset_s=30,
        reason="test",
    )

    with pytest.raises(ValueError, match="file names only"):
        build_ffmpeg_render_plan((unsafe,), visual_evidence_confirmed_event_ids=("event_001",))


def test_render_plan_builds_two_clip_concat_in_input_order() -> None:
    first = _clip("event_001")
    second = ResolvedCandidateClip(
        chapter_id="chapter_02",
        event_id="event_002",
        status=VideoMatchStatus.MATCHED,
        asset_id="gopro_002",
        file_name="GX010002.MP4",
        start_offset_s=5,
        end_offset_s=20,
        reason="test",
    )

    plan = build_ffmpeg_render_plan(
        (first, second),
        visual_evidence_confirmed_event_ids=("event_001", "event_002"),
    )

    assert plan.command is not None
    assert plan.command.count("-i") == 2
    assert plan.command.index("GX010001.MP4") < plan.command.index("GX010002.MP4")
    assert "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]" in plan.command
