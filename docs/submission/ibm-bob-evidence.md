# IBM Bob development evidence

> The IBM-specific track requirement was verified through the authenticated
> Devpost workflow on 2026-08-17. This index demonstrates Bob's development
> influence. Registration, the IBM track selection, and a sanitized
> project-specific IBM Bob screenshot are complete.

## Retained source artifact

A detailed IBM Bob code-review transcript is retained outside the repository in
the local Codex attachment store. It described the architecture, traced the
GPS-to-render flow, identified three priority gaps, and listed focused missing
tests. The original artifact must remain private because its local path is not a
portable public reference.

The earlier Bob screenshots are no longer available at their recorded paths;
the known locations were checked again on 2026-08-24. A replacement screenshot
was captured and validated on the same date.
`ibm-bob-review-sanitized.md` is the portable public-safe transcript summary.

## Sanitized screenshot — 2026-08-24

[`assets/06-ibm-bob-video-evidence-gate.png`](assets/06-ibm-bob-video-evidence-gate.png)
shows the IBM Bob product identity, the Ride Storyteller project context, the
public-only review prompt, and Bob's concrete finding about the fail-closed
render gate in `app/edit/render_plan.py` with its focused test in
`tests/test_render_plan.py`.

The image was inspected at its original 3232 x 3548 resolution. It does not
show an email address, account identity, credential, environment value, cloud
resource name, absolute filesystem path, GPX coordinate, or private media name.
The stated safeguard was independently checked against the current source and
test before the image was accepted.

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

## Submission evidence package — verified 2026-08-31

The current official IBM-track rule requires that the project be built using
IBM Bob during development and that the submission demonstrate that use. It
does not prescribe a single evidence format. This package therefore preserves
four mutually reinforcing, public-safe records:

1. **Product-specific visual evidence** —
   [`assets/06-ibm-bob-video-evidence-gate.png`](assets/06-ibm-bob-video-evidence-gate.png)
   shows IBM Bob, the Ride Storyteller context, and a concrete render-gate
   finding. The checked-in asset has SHA-256
   `e6f70ce05ede04d7487f2377eddbc62aa04f9cc9cec785081c40663684f5242a`.
2. **Portable review summary** —
   [`ibm-bob-review-sanitized.md`](ibm-bob-review-sanitized.md) describes the
   review scope, the flow Bob examined, and the resulting findings without
   reproducing private paths, account data, media, or credentials.
3. **Finding-to-implementation mapping** — the table above connects each
   substantive finding to repository files and focused verification.
4. **Rule and submission context** —
   [`official-rules-audit.md`](official-rules-audit.md) records the IBM-track
   requirement; the project README identifies the IBM track and this evidence
   strategy for a reviewer.

On 2026-08-31, the evidence image was confirmed as a tracked repository asset
and its SHA-256 was recomputed. The focused render-plan test remains the
source-level verification of the screenshot's stated fail-closed safeguard.
Exact Bob credit consumption, costs, and account details are intentionally not
part of this evidence package.

For the final three-minute submission video, show the visual evidence together
with the finding-to-test mapping. Do not represent it as proof that Bob ran the
application, processed private media, or reviewed later unverified changes.

## Honest limitations

- The retained Bob review predates the ADK deployment, evidence-state, probe,
  inventory, bilingual UI, and Vertex video-transport work; its architecture
  summary is historical, not a description of the current repository.
- The replacement screenshot proves one current, project-specific Bob review;
  it does not imply that Bob executed the application or reviewed private media.
- The official IBM wording, hackathon registration, IBM track selection, and
  submission-specific participant answers are confirmed.
- Real-video Gemini analysis is not yet evidence; no private media transfer has
  been authorized.
