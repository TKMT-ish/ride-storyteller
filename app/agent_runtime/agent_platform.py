"""Safe Agent Platform preparation, deployment, and verification helpers.

The deployment entry point in this module is intentionally limited to the fixed
synthetic ADK app.  It never reads GPX, video, Box content, local ``.env`` values,
or user-provided prompt text.  Deploying creates a remote Agent Runtime resource,
so callers must invoke it only after explicit approval.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import agentplatform
import vertexai
from vertexai import agent_engines

from app.config import load_local_environment
from app.deployable_agent import build_synthetic_deployment_agent

from .adk_agent import _SYNTHETIC_DEMO_PROMPT
from .google_config import GoogleCloudRuntimeSettings


class AgentPlatformPreparationError(RuntimeError):
    """Raised before a local Agent Runtime wrapper can be prepared safely."""


class AgentPlatformDeploymentError(RuntimeError):
    """A non-sensitive Agent Runtime deployment or synthetic verification failure."""


@dataclass(frozen=True)
class SyntheticAgentRuntimeVerification:
    """Only metadata retained from one deployed, synthetic-only interaction."""

    final_response_received: bool
    tool_called: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "private_data_used": False,
            "final_response_received": self.final_response_received,
            "tool_called": self.tool_called,
        }


_SYNTHETIC_DEPLOYMENT_REQUIREMENTS = (
    "google-cloud-aiplatform[agent_engines,adk]==1.163.0",
    "google-adk[gcp]==2.6.3",
    "google-genai==2.17.0",
)
_SYNTHETIC_DEPLOYMENT_GCS_DIRECTORY = "agent-runtime-synthetic-v1"
_SYNTHETIC_DEPLOYMENT_DISPLAY_NAME = "Ride Storyteller — Synthetic ADK Demo"
_SYNTHETIC_DEPLOYMENT_DESCRIPTION = (
    "Synthetic-only verification deployment. No GPX, video, Box content, "
    "credentials, or user-provided input is used."
)
_SYNTHETIC_DEPLOYMENT_USER_ID = "synthetic-deployment-verification"
_SYNTHETIC_VERIFICATION_ATTEMPTS = 2


@dataclass(frozen=True)
class AgentPlatformDeploymentSettings:
    """Non-secret configuration required before an object-style deployment.

    The inference endpoint and the Agent Runtime deployment endpoint are distinct:
    local Gemini inference can use ``global``, while a custom Agent Runtime must
    use a supported regional location. The selected region is read from the
    ignored local environment; its presence never confirms that the staging
    bucket exists or that a deployment is approved.
    """

    project: str
    location: str
    staging_bucket: str

    @classmethod
    def from_environment(
        cls, runtime_settings: GoogleCloudRuntimeSettings | None = None
    ) -> "AgentPlatformDeploymentSettings":
        runtime = runtime_settings or GoogleCloudRuntimeSettings.from_environment()
        local_values = load_local_environment()
        return cls(
            project=runtime.project,
            location=os.environ.get(
                "AGENT_PLATFORM_LOCATION", local_values.get("AGENT_PLATFORM_LOCATION", "")
            ).strip(),
            staging_bucket=os.environ.get(
                "AGENT_PLATFORM_STAGING_BUCKET",
                local_values.get("AGENT_PLATFORM_STAGING_BUCKET", ""),
            ).strip(),
        )

    @property
    def missing_configuration(self) -> tuple[str, ...]:
        missing: list[str] = []
        if not self.project:
            missing.append("GOOGLE_CLOUD_PROJECT")
        if not self.location:
            missing.append("AGENT_PLATFORM_LOCATION")
        elif self.location.lower() == "global":
            missing.append("AGENT_PLATFORM_LOCATION (custom Agent Runtime requires a region)")
        if not self.staging_bucket.startswith("gs://"):
            missing.append("AGENT_PLATFORM_STAGING_BUCKET (gs://...)")
        return tuple(missing)

    @property
    def status(self) -> str:
        """Never report deployment readiness from local configuration alone."""
        if self.missing_configuration:
            return "configuration_incomplete"
        return "awaiting_external_verification"

    def to_dict(self) -> dict[str, object]:
        """Expose configuration state only; do not expose bucket names or identities."""
        return {
            "status": self.status,
            "deployment_executed": False,
            "project_configured": bool(self.project),
            "regional_location_configured": bool(self.location)
            and self.location.lower() != "global",
            "staging_bucket_configured": self.staging_bucket.startswith("gs://"),
            "agent_framework": "google-adk",
            "private_data_used": False,
            "missing_configuration": list(self.missing_configuration),
            "external_verification_required": [
                "Cloud Billing",
                "Agent Platform API",
                "Cloud Storage API",
                "Agent Platform User and Storage permissions",
                "runtime identity and explicit deployment approval",
            ],
        }


@dataclass(frozen=True)
class AgentPlatformRuntimeSettings:
    """Safe local reference to one already-created synthetic Runtime."""

    resource_name: str

    @classmethod
    def from_environment(cls) -> "AgentPlatformRuntimeSettings":
        local_values = load_local_environment()
        return cls(
            resource_name=os.environ.get(
                "AGENT_PLATFORM_RUNTIME_NAME",
                local_values.get("AGENT_PLATFORM_RUNTIME_NAME", ""),
            ).strip()
        )

    @property
    def missing_configuration(self) -> tuple[str, ...]:
        if not self.resource_name:
            return ("AGENT_PLATFORM_RUNTIME_NAME",)
        return ()

    def validate_for(self, deployment_settings: AgentPlatformDeploymentSettings) -> None:
        """Reject malformed or cross-region Runtime references without exposing them."""
        parts = self.resource_name.split("/")
        valid_structure = (
            len(parts) == 6
            and parts[0] == "projects"
            and bool(parts[1])
            and parts[2] == "locations"
            and parts[3] == deployment_settings.location
            and parts[4] == "reasoningEngines"
            and bool(parts[5])
        )
        if not valid_structure:
            raise AgentPlatformPreparationError(
                "Configured synthetic Agent Runtime reference is invalid for this region"
            )

    def to_dict(self) -> dict[str, object]:
        """Report only presence; never expose the cloud resource identifier."""
        return {
            "status": "configured" if not self.missing_configuration else "unconfigured",
            "runtime_reference_configured": not self.missing_configuration,
            "private_data_used": False,
            "missing_configuration": list(self.missing_configuration),
        }


def build_agent_platform_adk_app(
    runtime_settings: GoogleCloudRuntimeSettings,
    deployment_settings: AgentPlatformDeploymentSettings,
) -> Any:
    """Return the official ``AdkApp`` wrapper without deploying it.

    Calling ``client.agent_engines.create`` is deliberately outside this function.
    That call uploads a bundle and creates a remote Agent Runtime resource, so it
    remains a separate explicit-approval step.
    """
    _initialize_agent_platform(runtime_settings, deployment_settings)
    return agent_engines.AdkApp(
        agent=build_synthetic_deployment_agent(runtime_settings.model)
    )


def deploy_synthetic_agent_runtime(
    runtime_settings: GoogleCloudRuntimeSettings,
    deployment_settings: AgentPlatformDeploymentSettings,
) -> Any:
    """Create the approved synthetic-only ``AdkApp`` Agent Runtime.

    Only Python source under the project's ``app/`` package is staged.  The local
    ``.env`` file, tests, documentation, GPX files, video, and Box content are
    deliberately outside that package and are never included.
    """
    app = build_agent_platform_adk_app(runtime_settings, deployment_settings)
    try:
        client = agentplatform.Client(
            project=deployment_settings.project,
            location=deployment_settings.location,
        )
        with tempfile.TemporaryDirectory(prefix="ride-storyteller-agent-runtime-") as temp_dir:
            source_package = _stage_deployment_source_package(Path(temp_dir))
            previous_directory = Path.cwd()
            try:
                os.chdir(source_package)
                return client.agent_engines.create(
                    agent=app,
                    config=agentplatform.types.AgentEngineConfig(
                        requirements=list(_SYNTHETIC_DEPLOYMENT_REQUIREMENTS),
                        stagingBucket=deployment_settings.staging_bucket,
                        displayName=_SYNTHETIC_DEPLOYMENT_DISPLAY_NAME,
                        description=_SYNTHETIC_DEPLOYMENT_DESCRIPTION,
                        gcsDirName=_SYNTHETIC_DEPLOYMENT_GCS_DIRECTORY,
                        extraPackages=["app"],
                        identityType=agentplatform.types.IdentityType.AGENT_IDENTITY,
                        minInstances=0,
                        maxInstances=1,
                        resourceLimits={"cpu": "4", "memory": "4Gi"},
                        containerConcurrency=9,
                    ),
                )
            finally:
                os.chdir(previous_directory)
    except Exception as error:
        raise AgentPlatformDeploymentError(
            "Synthetic Agent Runtime deployment failed; no response body was retained"
        ) from error


def get_synthetic_agent_runtime_verification_agent(
    remote_agent: Any,
    deployment_settings: AgentPlatformDeploymentSettings,
) -> Any:
    """Return a compatible client for verification of a created Runtime.

    Runtime creation remains on the current ``agentplatform.Client`` API.  With
    the pinned SDK, however, that client's asynchronous streaming path may yield
    no events even though the deployed Runtime is healthy.  The legacy Vertex AI
    client currently provides the working asynchronous event stream, so it is
    used only to retrieve the already-created Runtime for verification.
    """
    api_resource = getattr(remote_agent, "api_resource", None)
    resource_name = getattr(api_resource, "name", "")
    if not isinstance(resource_name, str) or not resource_name.strip():
        raise AgentPlatformDeploymentError(
            "Synthetic Agent Runtime verification target has no resource name"
        )

    try:
        client = vertexai.Client(
            project=deployment_settings.project,
            location=deployment_settings.location,
        )
        return client.agent_engines.get(name=resource_name)
    except Exception as error:
        raise AgentPlatformDeploymentError(
            "Synthetic Agent Runtime verification client preparation failed"
        ) from error


def get_configured_synthetic_agent_runtime(
    deployment_settings: AgentPlatformDeploymentSettings,
    runtime_settings: AgentPlatformRuntimeSettings | None = None,
) -> Any:
    """Retrieve the configured existing Runtime through the compatibility client."""
    reference = runtime_settings or AgentPlatformRuntimeSettings.from_environment()
    if reference.missing_configuration:
        raise AgentPlatformPreparationError(
            "Synthetic Agent Runtime reference is not configured"
        )
    reference.validate_for(deployment_settings)

    try:
        client = vertexai.Client(
            project=deployment_settings.project,
            location=deployment_settings.location,
        )
        remote_agent = client.agent_engines.get(name=reference.resource_name)
    except Exception as error:
        raise AgentPlatformDeploymentError(
            "Configured synthetic Agent Runtime could not be retrieved"
        ) from error

    api_resource = getattr(remote_agent, "api_resource", None)
    display_name = getattr(api_resource, "display_name", "")
    spec = getattr(api_resource, "spec", None)
    agent_framework = getattr(spec, "agent_framework", "")
    if display_name != _SYNTHETIC_DEPLOYMENT_DISPLAY_NAME or agent_framework != "google-adk":
        raise AgentPlatformDeploymentError(
            "Configured Agent Runtime is not the expected synthetic Google ADK Runtime"
        )
    return remote_agent


def run_hosted_synthetic_agent_runtime(
    deployment_settings: AgentPlatformDeploymentSettings | None = None,
    runtime_settings: AgentPlatformRuntimeSettings | None = None,
) -> SyntheticAgentRuntimeVerification:
    """Run fixed verification while preserving the compatibility client lifecycle."""
    deployment = deployment_settings or AgentPlatformDeploymentSettings.from_environment()
    _require_deployment_configuration(
        GoogleCloudRuntimeSettings.from_environment(),
        deployment,
    )
    remote_agent = get_configured_synthetic_agent_runtime(deployment, runtime_settings)
    return asyncio.run(verify_synthetic_agent_runtime(remote_agent))


async def verify_synthetic_agent_runtime(remote_agent: Any) -> SyntheticAgentRuntimeVerification:
    """Run the fixed synthetic prompt against a deployed Agent Runtime.

    The result intentionally retains only whether a tool call and final response
    were observed.  It does not log or return model text.
    """
    any_tool_called = False
    any_final_response_received = False
    try:
        for _attempt in range(_SYNTHETIC_VERIFICATION_ATTEMPTS):
            events = remote_agent.async_stream_query(
                message=_SYNTHETIC_DEMO_PROMPT,
                user_id=_SYNTHETIC_DEPLOYMENT_USER_ID,
            )
            tool_called = False
            final_response_received = False
            async for event in events:
                event_tool_called, event_response_received = _synthetic_event_flags(event)
                tool_called = tool_called or event_tool_called
                final_response_received = (
                    final_response_received or event_response_received
                )
            any_tool_called = any_tool_called or tool_called
            any_final_response_received = (
                any_final_response_received or final_response_received
            )
            if tool_called and final_response_received:
                return SyntheticAgentRuntimeVerification(
                    tool_called=True,
                    final_response_received=True,
                )
    except Exception as error:
        raise AgentPlatformDeploymentError(
            "Synthetic Agent Runtime verification failed; no response body was retained"
        ) from error

    if not any_tool_called:
        raise AgentPlatformDeploymentError(
            "Synthetic Agent Runtime did not call its required synthetic tool"
        )
    if not any_final_response_received:
        raise AgentPlatformDeploymentError(
            "Synthetic Agent Runtime returned no final response"
        )
    raise AgentPlatformDeploymentError(
        "Synthetic Agent Runtime did not complete tool use and a final response "
        "within the same verification attempt"
    )


def _require_deployment_configuration(
    runtime_settings: GoogleCloudRuntimeSettings,
    deployment_settings: AgentPlatformDeploymentSettings,
) -> None:
    if runtime_settings.status != "configuration_present":
        missing = ", ".join(runtime_settings.missing_configuration)
        raise AgentPlatformPreparationError(
            f"Google Cloud runtime configuration is incomplete: {missing}"
        )
    if deployment_settings.missing_configuration:
        missing = ", ".join(deployment_settings.missing_configuration)
        raise AgentPlatformPreparationError(
            f"Agent Platform deployment configuration is incomplete: {missing}"
        )


def _initialize_agent_platform(
    runtime_settings: GoogleCloudRuntimeSettings,
    deployment_settings: AgentPlatformDeploymentSettings,
) -> None:
    _require_deployment_configuration(runtime_settings, deployment_settings)
    vertexai.init(
        project=deployment_settings.project,
        location=deployment_settings.location,
        staging_bucket=deployment_settings.staging_bucket,
    )


def _deployment_source_directory() -> Path:
    """Return the local Python package boundary for a safe deployment copy."""
    return Path(__file__).resolve().parents[1]


def _stage_deployment_source_package(destination: Path) -> Path:
    """Copy only the isolated deployment Agent under an ``app/`` import root.

    Agent Runtime extracts each ``extraPackages`` directory by its contents.  The
    temporary parent therefore contains only ``app/__init__.py`` and the minimal
    synthetic Agent module. Repository settings, adapters, tests, and media are
    not included.
    """
    source_root = _deployment_source_directory()
    source_files = (
        source_root / "__init__.py",
        source_root / "deployable_agent.py",
    )
    for source_file in source_files:
        target_file = destination / source_file.relative_to(source_root.parent)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)
    return destination


def _synthetic_event_flags(event: Any) -> tuple[bool, bool]:
    """Extract only safe completion metadata from an ADK event or event dictionary."""
    content = _event_value(event, "content")
    parts = _event_value(content, "parts") or ()
    tool_called = False
    final_response_received = False
    for part in parts:
        if _event_value(part, "function_call") is not None or _event_value(
            part, "functionCall"
        ) is not None:
            tool_called = True
        text = _event_value(part, "text")
        if isinstance(text, str) and text.strip():
            final_response_received = True
    return tool_called, final_response_received


def _event_value(event: Any, key: str) -> Any:
    if isinstance(event, dict):
        return event.get(key)
    return getattr(event, key, None)
