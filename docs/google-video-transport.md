# Vertex AI Gemini video transport boundary

`VertexAIGeminiVideoTransport` is the concrete SDK boundary for a video object
that has already been approved and placed in Google Cloud Storage by an
authorized process. It is intentionally not an uploader.

## Safety properties

- Accepts only a complete `gs://bucket/object` URI.
- Rejects local paths, Box URIs, HTTP URLs, non-video MIME types, empty prompts,
  and invalid time intervals before any client call.
- Sends requested start/end offsets as video metadata.
- Requests `application/json` with a schema that requires all analysis fields,
  constrains scores to 0–1, and disallows extra keys.
- Passes the mapping to `GeminiVideoAnalyzer`, which independently validates the
  stable project contract.
- Converts provider failures to non-sensitive project errors.

## Deliberately absent

- local file reading or upload;
- GCS bucket selection;
- object creation, deletion, signed URLs, or lifecycle changes;
- automatic use of the Agent Platform staging bucket;
- authorization to transfer real GPX or video.

The existing Agent Runtime staging bucket is for deployment artifacts and must
not be reused for GoPro media. A separate storage, privacy, retention, cost, and
approval decision is required before the first real-video call.
