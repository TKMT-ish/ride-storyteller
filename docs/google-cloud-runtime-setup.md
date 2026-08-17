# Google Cloud runtime setup gate

## Purpose

This document records the configuration and safety boundary for Ride Storyteller's
minimal Vertex AI/Gemini connection check. Google ADK and one synthetic-only
Agent Platform Runtime are now implemented and verified separately. This still
does not establish compatibility with any distinct Agent Builder requirement in
the final hackathon environment.

## Local configuration

Keep the following values only in the Git-ignored local `.env` file:

```text
GOOGLE_CLOUD_PROJECT=
GOOGLE_CLOUD_LOCATION=
GOOGLE_GENAI_USE_VERTEXAI=true
GEMINI_MODEL=
```

`GOOGLE_CLOUD_PROJECT` is the project ID, not the display name. The current local
development selection is `global` with `gemini-2.5-flash`, after confirming that
Gemini 2.5 Flash appears in the project's Model Garden. Never store a
service-account key in this repository or `.env`; use local Application Default
Credentials (ADC) instead.

## Minimal connection probe

`run_synthetic_gemini_probe()` makes one short request with the fixed text
`Reply with exactly: RIDE_STORYTELLER_GEMINI_OK`. It sends no GPX, media asset,
route coordinate, user-authored story, or generated response to logs. A successful
probe only establishes that the selected model can receive a minimal request from
this machine. It disables Gemini thinking for this fixed short probe so the small
output budget is reserved for the response rather than hidden reasoning. It does
not prove video analysis, Google ADK, or Agent Builder.

Run the same non-private check locally with:

```text
.venv/bin/python -m app.gemini_probe
```

## Completed external gate (2026-08-16)

The existing probe was run from this development machine after local ADC
and its quota project were configured. It used the Vertex AI path with project
`ride-storyteller`, location `global`, and model `gemini-2.5-flash`. The only
application content sent was the probe's fixed synthetic text; it did not read
or send a GPX file, video, coordinate, personal story text, or other private
media.

The call received a non-empty response. The response body was intentionally
not persisted, logged, or recorded here. This result confirms only a minimal
text request from this machine. It does not confirm video analysis, Google ADK
tool execution, Agent Platform deployment, or permission to transfer private
ride material.

## Remaining live validation

The regional Runtime and dedicated staging bucket gates were completed for one
approved synthetic-only deployment. Billing, APIs, and deployment access were
checked before creation. The remaining live gates are:

1. Keep real GPX/video private until the user explicitly approves a specific
   transfer to a Google service.
2. Validate a real-video call only after separate storage, retention, cost, and
   deletion decisions; never reuse the Agent Runtime staging bucket for media.
3. Re-check the exact current hackathon environment and any distinct Agent
   Builder requirement.

See [agent-platform-deployment-preflight.md](agent-platform-deployment-preflight.md)
and [google-video-transport.md](google-video-transport.md).

## Runtime-state meanings

- `unconfigured`: one or more of the four local settings is absent. No Google
  call is attempted.
- `configuration_present`: all four settings are present. This is **not** proof
  of authentication, API enablement, a working model, or a successful request.
