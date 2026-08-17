"""Command-line entry point for the private-media-safe Gemini connection check."""

from __future__ import annotations

import json

from app.agent_runtime import GoogleCloudRuntimeSettings, run_synthetic_gemini_probe


def main() -> None:
    """Run the non-private connection check without exposing model output."""
    result = run_synthetic_gemini_probe(GoogleCloudRuntimeSettings.from_environment())
    print(json.dumps(result.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    main()
