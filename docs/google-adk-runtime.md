# Google ADK runtime boundary

## Purpose

This project now includes a local Google ADK implementation for the hackathon's
Gemini + Google Cloud Agent Builder direction. It is deliberately a
private-media-safe demonstration: the ADK agent has exactly one function tool,
and that tool returns a fixed synthetic event only.

## What the agent can and cannot do

- It can use Gemini through Vertex AI with local ADC.
- It can call `get_synthetic_ride_event()` to decide whether a synthetic event
  needs video evidence.
- It cannot read GPX files, route coordinates, video files, Box content, or
  credentials.
- It cannot upload media or GPS data. Those capabilities require a separate,
  explicit approval boundary after the real materials are available.

## Local verification

Run one fixed, non-private ADK invocation:

```text
.venv/bin/python -m app.adk_synthetic_demo
```

Successful output reports only the model name plus whether the function tool and
final response were received. It never prints or stores the model response.

## Hosted synthetic verification

The app uses Google ADK's `App` and `Agent` objects, with explicit Vertex AI
project and inference-location settings. It is wrapped as the official
`vertexai.agent_engines.AdkApp` type and one approved synthetic-only Agent
Runtime is deployed in `asia-northeast1` (Tokyo). The hosted verification has
confirmed the fixed tool call and final Gemini response without retaining the
response text.

The local Gemini inference endpoint continues to use `global`; the hosted Agent
Runtime remains regional. The local UI's cloud Runtime control accepts an empty
POST only and cannot send user input, GPX, coordinates, media, or Box content.
Its output contains safe completion flags only and explicitly marks the call as
external and potentially billable.
See [agent-platform-deployment-preflight.md](agent-platform-deployment-preflight.md).
