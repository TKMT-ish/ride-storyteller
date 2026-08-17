"""Deploy and verify the approved, synthetic-only Agent Runtime demo."""

from __future__ import annotations

import asyncio
import json

from .agent_platform import (
    AgentPlatformDeploymentError,
    AgentPlatformDeploymentSettings,
    deploy_synthetic_agent_runtime,
    get_synthetic_agent_runtime_verification_agent,
    verify_synthetic_agent_runtime,
)
from .google_config import GoogleCloudRuntimeSettings


def main() -> None:
    """Print safe completion metadata without model output or credentials."""
    runtime_settings = GoogleCloudRuntimeSettings.from_environment()
    deployment_settings = AgentPlatformDeploymentSettings.from_environment(runtime_settings)
    remote_agent = deploy_synthetic_agent_runtime(runtime_settings, deployment_settings)
    verification_agent = get_synthetic_agent_runtime_verification_agent(
        remote_agent,
        deployment_settings,
    )
    verification = asyncio.run(verify_synthetic_agent_runtime(verification_agent))
    print(
        json.dumps(
            {
                "deployment_created": True,
                "runtime_location": deployment_settings.location,
                **verification.to_dict(),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except AgentPlatformDeploymentError as error:
        raise SystemExit(str(error)) from error
