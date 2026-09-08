from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contracts import Location
from app.edit import CandidateEvidenceStatus
from app.local_pipeline import prepare_local_review_package
from app.private_story_e2e import run_private_story_e2e
from app.video import (
    LocalEvidenceDecision,
    LocalEvidenceReview,
    LocalVideoMetadata,
    load_local_evidence_review,
    write_local_evidence_review,
)
from app.video.highlight_quality import InterestLane, QualitySelectionMethod
from app.video.highlight_story_bridge import (
    HighlightBridgeCandidate,
    HighlightBridgeCandidateSet,
    HighlightReinforcementSelection,
    HighlightReinforcementSelectionSet,
    write_highlight_bridge_candidates,
    write_highlight_reinforcement_selections,
)


def _metadata(path: Path) -> LocalVideoMetadata:
    return LocalVideoMetadata(
        file_name=path.name,
        duration_s=3_600.0,
        recorded_start_time=datetime(2026, 8, 10, 1, 42, tzinfo=UTC),
        video_codec="hevc",
        width=3840,
        height=2160,
        frames_per_second=60.0,
        has_audio=True,
    )


def _runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
    Path(command[-1]).write_bytes(b"local-output")
    return subprocess.CompletedProcess(command, 0, "", "")


def _prepared_package(tmp_path: Path) -> Path:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    package = tmp_path / "package"
    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        package,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        probe=_metadata,
        clip_runner=_runner,
    )
    return package


def test_private_story_e2e_renders_in_director_story_order(tmp_path: Path) -> None:
    package = _prepared_package(tmp_path)
    candidates = json.loads((package / "ride-storyteller-candidates.json").read_text())
    write_local_evidence_review(
        package / "evidence-review.json",
        LocalEvidenceReview(
            tuple(
                LocalEvidenceDecision(
                    event_id=clip["event_id"],
                    evidence_status=CandidateEvidenceStatus.CONFIRMED,
                    evidence_source="synthetic_human_review",
                )
                for clip in candidates["clips"]
            )
        ),
        overwrite=True,
    )

    result = run_private_story_e2e(
        package,
        probe=_metadata,
        clip_runner=_runner,
        render_runner=_runner,
    )

    assert result.director.director_result is not None
    assert result.render.story_order_applied is True
    assert result.render.audio_included is False
    assert (package / result.render.output_file_name).is_file()
    result_payload = result.to_dict()
    payload = json.dumps(result_payload)
    assert "external_data_sent" in payload
    assert '"source_asset_id"' not in payload
    assert '"source_start_sec"' not in payload
    assert "output_file_name" not in result_payload["render"]


def test_private_story_e2e_rejects_awaiting_evidence_before_probing(tmp_path: Path) -> None:
    package = _prepared_package(tmp_path)
    # A matched clip is auto-confirmed by default; simulate a human manually
    # reopening one decision so an outstanding awaiting candidate remains.
    review_path = package / "evidence-review.json"
    review = load_local_evidence_review(review_path)
    reopened = LocalEvidenceReview(
        tuple(
            LocalEvidenceDecision(
                decision.event_id, CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE
            )
            if index == 0
            else decision
            for index, decision in enumerate(review.decisions)
        )
    )
    write_local_evidence_review(review_path, reopened, overwrite=True)
    calls: list[Path] = []

    def probe(path: Path) -> LocalVideoMetadata:
        calls.append(path)
        return _metadata(path)

    with pytest.raises(ValueError, match="no decision left awaiting"):
        run_private_story_e2e(package, probe=probe)

    assert calls == []


def test_private_story_e2e_rejects_a_missing_input_manifest_before_probing(
    tmp_path: Path,
) -> None:
    package = _prepared_package(tmp_path)
    (package / "local-pipeline-inputs.json").unlink()
    calls: list[Path] = []

    def probe(path: Path) -> LocalVideoMetadata:
        calls.append(path)
        return _metadata(path)

    with pytest.raises(ValueError, match="inputs are unavailable"):
        run_private_story_e2e(package, probe=probe)

    assert calls == []


def test_private_story_e2e_replays_selected_highlight_reinforcement(
    tmp_path: Path,
) -> None:
    """The final private E2E must use the package snapshot, not a live review.

    This connects the human selection through prepare, Director rerun, and
    deterministic rendering using only synthetic fixtures.
    """
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    baseline = tmp_path / "baseline"
    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        baseline,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        probe=_metadata,
        clip_runner=_runner,
    )
    matched = next(
        clip
        for clip in json.loads((baseline / "ride-storyteller-candidates.json").read_text())["clips"]
        if clip["status"] == "matched"
    )
    original_start = matched["start_offset_s"]
    original_end = matched["end_offset_s"]
    # The test metadata's recorded start is offset from the sample route by
    # five seconds; derive the GPS-aligned start from synthetic metadata.
    gps_file_start = _metadata(Path("GX010001.MP4")).recorded_start_time + timedelta(seconds=5.0)
    candidate = HighlightBridgeCandidate(
        candidate_id="highlight-e2e-choice0000000",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=gps_file_start + timedelta(seconds=original_start + 1.0),
        duration_s=(original_end - original_start) - 2.0,
        location=Location(35.0, 139.0),
        interest_lanes=(InterestLane.STRONG_TURN,),
        score=0.9,
    )
    review_directory = tmp_path / "reinforcement-review"
    review_directory.mkdir()
    write_highlight_bridge_candidates(
        review_directory / "highlight-bridge-candidates.json",
        HighlightBridgeCandidateSet((candidate,)),
    )
    write_highlight_reinforcement_selections(
        review_directory / "highlight-reinforcement-selections.json",
        HighlightReinforcementSelectionSet(
            (HighlightReinforcementSelection(matched["event_id"], candidate.candidate_id),)
        ),
    )
    package = tmp_path / "package"
    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        package,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        probe=_metadata,
        clip_runner=_runner,
        highlight_reinforcement_review_directory=review_directory,
    )
    review = load_local_evidence_review(package / "evidence-review.json")
    write_local_evidence_review(
        package / "evidence-review.json",
        LocalEvidenceReview(
            tuple(
                LocalEvidenceDecision(
                    event_id=decision.event_id,
                    evidence_status=CandidateEvidenceStatus.CONFIRMED,
                    evidence_source="synthetic_human_review",
                )
                for decision in review.decisions
            )
        ),
        overwrite=True,
    )

    result = run_private_story_e2e(
        package,
        probe=_metadata,
        clip_runner=_runner,
        render_runner=_runner,
    )

    assert result.render.story_order_applied is True
    clips = json.loads((package / "ride-storyteller-candidates.json").read_text())["clips"]
    reinforced = next(clip for clip in clips if clip["event_id"] == matched["event_id"])
    assert reinforced["start_offset_s"] == pytest.approx(original_start + 1.0)
    assert reinforced["end_offset_s"] == pytest.approx(original_end - 1.0)


def test_private_story_e2e_cli_accepts_only_a_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import private_story_e2e

    captured: dict[str, object] = {}

    def fake_run(
        package: Path,
        *,
        output_file_name: str,
        overwrite: bool,
    ) -> object:
        captured.update(
            package=package,
            output_file_name=output_file_name,
            overwrite=overwrite,
        )
        return type("Result", (), {"to_dict": lambda self: {"ok": True}})()

    monkeypatch.setattr(private_story_e2e, "run_private_story_e2e", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "private_story_e2e",
            "private-package",
            "--output-file-name",
            "story.mp4",
            "--overwrite",
        ],
    )

    private_story_e2e.main()

    assert captured == {
        "package": Path("private-package"),
        "output_file_name": "story.mp4",
        "overwrite": True,
    }
