"""A private-media-safe Google ADK agent for the Ride Storyteller prototype."""

from __future__ import annotations

from dataclasses import dataclass

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.runners import InMemoryRunner
from google.genai import types

from .google_config import GoogleCloudRuntimeSettings

_APP_NAME = "ride_storyteller"
_SYNTHETIC_DEMO_PROMPT = (
    "合成のRide Storyteller映像証拠判断デモを実行してください。"
    "最初に利用可能なツールを必ず1回呼び出し、その結果だけを根拠に、"
    "映像証拠が必要かを日本語で2文以内で答えてください。"
    "座標、実GPS、実動画、Boxの取得は要求も言及もしないでください。"
)


class AdkSyntheticRunError(RuntimeError):
    """A non-sensitive local ADK execution failure."""


@dataclass(frozen=True)
class AdkSyntheticRun:
    """Safe execution metadata; model text and private inputs are not retained."""

    model: str
    final_response_received: bool
    tool_called: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "final_response_received": self.final_response_received,
            "tool_called": self.tool_called,
        }


def get_synthetic_ride_event() -> dict[str, object]:
    """Return one fixed, non-private event for the local ADK verification only."""
    return {
        "event_id": "synthetic_scenery_change",
        "event_type": "scenery_change",
        "importance_hint": 0.82,
        "reason": "The route summary indicates a synthetic high-interest transition.",
        "contains_real_gpx": False,
        "contains_real_media": False,
    }


def build_ride_storyteller_adk_app(settings: GoogleCloudRuntimeSettings) -> App:
    """Create an ADK app with no tool that can read or transfer private material."""
    _require_complete_configuration(settings)
    agent = Agent(
        name="ride_storyteller_evidence_agent",
        model=Gemini(
            model=settings.model,
            client_kwargs={
                "vertexai": True,
                "project": settings.project,
                "location": settings.location,
            },
        ),
        instruction=(
            "You are the evidence-decision component of Ride Storyteller. "
            "For the synthetic demo, call get_synthetic_ride_event before making a decision. "
            "You only reason from returned synthetic data. You must not request, read, upload, "
            "or infer real GPX, locations, video, credentials, or Box content. "
            "Describe only whether video evidence is needed and why."
        ),
        tools=[get_synthetic_ride_event],
        generate_content_config=types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=160,
        ),
    )
    return App(name=_APP_NAME, root_agent=agent)


async def run_synthetic_adk_demo(settings: GoogleCloudRuntimeSettings) -> AdkSyntheticRun:
    """Run one ADK invocation over fixed synthetic input and retain only safe metadata."""
    app = build_ride_storyteller_adk_app(settings)
    try:
        events = await InMemoryRunner(app=app).run_debug(_SYNTHETIC_DEMO_PROMPT, quiet=True)
    except Exception as error:
        raise AdkSyntheticRunError("Google ADK synthetic demo failed") from error

    tool_called = False
    final_response_received = False
    for event in events:
        content = getattr(event, "content", None)
        for part in getattr(content, "parts", ()) or ():
            if getattr(part, "function_call", None) is not None:
                tool_called = True
            text = getattr(part, "text", None)
            if isinstance(text, str) and text.strip():
                final_response_received = True

    if not tool_called:
        raise AdkSyntheticRunError("Google ADK synthetic demo did not call its required tool")
    if not final_response_received:
        raise AdkSyntheticRunError("Google ADK synthetic demo returned no final text")
    return AdkSyntheticRun(
        model=settings.model,
        final_response_received=True,
        tool_called=True,
    )


def _require_complete_configuration(settings: GoogleCloudRuntimeSettings) -> None:
    if settings.status == "configuration_present":
        return
    missing = ", ".join(settings.missing_configuration)
    raise AdkSyntheticRunError(f"Google Cloud configuration is incomplete: {missing}")
