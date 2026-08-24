# Three-minute English demo script

> Recording draft. Segments marked **REAL MEDIA GATE** must not be recorded as
> complete until the private footage is accessible and its use is approved.
> A timing-matched draft is available as `demo-subtitles-en.srt`; align and
> human-review it again after the final recording is edited.

## 0:00–0:20 — Problem

“A motorcycle trip can produce hundreds of gigabytes of footage. The memorable
story is buried across GPS timestamps and long video files. Ride Storyteller uses
an evidence-seeking agent to find the moments worth reviewing.”

Show the English home screen and the pipeline summary.

## 0:20–0:50 — Explainable GPS events

“The system first parses the route locally and extracts explainable events:
departure, stops, elevation and direction changes, and arrival. GPS proposes
where to look. It never claims what the camera saw.”

Run the synthetic Story Plan view. Keep synthetic labeling visible.

## 0:50–1:25 — Agentic evidence loop

“For a high-interest event, the Story Agent decides that video evidence is
required. It calls the media-search boundary, requests analysis of the matching
interval, and updates the decision. Missing media, malformed analysis, or an
unavailable model fails closed to human review.”

Run the accepted scenario, then briefly show the missing-asset scenario.

## 1:25–1:50 — Evidence gate and edit plan

“A GPS match is not enough. Every candidate starts as awaiting evidence. It can
be confirmed or rejected with an attributed source. Only confirmed candidates
can enter the inspectable FFmpeg plan.”

Show the candidate plan and the blocked state.

## 1:50–2:15 — Hosted Google agent

“The same private-data boundary is deployed as a synthetic-only Google ADK
agent on Google Cloud Agent Platform in Tokyo, using Gemini 2.5 Flash. This
button sends a fixed synthetic event, confirms the tool call and final response,
and returns no model text or private data.”

Run the hosted synthetic test once. Keep the usage-cost notice visible.

## 2:15–2:35 — IBM Bob development evidence

“IBM Bob reviewed the architecture and identified missing ADK wiring, missing
evidence transitions, and boundary-test gaps. We implemented those findings and
retained the before-and-after evidence.”

Show `06-ibm-bob-video-evidence-gate.png` and the evidence table. The validated
image does not show an email address, API key, Runtime name, bucket name, or
private path.

## 2:35–2:55 — Real output

**REAL MEDIA GATE**

“With the approved source files available, the agent now links the selected GPS
event to this exact interval, Gemini evaluates only the clip, and the human
reviewer confirms the visual evidence. The resulting short sequence uses no
voice narration and only copyright-free music.”

Show one approved source-to-final sequence and its evidence status. Until this
exists, use a clearly labeled placeholder and do not imply completion.

## 2:55–3:00 — Close

“Ride Storyteller turns telemetry into questions, video into evidence, and
evidence into a travel story.”
