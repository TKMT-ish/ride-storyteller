"""Provider-neutral handoff contracts for the future Google ADK runtime."""

from app.agent_runtime.adk_agent import (
    AdkSyntheticRun,
    AdkSyntheticRunError,
    build_ride_storyteller_adk_app,
    get_synthetic_ride_event,
    run_synthetic_adk_demo,
)
from app.agent_runtime.adk_handoff import AdkHandoff, build_adk_handoff
from app.agent_runtime.agent_platform import (
    AgentPlatformDeploymentError,
    AgentPlatformDeploymentSettings,
    AgentPlatformPreparationError,
    AgentPlatformRuntimeSettings,
    SyntheticAgentRuntimeVerification,
    build_agent_platform_adk_app,
    deploy_synthetic_agent_runtime,
    get_configured_synthetic_agent_runtime,
    get_synthetic_agent_runtime_verification_agent,
    run_hosted_synthetic_agent_runtime,
    verify_synthetic_agent_runtime,
)
from app.agent_runtime.gemini_probe import (
    GeminiConnectionProbe,
    GeminiConnectionProbeError,
    run_synthetic_gemini_probe,
)
from app.agent_runtime.google_config import GoogleCloudRuntimeSettings

__all__ = [
    "AdkHandoff",
    "AdkSyntheticRun",
    "AdkSyntheticRunError",
    "AgentPlatformDeploymentSettings",
    "AgentPlatformDeploymentError",
    "AgentPlatformPreparationError",
    "AgentPlatformRuntimeSettings",
    "GeminiConnectionProbe",
    "GeminiConnectionProbeError",
    "GoogleCloudRuntimeSettings",
    "SyntheticAgentRuntimeVerification",
    "build_ride_storyteller_adk_app",
    "build_adk_handoff",
    "build_agent_platform_adk_app",
    "deploy_synthetic_agent_runtime",
    "get_configured_synthetic_agent_runtime",
    "get_synthetic_agent_runtime_verification_agent",
    "get_synthetic_ride_event",
    "run_synthetic_adk_demo",
    "run_hosted_synthetic_agent_runtime",
    "run_synthetic_gemini_probe",
    "verify_synthetic_agent_runtime",
]
