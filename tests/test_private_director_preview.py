"""Tests for the private, identifier-free DirectorScript browser preview."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.web.private_director_preview import (
    PRIVATE_DIRECTOR_SCRIPT_PATH_ENV,
    PrivateDirectorPreview,
    PrivateDirectorPreviewError,
)


def _artifact(*, scene_types: list[str] | None = None) -> dict[str, object]:
    roles = scene_types or ["hook", "build_up", "climax", "resolution"]
    return {
        "schema_version": "director-script-v1",
        "metadata": {
            "composer": "rule_based",
            "event_count_in": len(roles),
            "event_count_used": len(roles),
            "arc_names": roles,
        },
        "scenes": [
            {
                "scene_id": f"scene_{role}",
                "scene_type": role,
                "transition_type": "cut",
                "overlay_text": "A private-looking but generic line" if index == 0 else None,
                "clips": [
                    {
                        "event_id": f"event-{index}",
                        "source_asset_id": "private-asset-id",
                        "source_start_sec": 12.0,
                        "source_end_sec": 24.0,
                        "file_name": "PRIVATE.MP4",
                    }
                ],
            }
            for index, role in enumerate(roles)
        ],
    }


def _write_artifact(path: Path, **kwargs: object) -> Path:
    path.write_text(json.dumps(_artifact(**kwargs)), encoding="utf-8")
    return path


def test_payload_contains_only_browser_safe_story_structure(tmp_path: Path) -> None:
    preview = PrivateDirectorPreview.from_file(_write_artifact(tmp_path / "script.json"))

    payload = preview.payload()
    serialized = json.dumps(payload)

    assert payload["local_only"] is True
    assert payload["external_data_sent"] is False
    assert payload["director_script"] == {
        "composer": "rule_based",
        "event_count_in": 4,
        "event_count_used": 4,
        "scenes": [
            {
                "role": "hook",
                "event_count": 1,
                "transition_type": "cut",
                "overlay_text": "A private-looking but generic line",
            },
            {
                "role": "build_up",
                "event_count": 1,
                "transition_type": "cut",
                "overlay_text": None,
            },
            {
                "role": "climax",
                "event_count": 1,
                "transition_type": "cut",
                "overlay_text": None,
            },
            {
                "role": "resolution",
                "event_count": 1,
                "transition_type": "cut",
                "overlay_text": None,
            },
        ],
    }
    for forbidden in (
        "event_id", "source_asset_id", "source_start_sec", "source_end_sec",
        "file_name", "PRIVATE.MP4", "private-asset-id",
    ):
        assert forbidden not in serialized


def test_rejects_out_of_order_or_duplicate_roles(tmp_path: Path) -> None:
    out_of_order = _write_artifact(
        tmp_path / "out-of-order.json", scene_types=["climax", "hook"]
    )
    duplicate_role = _write_artifact(
        tmp_path / "duplicate.json", scene_types=["hook", "hook"]
    )

    with pytest.raises(PrivateDirectorPreviewError, match="invalid scene order"):
        PrivateDirectorPreview.from_file(out_of_order).payload()
    with pytest.raises(PrivateDirectorPreviewError, match="invalid scene order"):
        PrivateDirectorPreview.from_file(duplicate_role).payload()


def test_rejects_transition_not_supported_by_the_deterministic_editor(tmp_path: Path) -> None:
    artifact = _artifact(scene_types=["hook"])
    artifact["scenes"][0]["transition_type"] = "fade"  # type: ignore[index]
    path = tmp_path / "fade.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")

    with pytest.raises(PrivateDirectorPreviewError, match="invalid transition"):
        PrivateDirectorPreview.from_file(path).payload()


def test_from_environment_requires_explicit_configured_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PRIVATE_DIRECTOR_SCRIPT_PATH_ENV, raising=False)

    with pytest.raises(PrivateDirectorPreviewError, match="not configured"):
        PrivateDirectorPreview.from_environment()

    artifact = _write_artifact(tmp_path / "script.json")
    monkeypatch.setenv(PRIVATE_DIRECTOR_SCRIPT_PATH_ENV, str(artifact))
    assert PrivateDirectorPreview.from_environment().payload()["local_only"] is True
