"""Command-line entry point for Ride Storyteller's non-private ADK check."""

from __future__ import annotations

import asyncio
import json

from app.agent_runtime import GoogleCloudRuntimeSettings, run_synthetic_adk_demo


def main() -> None:
    """Run the fixed synthetic ADK workflow without printing model output."""
    result = asyncio.run(run_synthetic_adk_demo(GoogleCloudRuntimeSettings.from_environment()))
    print(json.dumps(result.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    main()
