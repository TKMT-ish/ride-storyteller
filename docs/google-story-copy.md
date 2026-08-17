# Gemini story-copy boundary

Ride Storyteller can ask Gemini to rewrite a deterministic synthetic Story Plan
into Japanese or English presentation copy without allowing the model to change
the selected story structure.

## Current scope

- Input must be explicitly marked `synthetic_input=true`.
- The generator accepts a validated `StoryPlan` and an explicit `ja|en` output
  language.
- The outbound payload contains only the synthetic source title, chapter IDs,
  narrative roles, source titles/rationales, target duration, and chapter
  durations.
- Event IDs, coordinates, asset names, video URIs, local paths, GPX data,
  credentials, and video-analysis text are not included.
- Real route-derived or media-derived input is rejected before the transport is
  called. Enabling it requires a separate privacy decision and explicit approval.

## Structured output

Vertex AI Gemini is constrained to JSON containing:

- one non-empty story title;
- the same number and order of chapters as the source plan;
- the exact original `chapter_id` for every chapter;
- one non-empty title and selection rationale per chapter;
- no additional top-level or chapter fields.

The local generator validates the response again. Missing chapters, reordered or
changed IDs, empty text, extra fields, invalid JSON, and provider failures all
fail closed as `GeminiStoryCopyError`. Provider exception details and generated
copy are not printed by the synthetic verification command.

## Synthetic external verification

Run only when a small Google Cloud charge is acceptable:

```bash
python -m app.story_copy_probe
```

The command uses the fixed synthetic demo Story Plan, requests English copy from
the configured Gemini model, and prints only model name, language, chapter
count, response-received status, `synthetic_input=true`, and
`private_data_used=false`.

On 2026-08-17, the existing Vertex AI configuration and `gemini-2.5-flash`
returned a valid three-chapter English structured response. Generated text was
not displayed, logged, or saved.

## Remaining gate

This proves the model/Schema/language boundary only for fixed synthetic input.
Real Story Agent prose, final English wording, subtitles aligned to the recorded
video, and human language review remain incomplete until the final approved
media workflow exists.
