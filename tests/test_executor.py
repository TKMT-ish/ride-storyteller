"""Tests for ScriptExecutor (app/executor.py).

Focus: DirectorScript → ResolvedCandidateClip resolution, ordering,
fail-closed conditions, and hand-off to build_ffmpeg_render_plan.

Deliberately avoids re-testing build_ffmpeg_render_plan internals —
those are covered by tests/test_render_plan.py.  The tests here cover
the connection layer only.
"""

from __future__ import annotations

import pytest

from app.director import (
    DirectorMetadata,
    DirectorScript,
    NarrativeArc,
    Scene,
    SceneClip,
)
from app.edit.render_plan import RenderPlanStatus
from app.executor import ScriptExecutor
from app.video.catalog import ResolvedCandidateClip, VideoMatchStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOLERANCE = 1e-6


def _resolved(
    event_id: str,
    *,
    asset_id: str = "asset-abc",
    file_name: str = "GX010001.MP4",
    start_offset_s: float = 10.0,
    end_offset_s: float = 40.0,
    chapter_id: str = "chapter_01",
) -> ResolvedCandidateClip:
    return ResolvedCandidateClip(
        chapter_id=chapter_id,
        event_id=event_id,
        status=VideoMatchStatus.MATCHED,
        asset_id=asset_id,
        file_name=file_name,
        start_offset_s=start_offset_s,
        end_offset_s=end_offset_s,
        reason="test",
    )


def _scene_clip(
    event_id: str,
    *,
    source_asset_id: str = "asset-abc",
    source_start_sec: float = 10.0,
    source_end_sec: float = 40.0,
) -> SceneClip:
    return SceneClip(
        event_id=event_id,
        source_asset_id=source_asset_id,
        source_start_sec=source_start_sec,
        source_end_sec=source_end_sec,
    )


def _scene(
    arc: NarrativeArc,
    clips: tuple[SceneClip, ...],
    transition_type: str = "cut",
) -> Scene:
    return Scene(
        scene_id=f"scene_{arc.value}",
        scene_type=arc,
        clips=clips,
        transition_type=transition_type,
        overlay_text=None,
    )


def _metadata(
    n_in: int = 1,
    n_used: int = 1,
    arc_names: tuple[str, ...] = ("hook",),
) -> DirectorMetadata:
    return DirectorMetadata(
        composer="test",
        event_count_in=n_in,
        event_count_used=n_used,
        arc_names=arc_names,
    )


def _script(scenes: tuple[Scene, ...], **kw: object) -> DirectorScript:
    metadata_kwargs = {
        "n_used": sum(len(scene.clips) for scene in scenes),
        "arc_names": tuple(scene.scene_type.value for scene in scenes),
        **kw,
    }
    return DirectorScript(scenes=scenes, metadata=_metadata(**metadata_kwargs))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. Single clip — happy path with evidence confirmed
# ---------------------------------------------------------------------------

def test_single_confirmed_clip_produces_ready_for_ffmpeg() -> None:
    rc = _resolved("evt_001")
    sc = _scene_clip("evt_001")
    script = _script((_scene(NarrativeArc.HOOK, (sc,)),))

    executor = ScriptExecutor()
    plan = executor.execute(
        script,
        (rc,),
        visual_evidence_confirmed_event_ids=("evt_001",),
    )

    assert plan.status == RenderPlanStatus.READY_FOR_FFMPEG
    assert plan.command is not None
    assert plan.command[0] == "ffmpeg"


def test_single_clip_without_confirmation_produces_needs_human_review() -> None:
    rc = _resolved("evt_001")
    sc = _scene_clip("evt_001")
    script = _script((_scene(NarrativeArc.HOOK, (sc,)),))

    plan = ScriptExecutor().execute(script, (rc,))  # no confirmed IDs

    assert plan.status == RenderPlanStatus.NEEDS_HUMAN_REVIEW
    assert plan.command is None


# ---------------------------------------------------------------------------
# 2. Director-determined scene order is preserved
# ---------------------------------------------------------------------------

def test_scene_order_is_preserved_in_render_plan() -> None:
    """FFmpeg -i inputs must follow DirectorScript scene order, not catalog order."""
    rc1 = _resolved("evt_first",  file_name="GX010001.MP4", start_offset_s=5.0,  end_offset_s=20.0)
    rc2 = _resolved("evt_second", file_name="GX010002.MP4", start_offset_s=30.0, end_offset_s=50.0)

    # Director says: second → first (reverse of catalog / chronological order)
    script = _script((
        _scene(NarrativeArc.HOOK, (
            _scene_clip("evt_second", source_start_sec=30.0, source_end_sec=50.0),
        )),
        _scene(NarrativeArc.RESOLUTION, (
            _scene_clip("evt_first", source_start_sec=5.0, source_end_sec=20.0),
        )),
    ), n_in=2, n_used=2)

    plan = ScriptExecutor().execute(
        script,
        (rc1, rc2),  # catalog order is first, second
        visual_evidence_confirmed_event_ids=("evt_first", "evt_second"),
    )

    assert plan.command is not None
    # GX010002 (second scene in Director order) must appear before GX010001
    assert plan.command.index("GX010002.MP4") < plan.command.index("GX010001.MP4")


def test_clip_order_within_scene_is_preserved() -> None:
    """Clips within a single scene must appear in scene.clips order."""
    rc_a = _resolved("evt_a", file_name="GX010001.MP4", start_offset_s=5.0,  end_offset_s=15.0)
    rc_b = _resolved("evt_b", file_name="GX010002.MP4", start_offset_s=20.0, end_offset_s=35.0)

    sc_a = _scene_clip("evt_a", source_start_sec=5.0,  source_end_sec=15.0)
    sc_b = _scene_clip("evt_b", source_start_sec=20.0, source_end_sec=35.0)

    script = _script((
        _scene(NarrativeArc.HOOK, (sc_a, sc_b)),
    ), n_in=2, n_used=2)

    plan = ScriptExecutor().execute(
        script,
        (rc_b, rc_a),  # reversed catalog order
        visual_evidence_confirmed_event_ids=("evt_a", "evt_b"),
    )

    assert plan.command is not None
    assert plan.command.index("GX010001.MP4") < plan.command.index("GX010002.MP4")


def test_resolved_clip_catalog_order_does_not_affect_output_order() -> None:
    """Catalog order must never override Director order."""
    rc1 = _resolved("evt_001", file_name="GX010001.MP4", start_offset_s=10.0, end_offset_s=30.0)
    rc2 = _resolved("evt_002", file_name="GX010002.MP4", start_offset_s=5.0,  end_offset_s=20.0)
    rc3 = _resolved("evt_003", file_name="GX010003.MP4", start_offset_s=35.0, end_offset_s=55.0)

    # Director order: 003, 001, 002
    script = _script((
        _scene(NarrativeArc.HOOK, (
            _scene_clip("evt_003", source_start_sec=35.0, source_end_sec=55.0),
        )),
        _scene(NarrativeArc.BUILD_UP, (
            _scene_clip("evt_001", source_start_sec=10.0, source_end_sec=30.0),
        )),
        _scene(NarrativeArc.RESOLUTION, (
            _scene_clip("evt_002", source_start_sec=5.0, source_end_sec=20.0),
        )),
    ), n_in=3, n_used=3)

    plan = ScriptExecutor().execute(
        script,
        (rc1, rc2, rc3),  # catalog order: 001, 002, 003
        visual_evidence_confirmed_event_ids=("evt_001", "evt_002", "evt_003"),
    )

    assert plan.command is not None
    pos = {fn: plan.command.index(fn) for fn in ("GX010001.MP4", "GX010002.MP4", "GX010003.MP4")}
    assert pos["GX010003.MP4"] < pos["GX010001.MP4"] < pos["GX010002.MP4"]


# ---------------------------------------------------------------------------
# 3. Fail-closed: missing ResolvedCandidateClip
# ---------------------------------------------------------------------------

def test_missing_resolved_clip_raises() -> None:
    sc = _scene_clip("evt_missing")
    script = _script((_scene(NarrativeArc.HOOK, (sc,)),))

    with pytest.raises(ValueError, match="no matching ResolvedCandidateClip"):
        ScriptExecutor().execute(script, ())


def test_partial_resolved_clips_raises_for_missing_one() -> None:
    rc_ok = _resolved("evt_ok")
    sc_ok = _scene_clip("evt_ok")
    sc_missing = _scene_clip(
        "evt_missing",
        source_asset_id="asset-xyz",
        source_start_sec=5.0,
        source_end_sec=25.0,
    )
    script = _script((
        _scene(NarrativeArc.HOOK,    (sc_ok,)),
        _scene(NarrativeArc.CLIMAX,  (sc_missing,)),
    ), n_in=2, n_used=2)

    with pytest.raises(ValueError, match="evt_missing"):
        ScriptExecutor().execute(script, (rc_ok,))


# ---------------------------------------------------------------------------
# 4. Fail-closed: duplicate event_id in DirectorScript
# ---------------------------------------------------------------------------

def test_duplicate_event_id_across_scenes_raises() -> None:
    sc1 = _scene_clip("evt_dup")
    sc2 = _scene_clip("evt_dup")
    with pytest.raises(ValueError, match="SceneClip.event_id values must be unique"):
        _script((
            _scene(NarrativeArc.HOOK,   (sc1,)),
            _scene(NarrativeArc.CLIMAX, (sc2,)),
        ), n_in=1, n_used=2)


# ---------------------------------------------------------------------------
# 5. Fail-closed: source_asset_id mismatch
# ---------------------------------------------------------------------------

def test_asset_id_mismatch_raises() -> None:
    rc = _resolved("evt_001", asset_id="correct-asset")
    sc = _scene_clip("evt_001", source_asset_id="wrong-asset")
    script = _script((_scene(NarrativeArc.HOOK, (sc,)),))

    with pytest.raises(ValueError, match="does not match"):
        ScriptExecutor().execute(script, (rc,))


# ---------------------------------------------------------------------------
# 6. Fail-closed: source_start_sec mismatch
# ---------------------------------------------------------------------------

def test_start_offset_mismatch_raises() -> None:
    rc = _resolved("evt_001", start_offset_s=10.0, end_offset_s=40.0)
    sc = _scene_clip("evt_001", source_start_sec=15.0, source_end_sec=40.0)  # wrong start
    script = _script((_scene(NarrativeArc.HOOK, (sc,)),))

    with pytest.raises(ValueError, match="start_offset_s"):
        ScriptExecutor().execute(script, (rc,))


# ---------------------------------------------------------------------------
# 7. Fail-closed: source_end_sec mismatch
# ---------------------------------------------------------------------------

def test_end_offset_mismatch_raises() -> None:
    rc = _resolved("evt_001", start_offset_s=10.0, end_offset_s=40.0)
    sc = _scene_clip("evt_001", source_start_sec=10.0, source_end_sec=35.0)  # wrong end
    script = _script((_scene(NarrativeArc.HOOK, (sc,)),))

    with pytest.raises(ValueError, match="end_offset_s"):
        ScriptExecutor().execute(script, (rc,))


# ---------------------------------------------------------------------------
# 8. Floating-point tolerance: near-identical offsets pass
# ---------------------------------------------------------------------------

def test_offsets_within_tolerance_pass() -> None:
    epsilon = 5e-7  # below _OFFSET_TOLERANCE_S (1e-6)
    rc = _resolved("evt_001", start_offset_s=10.0, end_offset_s=40.0)
    sc = _scene_clip(
        "evt_001",
        source_start_sec=10.0 + epsilon,
        source_end_sec=40.0 - epsilon,
    )
    script = _script((_scene(NarrativeArc.HOOK, (sc,)),))

    # Should not raise
    plan = ScriptExecutor().execute(
        script, (rc,), visual_evidence_confirmed_event_ids=("evt_001",)
    )
    assert plan.status == RenderPlanStatus.READY_FOR_FFMPEG


# ---------------------------------------------------------------------------
# 9. Evidence allow-list is forwarded to build_ffmpeg_render_plan unchanged
# ---------------------------------------------------------------------------

def test_unconfirmed_event_id_produces_needs_human_review() -> None:
    """ScriptExecutor must not bypass the evidence gate."""
    rc = _resolved("evt_001")
    sc = _scene_clip("evt_001")
    script = _script((_scene(NarrativeArc.HOOK, (sc,)),))

    # pass empty allow-list  → gate fires
    plan = ScriptExecutor().execute(script, (rc,), visual_evidence_confirmed_event_ids=())

    assert plan.status == RenderPlanStatus.NEEDS_HUMAN_REVIEW
    assert plan.command is None


def test_partial_confirmation_produces_needs_human_review() -> None:
    """One unconfirmed clip among multiple must block the whole render."""
    rc1 = _resolved("evt_001", file_name="GX010001.MP4", start_offset_s=5.0,  end_offset_s=20.0)
    rc2 = _resolved("evt_002", file_name="GX010002.MP4", start_offset_s=25.0, end_offset_s=45.0)
    sc1 = _scene_clip("evt_001", source_start_sec=5.0,  source_end_sec=20.0)
    sc2 = _scene_clip("evt_002", source_start_sec=25.0, source_end_sec=45.0)
    script = _script((
        _scene(NarrativeArc.HOOK,    (sc1,)),
        _scene(NarrativeArc.CLIMAX,  (sc2,)),
    ), n_in=2, n_used=2)

    # Only evt_001 confirmed
    plan = ScriptExecutor().execute(
        script,
        (rc1, rc2),
        visual_evidence_confirmed_event_ids=("evt_001",),
    )

    assert plan.status == RenderPlanStatus.NEEDS_HUMAN_REVIEW
    assert plan.command is None


def test_all_confirmed_produces_ready_for_ffmpeg() -> None:
    rc1 = _resolved("evt_001", file_name="GX010001.MP4", start_offset_s=5.0,  end_offset_s=20.0)
    rc2 = _resolved("evt_002", file_name="GX010002.MP4", start_offset_s=25.0, end_offset_s=45.0)
    sc1 = _scene_clip("evt_001", source_start_sec=5.0,  source_end_sec=20.0)
    sc2 = _scene_clip("evt_002", source_start_sec=25.0, source_end_sec=45.0)
    script = _script((
        _scene(NarrativeArc.HOOK,    (sc1,)),
        _scene(NarrativeArc.CLIMAX,  (sc2,)),
    ), n_in=2, n_used=2)

    plan = ScriptExecutor().execute(
        script,
        (rc1, rc2),
        visual_evidence_confirmed_event_ids=("evt_001", "evt_002"),
    )

    assert plan.status == RenderPlanStatus.READY_FOR_FFMPEG
    assert plan.command is not None


# ---------------------------------------------------------------------------
# 10. ScriptExecutor does not generate FFmpeg commands itself
# ---------------------------------------------------------------------------

def test_executor_does_not_produce_custom_ffmpeg_commands() -> None:
    """FfmpegRenderPlan.command must be produced by build_ffmpeg_render_plan."""
    rc = _resolved("evt_001")
    sc = _scene_clip("evt_001")
    script = _script((_scene(NarrativeArc.HOOK, (sc,)),))

    plan = ScriptExecutor().execute(
        script, (rc,), visual_evidence_confirmed_event_ids=("evt_001",)
    )

    # Verify it is the standard ffmpeg invocation, not something custom
    assert plan.command is not None
    assert plan.command[0] == "ffmpeg"
    assert "-filter_complex" in plan.command
    assert "concat" in " ".join(plan.command)


# ---------------------------------------------------------------------------
# 11. Evidence state is not changed
# ---------------------------------------------------------------------------

def test_execute_does_not_modify_resolved_clip_fields() -> None:
    rc = _resolved("evt_001", asset_id="asset-abc", start_offset_s=10.0, end_offset_s=40.0)
    sc = _scene_clip("evt_001")
    script = _script((_scene(NarrativeArc.HOOK, (sc,)),))

    ScriptExecutor().execute(
        script, (rc,), visual_evidence_confirmed_event_ids=("evt_001",)
    )

    # ResolvedCandidateClip is frozen; assert fields unchanged
    assert rc.asset_id == "asset-abc"
    assert rc.start_offset_s == pytest.approx(10.0)
    assert rc.end_offset_s == pytest.approx(40.0)
    assert rc.status == VideoMatchStatus.MATCHED


# ---------------------------------------------------------------------------
# 12. clip_count in returned plan matches number of flattened clips
# ---------------------------------------------------------------------------

def test_clip_count_matches_flattened_script_clips() -> None:
    rc1 = _resolved("evt_001", file_name="GX010001.MP4", start_offset_s=5.0,  end_offset_s=15.0)
    rc2 = _resolved("evt_002", file_name="GX010002.MP4", start_offset_s=20.0, end_offset_s=35.0)
    rc3 = _resolved("evt_003", file_name="GX010003.MP4", start_offset_s=40.0, end_offset_s=55.0)
    sc1 = _scene_clip("evt_001", source_start_sec=5.0,  source_end_sec=15.0)
    sc2 = _scene_clip("evt_002", source_start_sec=20.0, source_end_sec=35.0)
    sc3 = _scene_clip("evt_003", source_start_sec=40.0, source_end_sec=55.0)
    script = _script((
        _scene(NarrativeArc.HOOK,       (sc1, sc2)),
        _scene(NarrativeArc.RESOLUTION, (sc3,)),
    ), n_in=3, n_used=3)

    plan = ScriptExecutor().execute(
        script,
        (rc1, rc2, rc3),
        visual_evidence_confirmed_event_ids=("evt_001", "evt_002", "evt_003"),
    )

    assert plan.clip_count == 3


# ---------------------------------------------------------------------------
# 13. Two-defence-line contract: first line (Director) and second line (gate)
# ---------------------------------------------------------------------------

def test_two_defence_lines_both_active() -> None:
    """Passing confirmed UniversalEvents to Director (line 1) and confirmed
    event_ids to execute() (line 2) are both required to reach READY_FOR_FFMPEG.
    Omitting either must result in NEEDS_HUMAN_REVIEW."""
    rc = _resolved("evt_001")
    sc = _scene_clip("evt_001")
    script = _script((_scene(NarrativeArc.HOOK, (sc,)),))

    # Line 1 only (Director received confirmed events) — Line 2 missing
    plan_no_line2 = ScriptExecutor().execute(
        script, (rc,), visual_evidence_confirmed_event_ids=()
    )
    assert plan_no_line2.status == RenderPlanStatus.NEEDS_HUMAN_REVIEW
    assert plan_no_line2.command is None

    # Both lines active
    plan_both = ScriptExecutor().execute(
        script, (rc,), visual_evidence_confirmed_event_ids=("evt_001",)
    )
    assert plan_both.status == RenderPlanStatus.READY_FOR_FFMPEG
    assert plan_both.command is not None
