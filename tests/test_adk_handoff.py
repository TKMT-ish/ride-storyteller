from app.agent_runtime import GoogleCloudRuntimeSettings, build_adk_handoff
from app.demo import build_demo_candidate_edit_plan, build_demo_story_plan


def test_adk_handoff_is_data_only_until_cloud_configuration_exists(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    candidate_plan, _ = build_demo_candidate_edit_plan()

    handoff = build_adk_handoff(build_demo_story_plan(), candidate_plan)

    assert handoff.runtime_status == "unconfigured"
    assert handoff.task == "ride_storyteller_edit_review"
    assert "GEMINI_MODEL" in handoff.required_configuration
    assert handoff.payload["google_cloud_configuration"]["status"] == "unconfigured"
    assert handoff.to_dict()["payload"]["story_plan"]  # type: ignore[index]


def test_google_cloud_settings_distinguish_configured_from_authenticated(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "ride-storyteller")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")

    settings = GoogleCloudRuntimeSettings.from_environment()

    assert settings.status == "configuration_present"
    assert settings.missing_configuration == ()
    assert settings.to_dict()["status"] == "configuration_present"


def test_adk_handoff_preserves_nested_contract_structure(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    candidate_plan, _ = build_demo_candidate_edit_plan()

    payload = build_adk_handoff(build_demo_story_plan(), candidate_plan).to_dict()

    assert payload["schema_version"] == "adk-handoff-v1"
    assert set(payload) == {
        "schema_version",
        "runtime_status",
        "task",
        "payload",
        "required_configuration",
    }
    nested = payload["payload"]
    assert set(nested) == {
        "story_plan",
        "candidate_edit_plan",
        "google_cloud_configuration",
    }
    assert nested["story_plan"]["selected_event_ids"]
    assert nested["candidate_edit_plan"]["clips"]
