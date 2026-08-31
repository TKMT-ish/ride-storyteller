# Judging alignment

> Working evidence map for the four official five-point criteria. It does not
> invent impact metrics or treat unfinished gates as accomplishments.

## Technological Implementation

**Evidence available now**

- A tested GPS-event to Story Agent to media-evidence to updated-decision loop.
- Google ADK Agent/tool wiring with Gemini 2.5 Flash.
- A verified object-style `AdkApp` Runtime in Tokyo using fixed synthetic input.
- Explicit awaiting, confirmed, and rejected evidence states with attribution.
- A schema-constrained Vertex AI video transport that accepts only an already
  approved `gs://` object and cannot upload local files.
- A private Cloud Run revision whose safe health/demo routes pass and whose five
  private or Google-execution routes fail closed.
- IBM Bob development findings mapped to implemented changes and tests.
- A local real-media E2E that grouped 14 MP4 files into 10 logical recordings,
  analyzed 2,385 windows with GPS／FFmpeg／GPMF／Apple Vision, and produced four
  eight-clip review sets without external transfer or automatic confirmation.
- A public AGPL source repository whose exact link is rendered by the
  authenticated private hosted UI.

**Still required**

- Real source-to-analysis-to-confirmed-edit evidence.
- Public unauthenticated hosted URL verification.
- Precise Google Cloud Agent Builder wording in the final submission.

## Design

**Evidence available now**

- GPS context proposes where to look but never asserts what the camera saw.
- Every visual claim is gated by timestamp resolution and explicit evidence.
- Japanese and English presentation share stable internal identifiers.
- Public mode visibly disables private inputs and billable cloud actions.
- No voice narration is required; the planned film uses visual sequence, map,
  edit rhythm, and existing copyright-free music.
- Real-media storyboard review is recorded separately from technical E2E
  success; the current selector is explicitly marked partial rather than final.

**Still required**

- Human review of final English copy, subtitles, and recording.
- Real footage sequence and final music attribution.
- Final screenshot set at submission resolution.

## Potential Impact

**Evidence available now**

- The target workload is close to one terabyte of motorcycle footage, making
  manual review a concrete bottleneck.
- The current 26.7 GiB development set was reduced from 2,385 analyzed windows
  to 21 evidence-gated windows and 15 distinct extracted review clips.
- The workflow narrows review to explainable GPS-linked intervals and preserves
  human control over visual suitability.
- The same pattern can apply to other location-rich unscripted footage without
  claiming that the current prototype already serves those users.

**Still required**

- Measure review time and the false-positive/replacement rate from user labels;
  do not infer time savings from candidate counts alone.
- Avoid publishing a time-saved percentage until measured.

## Quality of the Idea

**Evidence available now**

- The differentiator is an evidence-seeking story agent, not generic automatic
  video summarization.
- The system treats telemetry as a question generator and video as the evidence
  source, which directly addresses hallucinated visual storytelling.
- The architecture separates deterministic planning, model analysis, and human
  confirmation so every final decision remains inspectable.

**Still required**

- Show the full loop with one real approved clip in the final three-minute demo.
- Keep the film output distinct from the product demonstration.
- Integrate highlight discovery, Story Plan, evidence review, and rendering into
  one product workflow instead of the current manual handoff.
