"""Synthetic-fixture tests for app.agent_runtime.google_config.

GoogleCloudRuntimeSettings.from_environment() is the one place that turns
process/`.env` strings into the non-network "is Vertex AI configured" contract
that `app/web/server.py`, `app/agent_runtime/agent_platform.py`, and the ADK
agent wrappers all rely on -- but every one of those callers either builds a
`GoogleCloudRuntimeSettings` directly with literal values or monkeypatches
`from_environment` away, so the parsing rules (process-env-over-local-file
precedence, whitespace stripping, the exact-"true" gate on the Vertex AI
flag, and what `to_dict()` is and is not allowed to reveal) had no direct
coverage before this file. No real project id, location, model name, or
credential is used anywhere here -- every value below is invented for the
test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent_runtime.google_config import GoogleCloudRuntimeSettings

_ENV_KEYS = (
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GEMINI_MODEL",
    "GOOGLE_GENAI_USE_VERTEXAI",
)


@pytest.fixture(autouse=True)
def _clean_google_cloud_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test from whatever the real process environment holds."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _write_env_file(tmp_path: Path, contents: str) -> None:
    (tmp_path / ".env").write_text(contents, encoding="utf-8")


def test_reads_configuration_from_the_local_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_env_file(
        tmp_path,
        "GOOGLE_CLOUD_PROJECT=example-project\n"
        "GOOGLE_CLOUD_LOCATION=example-location\n"
        "GEMINI_MODEL=example-model\n"
        "GOOGLE_GENAI_USE_VERTEXAI=true\n",
    )
    settings = GoogleCloudRuntimeSettings.from_environment()
    assert settings == GoogleCloudRuntimeSettings(
        project="example-project",
        location="example-location",
        model="example-model",
        use_vertex_ai="true",
    )


def test_missing_env_file_yields_every_field_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = GoogleCloudRuntimeSettings.from_environment()
    assert settings == GoogleCloudRuntimeSettings(
        project="", location="", model="", use_vertex_ai=""
    )


def test_process_environment_takes_precedence_over_the_local_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_env_file(tmp_path, "GOOGLE_CLOUD_PROJECT=from-file\n")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "from-process-env")
    settings = GoogleCloudRuntimeSettings.from_environment()
    assert settings.project == "from-process-env"


def test_a_blank_process_environment_variable_still_wins_over_the_local_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # os.environ.get(key, default) only falls back to `default` when the key
    # is absent, not when it is set to "" -- an explicitly blank process
    # variable must not fall through to the local .env value.
    monkeypatch.chdir(tmp_path)
    _write_env_file(tmp_path, "GOOGLE_CLOUD_PROJECT=from-file\n")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "")
    settings = GoogleCloudRuntimeSettings.from_environment()
    assert settings.project == ""


def test_surrounding_whitespace_is_stripped_from_every_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "  example-project  ")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "  example-location  ")
    monkeypatch.setenv("GEMINI_MODEL", "  example-model  ")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "  true  ")
    settings = GoogleCloudRuntimeSettings.from_environment()
    assert settings == GoogleCloudRuntimeSettings(
        project="example-project",
        location="example-location",
        model="example-model",
        use_vertex_ai="true",
    )


def test_the_vertex_ai_flag_is_lowercased(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "True")
    settings = GoogleCloudRuntimeSettings.from_environment()
    assert settings.use_vertex_ai == "true"


def test_missing_configuration_lists_every_absent_setting() -> None:
    settings = GoogleCloudRuntimeSettings(project="", location="", model="", use_vertex_ai="")
    assert settings.missing_configuration == (
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "GEMINI_MODEL",
        "GOOGLE_GENAI_USE_VERTEXAI=true",
    )


def test_missing_configuration_is_empty_when_fully_configured() -> None:
    settings = GoogleCloudRuntimeSettings(
        project="example-project",
        location="example-location",
        model="example-model",
        use_vertex_ai="true",
    )
    assert settings.missing_configuration == ()


@pytest.mark.parametrize("flag_value", ["false", "1", "yes", ""])
def test_missing_configuration_requires_the_flag_to_be_exactly_true(
    flag_value: str,
) -> None:
    settings = GoogleCloudRuntimeSettings(
        project="example-project",
        location="example-location",
        model="example-model",
        use_vertex_ai=flag_value,
    )
    assert "GOOGLE_GENAI_USE_VERTEXAI=true" in settings.missing_configuration


def test_missing_configuration_reports_only_the_fields_that_are_absent() -> None:
    settings = GoogleCloudRuntimeSettings(
        project="example-project", location="", model="example-model", use_vertex_ai="true"
    )
    assert settings.missing_configuration == ("GOOGLE_CLOUD_LOCATION",)


def test_status_is_configuration_present_when_nothing_is_missing() -> None:
    settings = GoogleCloudRuntimeSettings(
        project="example-project",
        location="example-location",
        model="example-model",
        use_vertex_ai="true",
    )
    assert settings.status == "configuration_present"


def test_status_is_unconfigured_when_anything_is_missing() -> None:
    settings = GoogleCloudRuntimeSettings(
        project="", location="example-location", model="example-model", use_vertex_ai="true"
    )
    assert settings.status == "unconfigured"


def test_to_dict_reports_only_booleans_names_and_status_never_the_raw_values() -> None:
    settings = GoogleCloudRuntimeSettings(
        project="example-project",
        location="example-location",
        model="example-model",
        use_vertex_ai="true",
    )
    payload = settings.to_dict()
    assert payload == {
        "status": "configuration_present",
        "project_configured": True,
        "location_configured": True,
        "model_configured": True,
        "vertex_ai_enabled": True,
        "missing_configuration": [],
    }
    # Privacy invariant: none of the actual project/location/model strings
    # leak into the payload, only whether each is present.
    serialized = str(payload)
    assert "example-project" not in serialized
    assert "example-location" not in serialized
    assert "example-model" not in serialized


def test_to_dict_lists_the_missing_configuration_names_when_unconfigured() -> None:
    settings = GoogleCloudRuntimeSettings(project="", location="", model="", use_vertex_ai="")
    payload = settings.to_dict()
    assert payload["status"] == "unconfigured"
    assert payload["project_configured"] is False
    assert payload["vertex_ai_enabled"] is False
    assert payload["missing_configuration"] == [
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "GEMINI_MODEL",
        "GOOGLE_GENAI_USE_VERTEXAI=true",
    ]
