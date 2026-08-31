# Technical evidence index

## Proven locally

- Validated GPS, event, story, evidence, media, and render-plan contracts.
- Deterministic event consolidation with stable identifiers.
- Explicit awaiting/confirmed/rejected evidence transitions.
- Fail-closed agent outcomes for missing assets, unavailable Gemini, malformed
  structured output, unknown event types, and unconfirmed clips.
- Japanese/English UI key parity, language-preserving navigation, and a
  deterministic bilingual Story Plan API whose structural identifiers remain
  equal across languages.
- A deterministic bilingual Story Agent API covering accepted, rejected,
  missing-media, and unavailable-analysis outcomes while preserving event IDs,
  evidence flags, asset hints, and decision statuses.
- A bilingual candidate-plan presentation that derives localized review reasons
  from structural duration and evidence fields without changing clip data or
  readiness state.
- A bilingual loopback-only GPX aggregate response with equal route/event
  structure and no coordinates; public demo mode still rejects GPX input.
- A synthetic-only Gemini Story copy generator and Vertex transport with
  explicit language, JSON Schema output, exact chapter-ID/order validation, no
  event IDs/coordinates/media references, and safe provider errors.
- Local-only GPX aggregate validation, source inventory, and `ffprobe` metadata
  extraction boundaries.
- A local-only GPX-to-review-clip preparation pipeline. It requires explicit
  camera/GPS clock confirmation, excludes LRV duplicate proxies from the source
  catalog, selects timestamp-covered GPS events with type diversity before
  filling the requested duration, preserves repeated event types in route order,
  and transcodes matched intervals to 720p review clips before stopping at human
  visual-evidence review.
- A fail-closed local evidence-review contract and FFmpeg draft renderer. The
  renderer starts only when every candidate is timestamp-matched and explicitly
  confirmed, rejects incomplete manifests, and produces a silent local film
  without sending files externally.
- A local ten-method highlight comparison stage that analyzes LRV proxies when
  present and otherwise analyzes MP4/MOV after an early reduced-resolution
  downscale. It combines GPS movement with FFmpeg motion, scene, blur, exposure,
  saturation, and entropy metrics, applies moving/non-straight gates, and
  extracts only ranked source intervals for human review.
- A local catalog v2 that recognizes GoPro chapter/recording identifiers,
  applies cumulative duration correction only to complete same-start chapter
  sequences, and rejects missing, duplicate, or inconsistent sequences without
  guessing.
- A second-generation local highlight research stage that fails closed on
  insufficient continuous speed, centered GPS turning, centered GoPro GPMF
  gyro motion, three-frame Apple Vision road context, utility frames, temporal
  overlap, or Feature Print duplicates. The real-media v4a experiment processed
  all 14 physical MP4 files as 10 logical recordings, analyzed 2,385 windows,
  retained 202 strict and complete-evidence windows, retained 21 after the final
  quality gate, and produced four eight-clip comparison sets with zero hard-gate
  violations. Content hashes reduced the 32 outputs to 15 distinct clips. This
  is local ranking evidence, not automatic visual confirmation.
- Vertex AI video request construction for an already-approved `gs://` object,
  including interval metadata and JSON Schema response constraints. Tests use a
  fake client and send no video.
- A fail-closed public demo mode that rejects private GPX, Maps, Gemini/ADK,
  hosted Runtime, and configuration endpoints while retaining deterministic
  synthetic views and a safe health check.
- A dependency-free public request guard that rejects non-GET methods and any
  request body, limits each of at most two workers to 60 non-health requests per
  minute, returns 429 with `Retry-After`, and leaves local mode unchanged. This
  is a process-local baseline rather than a distributed DDoS control.
- A Python 3.12 / Gunicorn 26 container that requires public
  mode, runs non-root, uses allowlisted source copies, excludes private formats
  from the build context, and has been built and health-checked locally for
  `linux/amd64`. The current 44,271,065-byte image contains no Google SDK and
  blocks all private/Google execution endpoints.
- A credential-free Cloud Run target model that pins Tokyo, 1 CPU / 512 MiB,
  minimum zero / maximum one instance, concurrency four, a dedicated no-role
  service identity, and separate private-deployment/public-access approval
  gates. It never invokes `gcloud` or a Google API.
- A private Tokyo Cloud Run revision that became Ready with 100% traffic under
  the reviewed limits. Authenticated verification returned 200 for the English
  synthetic demo, the exact GitHub AGPL Source link, and 403 for all five
  private/Google execution routes. There is no unauthenticated IAM binding.
- A canonical `/health` endpoint selected after confirming Google's warning
  about reserved paths ending in `z`. The current revision's HTTP startup probe,
  authenticated hosted request, security headers, and unauthenticated 403 are
  verified. `/healthz` remains only a local compatibility alias.
- A read-only scaling audit confirmed that the service-level maximum is one.
  Although the revision reports 20, Google applies the lower value, so the
  effective limit is one. Minimum instances remains zero. Billing currency JPY,
  the enabled Budget API, and one project-only monthly JPY 1,000 budget with
  actual 50/80/100%, forecast 100%, role-based email, and no Pub/Sub were
  created and re-read on 2026-08-27. The budget is not a hard cap.

## Proven with synthetic Google calls

- Vertex AI text connection probe: project `ride-storyteller`, Gemini inference
  endpoint `global`, model `gemini-2.5-flash`, non-empty response received.
- Local Google ADK run: fixed synthetic event tool called and final response
  received; model response text not retained.
- Gemini Story copy: fixed synthetic three-chapter plan rewritten to English by
  `gemini-2.5-flash`; structured response received, generated text not retained,
  and `private_data_used=false`.
- Hosted Google Cloud Agent Platform Runtime: object-style `AdkApp`, Tokyo
  (`asia-northeast1`), 4 CPU / 4 GiB, minimum zero and maximum one instance.
  Hosted verification observed the required synthetic tool call and final
  response and reported `private_data_used=false`.

The Runtime resource name, staging-bucket name, credentials, tokens, ADC files,
and model response text are intentionally excluded.

## Not yet proven

- The authenticated Devpost relationship confirms registration, and the
  submission requirements, judging criteria, and dates were refreshed on
  2026-08-24. No Devpost project has been created or sent. The IBM track is
  confirmed; the sanitized IBM Bob screenshot and its current-source
  cross-check are complete.
- Google Cloud Agent Builder compatibility if the current rules distinguish it
  from the deployed Agent Platform Runtime.
- Real GoPro video transfer, Gemini analysis, and story update.
- A public unauthenticated hosted application, English recording, and complete
  five-to-ten-minute film. The AGPL public source repository exists and its exact
  root link has been verified through the authenticated private hosted UI.
- separate public IAM approval, public URL verification, and distributed abuse
  controls. The process-local request guard, private revision, hosted health
  endpoint, and budget alerts are verified but are not public evidence.
- Real route/media-derived LLM story prose, final English wording, and human
  language review.
- User accept/reject review of the eight manually curated v4a examples and a
  v4b rerun that separates strong-turn and visual-event interest. Generic Apple
  aesthetic score is deliberately not treated as the final objective because
  it conflicts with the user's preference against straight road clips.
