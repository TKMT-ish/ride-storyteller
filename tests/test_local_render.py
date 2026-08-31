import json
import subprocess
from pathlib import Path

import pytest

from app.director_pipeline import DIRECTOR_SCRIPT_SCHEMA_VERSION
from app.edit import CandidateEvidenceStatus
from app.local_render import LocalRenderBlockedError, render_local_review_film
from app.video import ResolvedCandidateClip, VideoMatchStatus, export_candidate_json
from app.video.local_clips import LocalReviewClip, write_local_review_clip_manifest
from app.video.review import (
    LocalEvidenceDecision,
    LocalEvidenceReview,
    build_local_evidence_review_template,
    write_local_evidence_review,
)


def _clip(event_id: str = "event_001") -> ResolvedCandidateClip:
    return ResolvedCandidateClip(
        chapter_id="chapter_01",
        event_id=event_id,
        status=VideoMatchStatus.MATCHED,
        asset_id=f"asset-{event_id}",
        file_name="source.mp4",
        start_offset_s=0.0,
        end_offset_s=5.0,
        reason="test",
    )


def _package(tmp_path: Path, *, confirmed: bool) -> tuple[Path, tuple[ResolvedCandidateClip, ...]]:
    package = tmp_path / "package"
    reviews = package / "review-clips"
    reviews.mkdir(parents=True)
    clips = (_clip(), _clip("event_002"))
    (package / "ride-storyteller-candidates.json").write_text(
        export_candidate_json(clips), encoding="utf-8"
    )
    manifest = tuple(
        LocalReviewClip(
            event_id=clip.event_id,
            asset_id=clip.asset_id or "",
            output_file_name=f"review-{index:03d}.mp4",
            duration_s=5.0,
        )
        for index, clip in enumerate(clips, start=1)
    )
    for review in manifest:
        (reviews / review.output_file_name).write_bytes(b"review")
    write_local_review_clip_manifest(package / "review-clip-manifest.json", manifest)
    if confirmed:
        evidence = LocalEvidenceReview(
            tuple(
                LocalEvidenceDecision(
                    clip.event_id,
                    CandidateEvidenceStatus.CONFIRMED,
                    "human_review",
                )
                for clip in clips
            )
        )
    else:
        evidence = build_local_evidence_review_template(clips)
    write_local_evidence_review(package / "evidence-review.json", evidence)
    return package, clips


def test_local_render_concatenates_only_confirmed_review_clips(tmp_path: Path) -> None:
    package, _clips = _package(tmp_path, confirmed=True)
    received: dict[str, object] = {}

    def runner(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        received["command"] = command
        received["kwargs"] = kwargs
        Path(command[-1]).write_bytes(b"film")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = render_local_review_film(package, runner=runner)

    command = received["command"]
    assert isinstance(command, tuple)
    assert command[0] == "ffmpeg"
    assert command.count("-i") == 2
    filter_graph = command[command.index("-filter_complex") + 1]
    assert filter_graph == "[0:v:0][1:v:0]concat=n=2:v=1:a=0[v]"
    assert "-an" in command
    assert result.clip_count == 2
    assert result.duration_s == 10.0
    assert result.audio_included is False
    assert result.to_dict()["external_data_sent"] is False
    assert result.story_order_applied is False


def test_local_render_uses_valid_director_script_story_order(tmp_path: Path) -> None:
    package, clips = _package(tmp_path, confirmed=True)
    artifact = package / "local-director-script.json"
    artifact.write_text(
        json.dumps(
            {
                "schema_version": DIRECTOR_SCRIPT_SCHEMA_VERSION,
                "metadata": {
                    "composer": "rule_based",
                    "event_count_in": 2,
                    "event_count_used": 2,
                    "arc_names": ["hook", "resolution"],
                },
                "scenes": [
                    {
                        "scene_id": "scene_hook",
                        "scene_type": "hook",
                        "transition_type": "cut",
                        "overlay_text": None,
                        "clips": [
                            {
                                "event_id": clips[1].event_id,
                                "source_asset_id": clips[1].asset_id,
                                "source_start_sec": clips[1].start_offset_s,
                                "source_end_sec": clips[1].end_offset_s,
                                "file_name": clips[1].file_name,
                            }
                        ],
                    },
                    {
                        "scene_id": "scene_resolution",
                        "scene_type": "resolution",
                        "transition_type": "cut",
                        "overlay_text": None,
                        "clips": [
                            {
                                "event_id": clips[0].event_id,
                                "source_asset_id": clips[0].asset_id,
                                "source_start_sec": clips[0].start_offset_s,
                                "source_end_sec": clips[0].end_offset_s,
                                "file_name": clips[0].file_name,
                            }
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    received: dict[str, object] = {}

    def runner(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        received["command"] = command
        Path(command[-1]).write_bytes(b"film")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = render_local_review_film(
        package,
        director_script_path=artifact,
        runner=runner,
    )

    command = received["command"]
    assert isinstance(command, tuple)
    inputs = tuple(command[index + 1] for index, value in enumerate(command) if value == "-i")
    assert inputs == (
        str(package / "review-clips" / "review-002.mp4"),
        str(package / "review-clips" / "review-001.mp4"),
    )
    assert result.story_order_applied is True


def test_local_render_rejects_director_script_outside_private_package(tmp_path: Path) -> None:
    package, _clips = _package(tmp_path, confirmed=True)
    called = False

    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0, "", "")

    with pytest.raises(LocalRenderBlockedError, match="same private render package"):
        render_local_review_film(
            package,
            director_script_path=tmp_path / "different-package" / "script.json",
            runner=runner,
        )

    assert called is False


def test_local_render_rejects_unimplemented_director_script_transitions(
    tmp_path: Path,
) -> None:
    package, clips = _package(tmp_path, confirmed=True)
    artifact = package / "local-director-script.json"
    artifact.write_text(
        json.dumps(
            {
                "schema_version": DIRECTOR_SCRIPT_SCHEMA_VERSION,
                "metadata": {
                    "composer": "gemini",
                    "event_count_in": 1,
                    "event_count_used": 1,
                    "arc_names": ["hook"],
                },
                "scenes": [
                    {
                        "scene_id": "scene_hook",
                        "scene_type": "hook",
                        "transition_type": "fade",
                        "overlay_text": None,
                        "clips": [
                            {
                                "event_id": clips[0].event_id,
                                "source_asset_id": clips[0].asset_id,
                                "source_start_sec": clips[0].start_offset_s,
                                "source_end_sec": clips[0].end_offset_s,
                                "file_name": clips[0].file_name,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    called = False

    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0, "", "")

    with pytest.raises(ValueError, match="invalid transition_type"):
        render_local_review_film(
            package,
            director_script_path=artifact,
            runner=runner,
        )

    assert called is False


def test_local_render_blocks_awaiting_evidence_before_runner(tmp_path: Path) -> None:
    package, _clips = _package(tmp_path, confirmed=False)
    called = False

    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0, "", "")

    with pytest.raises(LocalRenderBlockedError, match="visual_evidence_awaiting"):
        render_local_review_film(package, runner=runner)

    assert called is False


def test_local_render_blocks_incomplete_manifest(tmp_path: Path) -> None:
    package, clips = _package(tmp_path, confirmed=True)
    write_local_review_clip_manifest(
        package / "review-clip-manifest.json",
        (
            LocalReviewClip(
                event_id=clips[0].event_id,
                asset_id=clips[0].asset_id or "",
                output_file_name="review-001.mp4",
                duration_s=5.0,
            ),
        ),
        overwrite=True,
    )

    with pytest.raises(LocalRenderBlockedError, match="manifest is incomplete"):
        render_local_review_film(package)


def test_local_render_requires_explicit_overwrite(tmp_path: Path) -> None:
    package, _clips = _package(tmp_path, confirmed=True)
    (package / "ride-storyteller-review-film.mp4").write_bytes(b"existing")

    with pytest.raises(FileExistsError, match="already exists"):
        render_local_review_film(package)


def test_local_render_rejects_output_paths(tmp_path: Path) -> None:
    package, _clips = _package(tmp_path, confirmed=True)

    with pytest.raises(ValueError, match="file name only"):
        render_local_review_film(package, output_file_name="../film.mp4")
