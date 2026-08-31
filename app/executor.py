"""ScriptExecutor: thin adapter from DirectorScript to FfmpegRenderPlan.

This module connects the Director layer to the existing FFmpeg render-plan
builder.  It owns no rendering logic of its own; all FFmpeg command generation
and the second-line-of-defence evidence gate remain inside
``build_ffmpeg_render_plan``.

Responsibilities
----------------
* Flatten ``DirectorScript.scenes → clips`` in Director-determined order.
* Resolve each ``SceneClip.event_id`` to a ``ResolvedCandidateClip`` supplied
  by the caller.
* Validate that the resolved clip's source identity matches the values that
  the Director carried forward from ``UniversalEvent``.
* Forward the ordered clip tuple and the caller-supplied
  ``visual_evidence_confirmed_event_ids`` allow-list directly to
  ``build_ffmpeg_render_plan``.

What ScriptExecutor does NOT do
--------------------------------
* It does not re-rank or reorder clips.
* It does not generate FFmpeg commands.
* It does not alter or judge evidence state.
* It does not replace ``build_ffmpeg_render_plan``'s fail-closed gate.

Fail-closed conditions (all raise ``ValueError``)
--------------------------------------------------
1. A ``SceneClip.event_id`` has no matching entry in ``resolved_clips``.
2. The same ``event_id`` appears more than once across all scenes in the
   ``DirectorScript`` (defence-in-depth: GeminiDirector already prohibits
   duplicates, but ScriptExecutor does not trust that unconditionally).
3. The ``ResolvedCandidateClip.asset_id`` does not match
   ``SceneClip.source_asset_id``.
4. The ``ResolvedCandidateClip.start_offset_s`` does not match
   ``SceneClip.source_start_sec`` (within ``_OFFSET_TOLERANCE_S``).
5. The ``ResolvedCandidateClip.end_offset_s`` does not match
   ``SceneClip.source_end_sec`` (within ``_OFFSET_TOLERANCE_S``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.director import DirectorScript
from app.edit.render_plan import FfmpegRenderPlan, build_ffmpeg_render_plan

if TYPE_CHECKING:
    from app.video.catalog import ResolvedCandidateClip


# Floating-point tolerance for start/end offset comparisons (seconds).
_OFFSET_TOLERANCE_S: float = 1e-6


class ScriptExecutor:
    """Convert a ``DirectorScript`` into a ``FfmpegRenderPlan``.

    The caller is responsible for supplying the ``ResolvedCandidateClip``
    lookup and the ``visual_evidence_confirmed_event_ids`` allow-list.
    ScriptExecutor does not fetch, modify, or judge either.
    """

    def execute(
        self,
        script: DirectorScript,
        resolved_clips: tuple[ResolvedCandidateClip, ...],
        *,
        visual_evidence_confirmed_event_ids: tuple[str, ...] = (),
        output_file_name: str = "ride-storyteller-film.mp4",
    ) -> FfmpegRenderPlan:
        """Translate *script* into a ``FfmpegRenderPlan``.

        Parameters
        ----------
        script:
            The ``DirectorScript`` produced by a ``Director``.
        resolved_clips:
            All ``ResolvedCandidateClip`` objects available for this session,
            in any order.  ScriptExecutor looks them up by ``event_id``.
        visual_evidence_confirmed_event_ids:
            Forwarded unchanged to ``build_ffmpeg_render_plan``.  This is the
            second-line-of-defence evidence allow-list.
        output_file_name:
            Passed to ``build_ffmpeg_render_plan``.

        Returns
        -------
        FfmpegRenderPlan
            May be ``NEEDS_HUMAN_REVIEW`` if the evidence gate is not
            satisfied; the existing gate logic determines this.

        Raises
        ------
        ValueError
            On any fail-closed condition (missing clip, duplicate event_id,
            or source mismatch).
        """
        resolved_by_id: dict[str, ResolvedCandidateClip] = {}
        for rc in resolved_clips:
            resolved_by_id[rc.event_id] = rc

        ordered: list[ResolvedCandidateClip] = []
        seen_event_ids: set[str] = set()

        for scene in script.scenes:
            for scene_clip in scene.clips:
                eid = scene_clip.event_id

                # Fail-closed: duplicate event_id in DirectorScript
                if eid in seen_event_ids:
                    raise ValueError(
                        f"event_id {eid!r} appears more than once in the "
                        "DirectorScript; duplicate clips are not permitted"
                    )
                seen_event_ids.add(eid)

                # Fail-closed: no matching ResolvedCandidateClip
                rc = resolved_by_id.get(eid)
                if rc is None:
                    raise ValueError(
                        f"DirectorScript references event_id {eid!r} but no "
                        "matching ResolvedCandidateClip was supplied"
                    )

                # Fail-closed: source_asset_id mismatch
                if rc.asset_id != scene_clip.source_asset_id:
                    raise ValueError(
                        f"event_id {eid!r}: ResolvedCandidateClip.asset_id "
                        f"{rc.asset_id!r} does not match "
                        f"SceneClip.source_asset_id {scene_clip.source_asset_id!r}"
                    )

                # Fail-closed: source_start_sec mismatch
                if (
                    rc.start_offset_s is None
                    or abs(rc.start_offset_s - scene_clip.source_start_sec)
                    > _OFFSET_TOLERANCE_S
                ):
                    raise ValueError(
                        f"event_id {eid!r}: ResolvedCandidateClip.start_offset_s "
                        f"{rc.start_offset_s} does not match "
                        f"SceneClip.source_start_sec {scene_clip.source_start_sec}"
                    )

                # Fail-closed: source_end_sec mismatch
                if (
                    rc.end_offset_s is None
                    or abs(rc.end_offset_s - scene_clip.source_end_sec)
                    > _OFFSET_TOLERANCE_S
                ):
                    raise ValueError(
                        f"event_id {eid!r}: ResolvedCandidateClip.end_offset_s "
                        f"{rc.end_offset_s} does not match "
                        f"SceneClip.source_end_sec {scene_clip.source_end_sec}"
                    )

                ordered.append(rc)

        return build_ffmpeg_render_plan(
            tuple(ordered),
            visual_evidence_confirmed_event_ids=visual_evidence_confirmed_event_ids,
            output_file_name=output_file_name,
        )
