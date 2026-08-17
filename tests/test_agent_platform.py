from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.agent_runtime import (
    AgentPlatformDeploymentError,
    AgentPlatformDeploymentSettings,
    AgentPlatformPreparationError,
    AgentPlatformRuntimeSettings,
    GoogleCloudRuntimeSettings,
    build_agent_platform_adk_app,
    deploy_synthetic_agent_runtime,
    get_configured_synthetic_agent_runtime,
    get_synthetic_agent_runtime_verification_agent,
    verify_synthetic_agent_runtime,
)
from app.agent_runtime.agent_platform import _stage_deployment_source_package


def _runtime_settings() -> GoogleCloudRuntimeSettings:
    return GoogleCloudRuntimeSettings(
        project="ride-storyteller",
        location="global",
        model="gemini-2.5-flash",
        use_vertex_ai="true",
    )


def test_agent_platform_wrapper_uses_official_adk_runtime_type_without_deploying() -> None:
    deployment = AgentPlatformDeploymentSettings(
        project="ride-storyteller",
        location="asia-northeast1",
        staging_bucket="gs://ride-storyteller-staging",
    )

    app = build_agent_platform_adk_app(_runtime_settings(), deployment)

    assert type(app).__name__ == "AdkApp"
    assert app.agent_framework == "google-adk"


def test_agent_platform_wrapper_initializes_the_configured_staging_bucket(monkeypatch) -> None:
    deployment = AgentPlatformDeploymentSettings(
        project="ride-storyteller",
        location="asia-northeast1",
        staging_bucket="gs://ride-storyteller-staging",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "app.agent_runtime.agent_platform.vertexai.init",
        lambda **kwargs: captured.update(kwargs),
    )

    build_agent_platform_adk_app(_runtime_settings(), deployment)

    assert captured["location"] == "asia-northeast1"
    assert captured["staging_bucket"] == "gs://ride-storyteller-staging"


def test_agent_platform_preflight_rejects_global_as_a_custom_runtime_location() -> None:
    deployment = AgentPlatformDeploymentSettings(
        project="ride-storyteller",
        location="global",
        staging_bucket="gs://ride-storyteller-staging",
    )

    assert deployment.status == "configuration_incomplete"
    assert "custom Agent Runtime requires a region" in deployment.missing_configuration[0]
    with pytest.raises(
        AgentPlatformPreparationError, match="deployment configuration is incomplete"
    ):
        build_agent_platform_adk_app(_runtime_settings(), deployment)


def test_agent_platform_preflight_returns_safe_metadata_only(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    deployment = AgentPlatformDeploymentSettings(
        project="ride-storyteller",
        location="asia-northeast1",
        staging_bucket="gs://private-ride-storyteller-staging",
    )

    payload = deployment.to_dict()

    assert payload["deployment_executed"] is False
    assert payload["private_data_used"] is False
    assert payload["status"] == "awaiting_external_verification"
    assert payload["missing_configuration"] == []
    assert "private-ride-storyteller-staging" not in str(payload)


def test_deploy_synthetic_agent_runtime_stages_only_the_app_package(monkeypatch) -> None:
    deployment = AgentPlatformDeploymentSettings(
        project="ride-storyteller",
        location="asia-northeast1",
        staging_bucket="gs://ride-storyteller-staging",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "app.agent_runtime.agent_platform.vertexai.init",
        lambda **_kwargs: None,
    )
    class FakeAgentEngines:
        def create(self, **kwargs):
            captured.update(kwargs)
            captured["staged_agent_exists"] = Path("app/deployable_agent.py").is_file()
            return object()

    class FakeClient:
        agent_engines = FakeAgentEngines()

    monkeypatch.setattr(
        "app.agent_runtime.agent_platform.agentplatform.Client", lambda **_kwargs: FakeClient()
    )

    deploy_synthetic_agent_runtime(_runtime_settings(), deployment)

    config = captured["config"]
    assert config.gcs_dir_name == "agent-runtime-synthetic-v1"
    assert config.min_instances == 0
    assert config.max_instances == 1
    assert config.resource_limits == {"cpu": "4", "memory": "4Gi"}
    assert config.container_concurrency == 9
    assert config.identity_type.name == "AGENT_IDENTITY"
    assert config.env_vars is None
    assert config.extra_packages == ["app"]
    assert captured["staged_agent_exists"] is True


def test_stage_deployment_source_package_preserves_app_import_root(tmp_path) -> None:
    staged_root = _stage_deployment_source_package(tmp_path)

    assert (staged_root / "app" / "__init__.py").is_file()
    assert (staged_root / "app" / "deployable_agent.py").is_file()
    assert not (staged_root / "app" / "agent_runtime").exists()
    assert len(list(staged_root.rglob("*.py"))) == 2
    assert not list(staged_root.rglob("*.gpx"))
    assert not list(staged_root.rglob("*.mp4"))
    assert not list(staged_root.rglob(".env"))


def test_get_verification_agent_uses_existing_runtime_resource(monkeypatch) -> None:
    deployment = AgentPlatformDeploymentSettings(
        project="ride-storyteller",
        location="asia-northeast1",
        staging_bucket="gs://ride-storyteller-staging",
    )
    expected_agent = object()
    captured: dict[str, object] = {}

    class FakeAgentEngines:
        def get(self, *, name: str):
            captured["name"] = name
            return expected_agent

    class FakeClient:
        agent_engines = FakeAgentEngines()

    def fake_client(**kwargs):
        captured.update(kwargs)
        return FakeClient()

    monkeypatch.setattr(
        "app.agent_runtime.agent_platform.vertexai.Client",
        fake_client,
    )
    remote_agent = type(
        "CreatedAgent",
        (),
        {"api_resource": type("Resource", (), {"name": "existing-runtime"})()},
    )()

    result = get_synthetic_agent_runtime_verification_agent(remote_agent, deployment)

    assert result is expected_agent
    assert captured == {
        "project": "ride-storyteller",
        "location": "asia-northeast1",
        "name": "existing-runtime",
    }


def test_get_verification_agent_rejects_missing_resource_name() -> None:
    deployment = AgentPlatformDeploymentSettings(
        project="ride-storyteller",
        location="asia-northeast1",
        staging_bucket="gs://ride-storyteller-staging",
    )

    with pytest.raises(AgentPlatformDeploymentError, match="has no resource name"):
        get_synthetic_agent_runtime_verification_agent(object(), deployment)


def test_runtime_reference_reports_presence_without_exposing_resource_name() -> None:
    reference = AgentPlatformRuntimeSettings(
        resource_name=(
            "projects/123456/locations/asia-northeast1/reasoningEngines/runtime-1"
        )
    )

    payload = reference.to_dict()

    assert payload == {
        "status": "configured",
        "runtime_reference_configured": True,
        "private_data_used": False,
        "missing_configuration": [],
    }
    assert "runtime-1" not in str(payload)


def test_get_configured_runtime_rejects_cross_region_reference() -> None:
    deployment = AgentPlatformDeploymentSettings(
        project="ride-storyteller",
        location="asia-northeast1",
        staging_bucket="gs://ride-storyteller-staging",
    )
    reference = AgentPlatformRuntimeSettings(
        resource_name="projects/123/locations/us-central1/reasoningEngines/runtime-1"
    )

    with pytest.raises(AgentPlatformPreparationError, match="invalid for this region"):
        get_configured_synthetic_agent_runtime(deployment, reference)


def test_get_configured_runtime_requires_expected_synthetic_agent(monkeypatch) -> None:
    deployment = AgentPlatformDeploymentSettings(
        project="ride-storyteller",
        location="asia-northeast1",
        staging_bucket="gs://ride-storyteller-staging",
    )
    reference = AgentPlatformRuntimeSettings(
        resource_name=(
            "projects/123456/locations/asia-northeast1/reasoningEngines/runtime-1"
        )
    )
    api_resource = type(
        "Resource",
        (),
        {
            "display_name": "A different Runtime",
            "spec": type("Spec", (), {"agent_framework": "google-adk"})(),
        },
    )()
    remote_agent = type("RemoteAgent", (), {"api_resource": api_resource})()
    fake_agent_engines = type(
        "AgentEngines",
        (),
        {"get": lambda self, *, name: remote_agent},
    )()
    fake_client = type("Client", (), {"agent_engines": fake_agent_engines})()
    monkeypatch.setattr(
        "app.agent_runtime.agent_platform.vertexai.Client",
        lambda **_kwargs: fake_client,
    )

    with pytest.raises(AgentPlatformDeploymentError, match="not the expected synthetic"):
        get_configured_synthetic_agent_runtime(deployment, reference)


def test_verify_synthetic_agent_runtime_retains_metadata_only() -> None:
    class RemoteAgent:
        async def async_stream_query(self, *, message: str, user_id: str):
            assert "合成" in message
            assert user_id == "synthetic-deployment-verification"
            yield {"content": {"parts": [{"functionCall": {"name": "synthetic"}}]}}
            yield {"content": {"parts": [{"text": "non-sensitive synthetic result"}]}}

    result = asyncio.run(verify_synthetic_agent_runtime(RemoteAgent()))

    assert result.to_dict() == {
        "private_data_used": False,
        "final_response_received": True,
        "tool_called": True,
    }


def test_verify_synthetic_agent_runtime_retries_one_incomplete_stream() -> None:
    class RemoteAgent:
        attempts = 0

        async def async_stream_query(self, *, message: str, user_id: str):
            self.attempts += 1
            yield {"content": {"parts": [{"functionCall": {"name": "synthetic"}}]}}
            if self.attempts == 2:
                yield {"content": {"parts": [{"text": "synthetic result"}]}}

    remote_agent = RemoteAgent()

    result = asyncio.run(verify_synthetic_agent_runtime(remote_agent))

    assert result.tool_called is True
    assert result.final_response_received is True
    assert remote_agent.attempts == 2


def test_verify_synthetic_agent_runtime_rejects_missing_tool_call() -> None:
    class RemoteAgent:
        async def async_stream_query(self, *, message: str, user_id: str):
            yield {"content": {"parts": [{"text": "synthetic result"}]}}

    with pytest.raises(AgentPlatformDeploymentError, match="required synthetic tool"):
        asyncio.run(verify_synthetic_agent_runtime(RemoteAgent()))
