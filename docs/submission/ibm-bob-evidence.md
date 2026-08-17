# IBM Bob development evidence

> The IBM-specific track requirement was verified through the authenticated
> Devpost workflow on 2026-08-17. This index demonstrates Bob's development
> influence; registration, final track confirmation, and a sanitized screenshot
> remain separate gates.

## Retained source artifact

A detailed IBM Bob code-review transcript is retained outside the repository in
the local Codex attachment store. It described the architecture, traced the
GPS-to-render flow, identified three priority gaps, and listed focused missing
tests. The original artifact must remain private because its local path is not a
portable public reference.

The earlier Bob screenshots are no longer available at their recorded paths.
A new sanitized product-identifying screenshot is therefore still required.
`ibm-bob-review-sanitized.md` is the portable public-safe transcript summary.

## Findings and implemented response

| Bob finding | Implemented response | Verification |
|---|---|---|
| No Google ADK agent or tool wiring | Added a Google ADK `App`/`Agent`, fixed synthetic tool, local runner, object-style `AdkApp` wrapper, and hosted synthetic Runtime path | `tests/test_adk_agent.py`, `tests/test_agent_platform.py`, hosted tool/final-response flags |
| No transition from awaiting video evidence | Added `CONFIRMED` and `REJECTED`, attributed `evidence_source`, invariant checks, review reasons, and `confirmed_event_ids()` | `tests/test_evidence_status.py` |
| No concrete Gemini video transport | Added `VertexAIGeminiVideoTransport` for pre-approved `gs://` objects with interval metadata and JSON Schema output; no uploader was added | `tests/test_vertex_video_transport.py`; real-media call remains gated |
| Weak malformed-output tests | Added missing, empty, nonnumeric, boolean, and out-of-range field cases | `tests/test_gemini_video_analyzer.py` |
| Event-consolidation boundary gaps | Added singleton, exact 900-second boundary, and mixed-type tests | `tests/test_events.py` |
| Multi-clip FFmpeg command not covered | Added two-input ordering, input count, and concat-shape verification | `tests/test_render_plan.py` |
| Video clock-correction edges not covered | Adopted half-open file intervals and added boundary, negative-offset, and after-end tests | `tests/test_video_catalog.py` |
| Unknown event type not covered | Added fail-closed, zero-tool-call coverage | `tests/test_orchestrator.py` |
| Planner tie depended on input order | Added stable `event_id` tie-break and regression test | `tests/test_story_planner.py` |
| Windows-style source paths could bypass POSIX check | Validate both POSIX and Windows path semantics plus NUL input | `tests/test_render_plan.py` |

## Honest limitations

- The retained Bob review predates the ADK deployment, evidence-state, probe,
  inventory, bilingual UI, and Vertex video-transport work; its architecture
  summary is historical, not a description of the current repository.
- A sanitized IBM Bob screenshot still must be re-captured.
- The official IBM wording is verified, but the user has not yet completed
  registration, explicit rules agreement, or final form selection.
- Real-video Gemini analysis is not yet evidence; no private media transfer has
  been authorized.
