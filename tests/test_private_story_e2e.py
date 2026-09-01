from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.edit import CandidateEvidenceStatus
from app.local_pipeline import prepare_local_review_package
from app.private_story_e2e import run_private_story_e2e
from app.video import (
    LocalEvidenceDecision,
    LocalEvidenceReview,
    LocalVideoMetadata,
    write_local_evidence_review,
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
    calls: list[Path] = []

    def probe(path: Path) -> LocalVideoMetadata:
        calls.append(path)
        return _metadata(path)

    with pytest.raises(ValueError, match="must be confirmed"):
        run_private_story_e2e(package, probe=probe)

    assert calls == []
