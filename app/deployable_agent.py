"""Minimal synthetic-only ADK Agent used exclusively by Agent Runtime."""

from __future__ import annotations

from google.adk.agents import Agent


def get_synthetic_deployment_event() -> dict[str, object]:
    """Return one fixed event without reading local or private data."""
    return {
        "event_id": "synthetic_scenery_change",
        "event_type": "scenery_change",
        "importance_hint": 0.82,
        "reason": "The route summary indicates a synthetic high-interest transition.",
        "contains_real_gpx": False,
        "contains_real_media": False,
    }


def build_synthetic_deployment_agent(model: str) -> Agent:
    """Build an official-sample-style Agent with one deterministic tool."""
    return Agent(
        name="ride_storyteller_evidence_agent",
        model=model,
        instruction=(
            "You are the synthetic evidence-decision component of Ride Storyteller. "
            "Always call get_synthetic_deployment_event before answering. Use only its "
            "fixed synthetic result. Never request or infer real GPX, locations, video, "
            "credentials, or Box content. Answer in Japanese in at most two sentences."
        ),
        tools=[get_synthetic_deployment_event],
    )
