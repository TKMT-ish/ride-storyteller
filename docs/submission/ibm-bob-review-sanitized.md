# Sanitized IBM Bob review record

## Evidence purpose

IBM Bob reviewed the Ride Storyteller codebase during development and produced a
structured architecture review, end-to-end flow trace, priority-gap analysis,
and missing-test list. This public-safe record summarizes that development use
without disclosing account details, credentials, cloud resource names, private
paths, GPS data, or video filenames.

The full source transcript is retained privately. This file is a faithful
summary, not an original screenshot and not a claim that Bob reviewed later code.

## Review scope at the time

Bob inspected the Python contracts, GPS parser and event extraction, rule-based
Story Agent and planner, media-search boundary, Gemini analysis boundary,
candidate edit gate, timestamp catalog, FFmpeg render planner, ADK handoff, and
local web demo.

Bob traced two related flows:

1. GPX input to route events, Story Plan, candidate clips, timestamp resolution,
   evidence gate, and inspectable FFmpeg plan.
2. A Story Agent sub-loop that requests media, analyzes a clip, and accepts,
   rejects, or escalates the story decision.

## Priority findings and implemented responses

| Bob development finding | Implemented response |
|---|---|
| No concrete Gemini video transport | Added a schema-constrained Vertex AI transport for an already-approved `gs://` object. It cannot upload local video. |
| No real Google ADK Agent/tool wiring | Added a fixed-synthetic ADK Agent, tool, runner, object-style `AdkApp`, and a verified synthetic-only Tokyo Runtime. |
| No evidence-state transition into the render gate | Added awaiting, confirmed, and rejected states, attribution, construction invariants, review reasons, and confirmed-event extraction. |
| Malformed model-output cases were incomplete | Added missing, empty, nonnumeric, boolean, and out-of-range structured-output tests. |
| Event, clock, render, planner, and path boundaries needed coverage | Added exact-window, multi-clip, half-open timestamp, negative-offset, stable tie-break, Windows-path, and fail-closed regression tests. |

The complete finding-to-test mapping is in `ibm-bob-evidence.md`.

## Evidence limitations

- Bob's review describes the repository before the later cloud, bilingual UI,
  deployment, and evidence-state work was added.
- The product-identifying sanitized screenshot is still a separate submission
  gate.
- This evidence supports IBM Bob use during development. It does not replace the
  Google Cloud runtime proof, hosted app, public repository, or real-media demo.
