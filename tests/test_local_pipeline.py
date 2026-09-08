import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from app.contracts import Location
from app.edit import CandidateEvidenceStatus
from app.local_pipeline import (
    load_local_pipeline_inputs,
    prepare_local_review_package,
    rerun_local_director_from_package,
)
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
    load_highlight_bridge_candidates,
    load_highlight_reinforcement_selections,
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
    Path(command[-1]).write_bytes(b"review")
    return subprocess.CompletedProcess(command, 0, "", "")


def test_local_pipeline_connects_gpx_catalog_matching_and_review_clips(
    tmp_path: Path,
) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    output = tmp_path / "private-output"

    result = prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        output,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=True,
        probe=_metadata,
        clip_runner=_runner,
    )
    payload = result.to_dict()

    assert result.catalog_entry_count == 1
    assert result.matched_clip_count >= 1
    assert result.unmatched_clip_count == 0
    assert result.review_clip_count == result.matched_clip_count
    assert payload["privacy"] == {
        "private_data_used": True,
        "external_data_sent": False,
        "coordinates_in_summary": False,
        "absolute_paths_in_summary": False,
        "visual_evidence_auto_confirmed": True,
    }
    # The matched clip is auto-confirmed; the remaining blocker is that a
    # single short event does not reach the target story duration.
    assert payload["next_gate"] == "add_timestamp_matched_candidates"
    assert (output / "local-video-catalog.json").exists()
    assert (output / "ride-storyteller-candidates.json").exists()
    assert (output / "ride-storyteller-candidates.csv").exists()
    assert (output / "local-pipeline-summary.json").exists()
    assert (output / "evidence-review.json").exists()
    assert (output / "review-clip-manifest.json").exists()
    assert len(tuple((output / "review-clips").glob("review-*.mp4"))) == result.review_clip_count
    inputs = load_local_pipeline_inputs(output / "local-pipeline-inputs.json")
    assert inputs.gpx_path == Path("tests/fixtures/sample_route.xml").resolve()
    assert inputs.video_root == video_root.resolve()
    assert inputs.video_to_gps_offset_s == 5.0


def test_prepare_local_review_package_merges_highlight_bridge_candidates(
    tmp_path: Path,
) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    output = tmp_path / "output"

    # Well clear of the GPS-derived event near the start of the recording.
    gps_file_start = _metadata(Path("GX010001.MP4")).recorded_start_time + timedelta(seconds=5.0)
    candidate = HighlightBridgeCandidate(
        candidate_id="highlight-0123456789abcdef",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=gps_file_start + timedelta(seconds=500.0),
        duration_s=12.0,
        location=Location(35.0, 139.0),
        interest_lanes=(InterestLane.STRONG_TURN,),
        score=0.9,
    )
    bridge_path = tmp_path / "highlight-bridge-candidates.json"
    write_highlight_bridge_candidates(bridge_path, HighlightBridgeCandidateSet((candidate,)))

    result = prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        output,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
        highlight_bridge_candidates_path=bridge_path,
    )

    assert result.matched_clip_count >= 2
    candidates_payload = json.loads((output / "ride-storyteller-candidates.json").read_text())
    highlight_clips = [
        clip
        for clip in candidates_payload["clips"]
        if clip["event_id"].startswith("highlight-event-")
    ]
    assert len(highlight_clips) == 1
    assert highlight_clips[0]["status"] == "matched"
    review = load_local_evidence_review(output / "evidence-review.json")
    highlight_decision = next(
        decision
        for decision in review.decisions
        if decision.event_id == highlight_clips[0]["event_id"]
    )
    assert highlight_decision.evidence_status is CandidateEvidenceStatus.CONFIRMED


def test_prepare_local_review_package_reinforces_an_overlapping_resolved_clip(
    tmp_path: Path,
) -> None:
    """A highlight candidate overlapping an existing resolved clip narrows it
    instead of being discarded (docs/highlight-story-bridge-design-ja.md §7-5:
    on real media every candidate overlapped an existing event, so only the
    reinforcement path -- not the new-event path -- has real value)."""
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")

    baseline = prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        tmp_path / "baseline",
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
    )
    assert baseline.matched_clip_count >= 1
    baseline_clips = json.loads(
        (tmp_path / "baseline" / "ride-storyteller-candidates.json").read_text()
    )["clips"]
    matched = next(clip for clip in baseline_clips if clip["status"] == "matched")
    original_start = matched["start_offset_s"]
    original_end = matched["end_offset_s"]
    assert original_end - original_start > 4.0  # enough room to narrow meaningfully

    gps_file_start = _metadata(Path("GX010001.MP4")).recorded_start_time + timedelta(seconds=5.0)
    candidate_start_offset = original_start + 1.0
    candidate_duration = (original_end - original_start) - 2.0
    candidate = HighlightBridgeCandidate(
        candidate_id="highlight-fedcba9876543210",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=gps_file_start + timedelta(seconds=candidate_start_offset),
        duration_s=candidate_duration,
        location=Location(35.0, 139.0),
        interest_lanes=(InterestLane.STRONG_TURN,),
        score=0.9,
    )
    bridge_path = tmp_path / "highlight-bridge-candidates.json"
    write_highlight_bridge_candidates(bridge_path, HighlightBridgeCandidateSet((candidate,)))

    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        tmp_path / "reinforced",
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
        highlight_bridge_candidates_path=bridge_path,
    )

    reinforced_clips = json.loads(
        (tmp_path / "reinforced" / "ride-storyteller-candidates.json").read_text()
    )["clips"]
    reinforced_matched = next(
        clip for clip in reinforced_clips if clip["event_id"] == matched["event_id"]
    )
    assert reinforced_matched["start_offset_s"] == pytest.approx(candidate_start_offset)
    assert reinforced_matched["end_offset_s"] == pytest.approx(
        candidate_start_offset + candidate_duration
    )
    assert (
        reinforced_matched["end_offset_s"] - reinforced_matched["start_offset_s"]
        < original_end - original_start
    )
    # The candidate overlapped an existing event, so it reinforces that
    # event's clip rather than also being added as a new one.
    assert not any(clip["event_id"].startswith("highlight-event-") for clip in reinforced_clips)


def _baseline_matched_clip(tmp_path: Path, video_root: Path) -> tuple[dict, datetime]:
    """A real, timestamp-matched clip and its video's GPS-corrected start time."""
    baseline = prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        tmp_path / "baseline",
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
    )
    assert baseline.matched_clip_count >= 1
    baseline_clips = json.loads(
        (tmp_path / "baseline" / "ride-storyteller-candidates.json").read_text()
    )["clips"]
    matched = next(clip for clip in baseline_clips if clip["status"] == "matched")
    assert matched["end_offset_s"] - matched["start_offset_s"] > 4.0
    gps_file_start = _metadata(Path("GX010001.MP4")).recorded_start_time + timedelta(seconds=5.0)
    return matched, gps_file_start


def test_prepare_local_review_package_applies_explicit_selection_from_review_directory(
    tmp_path: Path,
) -> None:
    """Two candidates from different methods overlapping the same clip cannot
    resolve automatically; an explicit HighlightReinforcementSelection from the
    reinforcement review directory picks one, and only that one narrows the
    clip."""
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    matched, gps_file_start = _baseline_matched_clip(tmp_path, video_root)
    original_start = matched["start_offset_s"]
    original_end = matched["end_offset_s"]

    chosen = HighlightBridgeCandidate(
        candidate_id="highlight-chosen0000000000000",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=gps_file_start + timedelta(seconds=original_start + 1.0),
        duration_s=(original_end - original_start) - 2.0,
        location=Location(35.0, 139.0),
        interest_lanes=(InterestLane.STRONG_TURN,),
        score=0.9,
    )
    other = HighlightBridgeCandidate(
        candidate_id="highlight-other00000000000000",
        method=QualitySelectionMethod.RIDE_DYNAMICS,
        rank=1,
        start_time=gps_file_start + timedelta(seconds=original_start + 0.5),
        duration_s=(original_end - original_start) - 1.0,
        location=Location(35.0, 139.0),
        interest_lanes=(InterestLane.STRONG_TURN,),
        score=0.8,
    )
    review_directory = tmp_path / "reinforcement-review"
    review_directory.mkdir()
    write_highlight_bridge_candidates(
        review_directory / "highlight-bridge-candidates.json",
        HighlightBridgeCandidateSet((chosen, other)),
    )
    write_highlight_reinforcement_selections(
        review_directory / "highlight-reinforcement-selections.json",
        HighlightReinforcementSelectionSet(
            (HighlightReinforcementSelection(matched["event_id"], chosen.candidate_id),)
        ),
    )

    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        tmp_path / "reinforced",
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
        highlight_reinforcement_review_directory=review_directory,
    )

    reinforced_clips = json.loads(
        (tmp_path / "reinforced" / "ride-storyteller-candidates.json").read_text()
    )["clips"]
    reinforced_matched = next(
        clip for clip in reinforced_clips if clip["event_id"] == matched["event_id"]
    )
    assert reinforced_matched["start_offset_s"] == pytest.approx(original_start + 1.0)
    assert reinforced_matched["end_offset_s"] == pytest.approx(original_end - 1.0)


def test_prepare_local_review_package_rejects_both_reinforcement_inputs_before_probing(
    tmp_path: Path,
) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    candidates_path = tmp_path / "highlight-bridge-candidates.json"
    write_highlight_bridge_candidates(candidates_path, HighlightBridgeCandidateSet(()))
    review_directory = tmp_path / "reinforcement-review"
    review_directory.mkdir()
    write_highlight_bridge_candidates(
        review_directory / "highlight-bridge-candidates.json", HighlightBridgeCandidateSet(())
    )
    calls: list[Path] = []

    def probe(path: Path) -> LocalVideoMetadata:
        calls.append(path)
        return _metadata(path)

    with pytest.raises(ValueError, match="cannot both be given"):
        prepare_local_review_package(
            Path("tests/fixtures/sample_route.xml"),
            video_root,
            tmp_path / "output",
            video_to_gps_offset_s=5.0,
            clock_offset_confirmed=True,
            probe=probe,
            highlight_bridge_candidates_path=candidates_path,
            highlight_reinforcement_review_directory=review_directory,
        )

    assert calls == []


def test_prepare_local_review_package_rejects_unsafe_review_directory_before_probing(
    tmp_path: Path,
) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    real_directory = tmp_path / "real-review"
    real_directory.mkdir()
    write_highlight_bridge_candidates(
        real_directory / "highlight-bridge-candidates.json", HighlightBridgeCandidateSet(())
    )
    link_directory = tmp_path / "linked-review"
    link_directory.symlink_to(real_directory)
    calls: list[Path] = []

    def probe(path: Path) -> LocalVideoMetadata:
        calls.append(path)
        return _metadata(path)

    with pytest.raises(ValueError, match="unavailable"):
        prepare_local_review_package(
            Path("tests/fixtures/sample_route.xml"),
            video_root,
            tmp_path / "output",
            video_to_gps_offset_s=5.0,
            clock_offset_confirmed=True,
            probe=probe,
            highlight_reinforcement_review_directory=link_directory,
        )

    assert calls == []


def test_prepare_local_review_package_rejects_malformed_candidates_before_probing(
    tmp_path: Path,
) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    review_directory = tmp_path / "reinforcement-review"
    review_directory.mkdir()
    (review_directory / "highlight-bridge-candidates.json").write_text("not json", encoding="utf-8")
    calls: list[Path] = []

    def probe(path: Path) -> LocalVideoMetadata:
        calls.append(path)
        return _metadata(path)

    with pytest.raises(ValueError):
        prepare_local_review_package(
            Path("tests/fixtures/sample_route.xml"),
            video_root,
            tmp_path / "output",
            video_to_gps_offset_s=5.0,
            clock_offset_confirmed=True,
            probe=probe,
            highlight_reinforcement_review_directory=review_directory,
        )

    assert calls == []


def test_prepare_local_review_package_treats_a_missing_selections_sidecar_as_empty(
    tmp_path: Path,
) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    review_directory = tmp_path / "reinforcement-review"
    review_directory.mkdir()
    write_highlight_bridge_candidates(
        review_directory / "highlight-bridge-candidates.json", HighlightBridgeCandidateSet(())
    )
    assert not (review_directory / "highlight-reinforcement-selections.json").exists()

    result = prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        tmp_path / "output",
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
        highlight_reinforcement_review_directory=review_directory,
    )

    assert result.matched_clip_count >= 1
    snapshot = load_highlight_reinforcement_selections(
        tmp_path / "output" / "highlight-reinforcement-selections.json"
    )
    assert snapshot == HighlightReinforcementSelectionSet(())


def test_prepare_local_review_package_snapshots_reinforcement_inputs(tmp_path: Path) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    matched, gps_file_start = _baseline_matched_clip(tmp_path, video_root)
    candidate = HighlightBridgeCandidate(
        candidate_id="highlight-snapshot000000000",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=gps_file_start + timedelta(seconds=matched["start_offset_s"] + 1.0),
        duration_s=(matched["end_offset_s"] - matched["start_offset_s"]) - 2.0,
        location=Location(35.0, 139.0),
        interest_lanes=(InterestLane.STRONG_TURN,),
        score=0.9,
    )
    review_directory = tmp_path / "reinforcement-review"
    review_directory.mkdir()
    candidate_set = HighlightBridgeCandidateSet((candidate,))
    write_highlight_bridge_candidates(
        review_directory / "highlight-bridge-candidates.json", candidate_set
    )
    selection_set = HighlightReinforcementSelectionSet(
        (HighlightReinforcementSelection(matched["event_id"], candidate.candidate_id),)
    )
    write_highlight_reinforcement_selections(
        review_directory / "highlight-reinforcement-selections.json", selection_set
    )

    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        tmp_path / "output",
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
        highlight_reinforcement_review_directory=review_directory,
    )

    snapshot_candidates = load_highlight_bridge_candidates(
        tmp_path / "output" / "highlight-bridge-candidates.json"
    )
    snapshot_selections = load_highlight_reinforcement_selections(
        tmp_path / "output" / "highlight-reinforcement-selections.json"
    )
    assert snapshot_candidates == candidate_set
    assert snapshot_selections == selection_set


def test_resume_replays_reinforcement_from_snapshot_even_if_review_directory_changes(
    tmp_path: Path,
) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    matched, gps_file_start = _baseline_matched_clip(tmp_path, video_root)
    original_start = matched["start_offset_s"]
    original_end = matched["end_offset_s"]

    first_choice = HighlightBridgeCandidate(
        candidate_id="highlight-first0000000000000",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=gps_file_start + timedelta(seconds=original_start + 1.0),
        duration_s=(original_end - original_start) - 2.0,
        location=Location(35.0, 139.0),
        interest_lanes=(InterestLane.STRONG_TURN,),
        score=0.9,
    )
    second_choice = HighlightBridgeCandidate(
        candidate_id="highlight-second000000000000",
        method=QualitySelectionMethod.RIDE_DYNAMICS,
        rank=1,
        start_time=gps_file_start + timedelta(seconds=original_start + 0.5),
        duration_s=(original_end - original_start) - 1.0,
        location=Location(35.0, 139.0),
        interest_lanes=(InterestLane.STRONG_TURN,),
        score=0.8,
    )
    review_directory = tmp_path / "reinforcement-review"
    review_directory.mkdir()
    write_highlight_bridge_candidates(
        review_directory / "highlight-bridge-candidates.json",
        HighlightBridgeCandidateSet((first_choice, second_choice)),
    )
    write_highlight_reinforcement_selections(
        review_directory / "highlight-reinforcement-selections.json",
        HighlightReinforcementSelectionSet(
            (HighlightReinforcementSelection(matched["event_id"], first_choice.candidate_id),)
        ),
    )

    output = tmp_path / "output"
    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        output,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
        highlight_reinforcement_review_directory=review_directory,
    )
    # Confirm the event so the rerun's evidence gate is satisfied.
    review = load_local_evidence_review(output / "evidence-review.json")
    write_local_evidence_review(
        output / "evidence-review.json",
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

    # A human later changes their mind in the review directory itself.
    write_highlight_reinforcement_selections(
        review_directory / "highlight-reinforcement-selections.json",
        HighlightReinforcementSelectionSet(
            (HighlightReinforcementSelection(matched["event_id"], second_choice.candidate_id),)
        ),
        overwrite=True,
    )

    rerun_local_director_from_package(output, probe=_metadata, clip_runner=_runner)

    resumed_clips = json.loads((output / "ride-storyteller-candidates.json").read_text())["clips"]
    resumed_matched = next(
        clip for clip in resumed_clips if clip["event_id"] == matched["event_id"]
    )
    # Still the first choice: the rerun never re-read the review directory.
    assert resumed_matched["start_offset_s"] == pytest.approx(original_start + 1.0)
    assert resumed_matched["end_offset_s"] == pytest.approx(original_end - 1.0)


def test_resume_rejects_an_unsafe_reinforcement_snapshot_before_probing(tmp_path: Path) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    output = tmp_path / "output"
    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        output,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
    )
    review = load_local_evidence_review(output / "evidence-review.json")
    write_local_evidence_review(
        output / "evidence-review.json",
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
    # Simulate tampering: a symlinked snapshot appears in the package.
    elsewhere = tmp_path / "elsewhere.json"
    write_highlight_bridge_candidates(elsewhere, HighlightBridgeCandidateSet(()))
    (output / "highlight-bridge-candidates.json").symlink_to(elsewhere)
    calls: list[Path] = []

    def probe(path: Path) -> LocalVideoMetadata:
        calls.append(path)
        return _metadata(path)

    with pytest.raises(ValueError, match="unavailable"):
        rerun_local_director_from_package(output, probe=probe)

    assert calls == []


@pytest.mark.parametrize(
    ("file_name", "write_snapshot"),
    (
        (
            "highlight-bridge-candidates.json",
            lambda path: write_highlight_bridge_candidates(path, HighlightBridgeCandidateSet(())),
        ),
        (
            "highlight-reinforcement-selections.json",
            lambda path: write_highlight_reinforcement_selections(
                path, HighlightReinforcementSelectionSet(())
            ),
        ),
    ),
)
def test_resume_rejects_an_incomplete_reinforcement_snapshot_before_probing(
    tmp_path: Path,
    file_name: str,
    write_snapshot: Callable[[Path], None],
) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    output = tmp_path / "output"
    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        output,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
    )
    review = load_local_evidence_review(output / "evidence-review.json")
    write_local_evidence_review(
        output / "evidence-review.json",
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
    write_snapshot(output / file_name)
    calls: list[Path] = []

    def probe(path: Path) -> LocalVideoMetadata:
        calls.append(path)
        return _metadata(path)

    with pytest.raises(ValueError, match="snapshot is incomplete"):
        rerun_local_director_from_package(output, probe=probe)

    assert calls == []


def test_prepare_rejects_stale_reinforcement_snapshot_on_overwrite_before_probing(
    tmp_path: Path,
) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    output = tmp_path / "output"
    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        output,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
    )
    write_highlight_bridge_candidates(
        output / "highlight-bridge-candidates.json", HighlightBridgeCandidateSet(())
    )
    write_highlight_reinforcement_selections(
        output / "highlight-reinforcement-selections.json", HighlightReinforcementSelectionSet(())
    )
    calls: list[Path] = []

    def probe(path: Path) -> LocalVideoMetadata:
        calls.append(path)
        return _metadata(path)

    with pytest.raises(FileExistsError, match="holds a highlight-reinforcement snapshot"):
        prepare_local_review_package(
            Path("tests/fixtures/sample_route.xml"),
            video_root,
            output,
            video_to_gps_offset_s=5.0,
            clock_offset_confirmed=True,
            extract_reviews=False,
            overwrite=True,
            probe=probe,
        )

    assert calls == []


def test_reinforcement_review_directory_path_never_appears_in_package_output(
    tmp_path: Path,
) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    review_directory = tmp_path / "reinforcement-review"
    review_directory.mkdir()
    write_highlight_bridge_candidates(
        review_directory / "highlight-bridge-candidates.json", HighlightBridgeCandidateSet(())
    )
    output = tmp_path / "output"

    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        output,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
        highlight_reinforcement_review_directory=review_directory,
    )

    summary = (output / "local-pipeline-summary.json").read_text()
    candidates = (output / "ride-storyteller-candidates.json").read_text()
    assert str(review_directory) not in summary
    assert str(review_directory) not in candidates


def test_local_pipeline_stops_before_probing_without_clock_confirmation(
    tmp_path: Path,
) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    calls: list[Path] = []

    def probe(path: Path) -> LocalVideoMetadata:
        calls.append(path)
        return _metadata(path)

    with pytest.raises(ValueError, match="explicitly confirmed"):
        prepare_local_review_package(
            Path("tests/fixtures/sample_route.xml"),
            video_root,
            tmp_path / "output",
            video_to_gps_offset_s=0.0,
            clock_offset_confirmed=False,
            probe=probe,
        )

    assert calls == []


def test_local_pipeline_summary_contains_no_coordinates_or_absolute_paths(
    tmp_path: Path,
) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    output = tmp_path / "output"

    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        output,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        extract_reviews=False,
        probe=_metadata,
    )
    summary = (output / "local-pipeline-summary.json").read_text()

    assert str(tmp_path) not in summary
    assert "latitude" not in summary
    assert "longitude" not in summary
    assert json.loads(summary)["next_gate"] == "add_timestamp_matched_candidates"


def test_local_pipeline_requires_explicit_overwrite(tmp_path: Path) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    output = tmp_path / "output"
    output.mkdir()
    (output / "local-pipeline-summary.json").write_text("existing")

    with pytest.raises(FileExistsError, match="already exists"):
        prepare_local_review_package(
            Path("tests/fixtures/sample_route.xml"),
            video_root,
            output,
            video_to_gps_offset_s=5.0,
            clock_offset_confirmed=True,
            probe=_metadata,
        )


def test_local_pipeline_rejects_a_different_input_before_probing(tmp_path: Path) -> None:
    first_video_root = tmp_path / "first-videos"
    first_video_root.mkdir()
    (first_video_root / "GX010001.MP4").write_bytes(b"source")
    second_video_root = tmp_path / "second-videos"
    second_video_root.mkdir()
    (second_video_root / "GX010002.MP4").write_bytes(b"source")
    output = tmp_path / "output"
    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        first_video_root,
        output,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        probe=_metadata,
        clip_runner=_runner,
    )
    calls: list[Path] = []

    def probe(path: Path) -> LocalVideoMetadata:
        calls.append(path)
        return _metadata(path)

    with pytest.raises(ValueError, match="do not match"):
        prepare_local_review_package(
            Path("tests/fixtures/sample_route.xml"),
            second_video_root,
            output,
            video_to_gps_offset_s=5.0,
            clock_offset_confirmed=True,
            overwrite=True,
            probe=probe,
        )

    assert calls == []


def test_input_manifest_rejects_relative_source_paths(tmp_path: Path) -> None:
    manifest = tmp_path / "local-pipeline-inputs.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "local-pipeline-input-manifest-v1",
                "gpx_path": "relative-route.gpx",
                "video_root": "/private/videos",
                "video_to_gps_offset_s": 0.0,
                "target_duration_s": 300.0,
                "output_language": "ja",
            }
        )
    )

    with pytest.raises(ValueError, match="non-absolute GPX"):
        load_local_pipeline_inputs(manifest)


def test_local_pipeline_rejects_unignored_repository_output() -> None:
    repository_root = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="ignored private-media"):
        prepare_local_review_package(
            Path("tests/fixtures/sample_route.xml"),
            repository_root / "tests" / "fixtures",
            repository_root / "unsafe-local-output",
            video_to_gps_offset_s=0.0,
            clock_offset_confirmed=True,
            probe=_metadata,
        )


def test_local_pipeline_rejects_repository_derived_media_as_source() -> None:
    from app.local_pipeline import _validate_source_video_directory

    repository_root = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="must not be inside private-media/work"):
        _validate_source_video_directory(repository_root / "private-media/work/review-proxies")


def test_rerun_local_director_reuses_the_exact_private_input_manifest(tmp_path: Path) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    output = tmp_path / "output"
    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        output,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        probe=_metadata,
        clip_runner=_runner,
    )
    candidates = json.loads((output / "ride-storyteller-candidates.json").read_text())
    write_local_evidence_review(
        output / "evidence-review.json",
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

    result = rerun_local_director_from_package(
        output,
        probe=_metadata,
        clip_runner=_runner,
    )

    assert result.director_result is not None
    assert (output / "local-director-script.json").exists()


def test_rerun_local_director_rejects_awaiting_evidence_before_probing(
    tmp_path: Path,
) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")
    output = tmp_path / "output"
    prepare_local_review_package(
        Path("tests/fixtures/sample_route.xml"),
        video_root,
        output,
        video_to_gps_offset_s=5.0,
        clock_offset_confirmed=True,
        probe=_metadata,
        clip_runner=_runner,
    )
    # A matched clip is auto-confirmed by default; simulate a human manually
    # reopening one decision so the rerun still has an outstanding awaiting
    # candidate to reject.
    review_path = output / "evidence-review.json"
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
        rerun_local_director_from_package(output, probe=probe)

    assert calls == []


def test_local_pipeline_fails_closed_without_video_backed_events(tmp_path: Path) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    (video_root / "GX010001.MP4").write_bytes(b"source")

    def distant_metadata(path: Path) -> LocalVideoMetadata:
        return LocalVideoMetadata(
            file_name=path.name,
            duration_s=60.0,
            recorded_start_time=datetime(2030, 1, 1, tzinfo=UTC),
            video_codec="h264",
            width=1920,
            height=1080,
            frames_per_second=30.0,
            has_audio=True,
        )

    with pytest.raises(ValueError, match="timestamp-matched video coverage"):
        prepare_local_review_package(
            Path("tests/fixtures/sample_route.xml"),
            video_root,
            tmp_path / "output",
            video_to_gps_offset_s=0.0,
            clock_offset_confirmed=True,
            probe=distant_metadata,
        )


def test_cli_director_mode_is_explicit_and_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI must opt into only the local RuleBased Director path."""
    from app import local_pipeline

    captured: dict[str, object] = {}

    def fake_prepare(*args: object, **kwargs: object) -> object:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(to_dict=lambda: {"ok": True})

    monkeypatch.setattr(local_pipeline, "prepare_local_review_package", fake_prepare)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "local_pipeline",
            "private-route.gpx",
            "private-videos",
            "--output",
            "private-media/work/cli-test",
            "--clock-offset-s",
            "0",
            "--clock-offset-confirmed",
            "--director-mode",
        ],
    )

    local_pipeline.main()

    assert captured["kwargs"] == {
        "video_to_gps_offset_s": 0.0,
        "clock_offset_confirmed": True,
        "target_duration_s": 300.0,
        "output_language": local_pipeline.StoryOutputLanguage.JAPANESE,
        "extract_reviews": True,
        "overwrite": False,
        "director_mode": True,
        "highlight_bridge_candidates_path": None,
        "highlight_reinforcement_review_directory": None,
    }


def test_cli_accepts_highlight_bridge_candidates_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import local_pipeline

    captured: dict[str, object] = {}

    def fake_prepare(*args: object, **kwargs: object) -> object:
        captured["kwargs"] = kwargs
        return SimpleNamespace(to_dict=lambda: {"ok": True})

    monkeypatch.setattr(local_pipeline, "prepare_local_review_package", fake_prepare)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "local_pipeline",
            "private-route.gpx",
            "private-videos",
            "--output",
            "private-media/work/cli-test",
            "--clock-offset-s",
            "0",
            "--clock-offset-confirmed",
            "--highlight-bridge-candidates",
            "private-media/work/highlight-bridge-candidates.json",
        ],
    )

    local_pipeline.main()

    assert captured["kwargs"]["highlight_bridge_candidates_path"] == Path(
        "private-media/work/highlight-bridge-candidates.json"
    )


def test_cli_resume_output_reuses_the_private_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resume mode must not accept replacement source arguments."""
    from app import local_pipeline

    captured: dict[str, object] = {}

    def fake_rerun(output: Path) -> object:
        captured["output"] = output
        return SimpleNamespace(to_dict=lambda: {"ok": True})

    monkeypatch.setattr(local_pipeline, "rerun_local_director_from_package", fake_rerun)
    monkeypatch.setattr(sys, "argv", ["local_pipeline", "--resume-output", "private-output"])

    local_pipeline.main()

    assert captured == {"output": Path("private-output")}


def test_next_gate_distinguishes_evidence_replacement_and_story_render() -> None:
    from app.director_pipeline import DirectorPipelineResult
    from app.edit import CandidateEditReview
    from app.local_pipeline import _next_local_pipeline_gate

    rejected = CandidateEditReview(
        is_ready_for_edit=False,
        missing_duration_s=0.0,
        reasons=("rejected",),
        event_ids_requiring_evidence=(),
        rejected_event_ids=("event_001",),
    )
    ready = CandidateEditReview(
        is_ready_for_edit=True,
        missing_duration_s=0.0,
        reasons=(),
        event_ids_requiring_evidence=(),
        rejected_event_ids=(),
    )
    director_result = DirectorPipelineResult(
        universal_event_count=2,
        confirmed_event_count=2,
        composer="rule_based",
        fallback_used=False,
        scene_count=2,
        used_event_count=2,
        render_plan_status="ready_for_ffmpeg",
        render_plan_ready=True,
    )

    assert _next_local_pipeline_gate(rejected, None) == "replace_rejected_candidate_clips"
    assert _next_local_pipeline_gate(ready, None) == "run_offline_director"
    assert _next_local_pipeline_gate(ready, director_result) == "render_director_script"
