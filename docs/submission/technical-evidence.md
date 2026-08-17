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
- Vertex AI video request construction for an already-approved `gs://` object,
  including interval metadata and JSON Schema response constraints. Tests use a
  fake client and send no video.
- A fail-closed public demo mode that rejects private GPX, Maps, Gemini/ADK,
  hosted Runtime, and configuration endpoints while retaining deterministic
  synthetic views and a safe health check.
- A Python 3.12 / Gunicorn 26 container that requires public
  mode, runs non-root, uses allowlisted source copies, excludes private formats
  from the build context, and has been built and health-checked locally for
  `linux/amd64`. The 44,497,520-byte image contains no Google SDK and blocks all
  private/Google execution endpoints. No public deployment exists yet.
- A credential-free Cloud Run target model that pins Tokyo, 1 CPU / 512 MiB,
  minimum zero / maximum one instance, concurrency four, a dedicated no-role
  service identity, and separate private-deployment/public-access approval
  gates. It never invokes `gcloud` or a Google API.

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

- The authenticated Devpost overview was fetched on 2026-08-17 and currently
  shows submissions open. It confirms Gemini, Google Cloud Agent Builder, and a
  Partner Entity product or MCP server as core requirements. Registration,
  detailed rules acknowledgment, final Partner-track selection, and exact
  submission obligations are not yet complete.
- Google Cloud Agent Builder compatibility if the current rules distinguish it
  from the deployed Agent Platform Runtime.
- Real GoPro video transfer, Gemini analysis, and story update.
- Actual camera-to-GPS clock correction across source files.
- Final public repository, hosted application, English recording, and complete
  five-to-ten-minute film.
- Cloud Run and Artifact Registry API enablement, registry/service-account
  creation, image push, private verification, and separate public IAM approval.
- Real route/media-derived LLM story prose, final English wording, and human
  language review.
