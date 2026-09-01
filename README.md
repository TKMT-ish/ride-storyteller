# Ride Storyteller

Ride Storyteller turns motorcycle-touring footage and GPS context into an
evidence-based travel story. The repository contains a tested synthetic Agent
loop, a private local GPX/video workflow, fail-closed edit gates, a bilingual
demo UI, and synthetic-only Google ADK / Agent Platform integration.

```
GPS event -> Story Agent decides video evidence is needed
          -> media search tool -> video analyser -> Story Agent updates decision
```

The current implementation baseline and the open system-design questions are
summarized in
[`docs/current-system-handoff-ja.md`](docs/current-system-handoff-ja.md).

## Current boundaries

- The public and cloud demos use fixed synthetic data. They cannot read private
  GPX, route coordinates, video, Box content, or arbitrary user input.
- Private local commands can parse real GPX, inspect video metadata, decode
  video with FFmpeg, read GoPro GPMF, run on-device Apple Vision, and write
  ignored review artifacts. They make no external media call.
- A separately invoked Google Cloud probe and ADK demo make real Gemini calls only
  with fixed synthetic text and a fixed synthetic event. They cannot read or send
  GPX, route coordinates, video, or Box content.
- `MockMediaSearchTool` and `MockVideoAnalyzer` remain explicit test and demo
  boundaries. A Vertex video transport exists only for an already-approved
  `gs://` object and does not upload local files.
- Real GoPro media, Garmin logs, OAuth tokens, and API keys must never be committed. `.env` and private media/GPS formats are ignored.
- A hosted synthetic-only Agent Platform Runtime has been validated separately.
  This does not authorize real GPX, route coordinates, or video transfer and
  does not establish Google Cloud Agent Builder compatibility by itself.
- Visual evidence remains `awaiting_video_evidence` until a human explicitly
  confirms or rejects it. Local candidate generation never auto-confirms a clip.

## Current real-media status

On 2026-08-30, the local v4a research run processed 14 physical MP4 files as
10 logical recordings. It analyzed 2,385 twelve-second windows, retained 202 at
the strict movement/interest gate, retained 21 at the final evidence gate, and
generated four eight-clip review sets. Content hashes reduced the 32 outputs to
15 distinct clips. No media, GPX, coordinate, file name, timestamp, or credential
was sent externally.

The technical E2E passed, but candidate quality is still partial: storyboard
review found several gentle, straight-looking road segments. Eight clearer
turn/merge/intersection/traffic-event examples were prepared for private human
review, but no visual evidence has been confirmed. Highlight discovery now separates
an intentionally strict strong-turn lane from a non-semantic temporal visual-event
lane; this is a candidate gate, not proof that an intersection, vehicle, or scenic
subject is present. The next design must connect that output to Story Plan and
evidence review. A reusable private metric cache avoids re-scanning unchanged source
footage while the two lanes are evaluated on real material.

## Run

Python 3.11 or later is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m app.main
python -m pytest
```

Optionally install Ruff and run `ruff check .`.

If package installation is unavailable, `python -m tests.run_day1_checks` runs the
same core Day 1 acceptance behaviour using only the Python standard library.

## Later replacements

1. Day 2 replaces synthetic events with GPX parsing while preserving the `GpsEvent` contract.
2. Box MCP is optional future media-search infrastructure, not an MVP gate.
3. The Gemini adapter validates structured short-clip analysis and turns
   unavailable or malformed analysis into human review. A concrete Vertex AI
   transport now builds a schema-constrained request for an already-approved
   `gs://` object; it never uploads local video. See
   [`docs/google-video-transport.md`](docs/google-video-transport.md).

No live connector should be enabled before its credentials, permissions, and the exact hackathon environment have been verified.

## Day 2: GPX route normalisation

The parser uses only Python's standard library. It accepts a private Garmin-exported GPX file and writes a local `route.json` containing timestamp, latitude, longitude, elevation, derived distance, and derived speed.

```bash
python -m app.gps.parser /path/to/private.gpx --output /path/to/route.json
```

Do not commit either the GPX file or a route JSON that contains real trip locations or timestamps.

## Day 3: event candidates

`app.gps.extract_events` turns a normalized route into explainable candidates: departure, stop, long ride, elevation change, speed change, direction change, and arrival candidate. Thresholds are deliberately conservative initial values and will only be tuned after reviewing private GPS data.

## Day 4: Story Plan mock

`RuleBasedStoryPlanner` turns a route summary and GPS event candidates into a 5–10 minute draft: a neutral title, chapters, selected event IDs, and short rationale. It makes no visual claims; Gemini-based story planning remains a future replacement after video evidence is available.

## Day 5: Box MCP preparation

The project now has a connection-free Box MCP preflight check. Copy `.env.example` to a local `.env` only after the Box OAuth setup is complete, then run:

```bash
python -m app.mcp.preflight
```

This does **not** authenticate or connect to Box. It never prints secrets. The hosted endpoint, credential requirements, and remaining verification steps are documented in [docs/day5-box-mcp-setup.md](docs/day5-box-mcp-setup.md).

## Day 7: local demo UI

The local UI makes the synthetic Agent flow visible. Its standard Story Plan,
candidate-edit, and GPX-validation controls do not call Gemini. The separately
labelled **ADK合成デモを実行** control sends only a fixed synthetic event to the
local ADK/Gemini runtime; it does not accept or send user input, GPX, video,
coordinates, Box content, or credentials.

The separately labelled **クラウドRuntime合成テストを実行** control calls the
one already-created Tokyo Agent Runtime. It accepts only an empty POST request,
sends the same fixed synthetic event, returns completion metadata only, and
warns that the external call may incur Google Cloud usage charges.

```bash
python -m app.web.server
```

Then open `http://127.0.0.1:8765` and choose **判断デモを実行**.

The local UI has a Japanese/English switch. Japanese remains the default for
development; `?lang=en` selects the English presentation layer without changing
API status identifiers or agent contracts. A future submission environment can
set the non-secret `RIDE_UI_DEFAULT_LANGUAGE=en` value. Translation keys are
validated in both languages so a missing English label fails the test suite.
The deterministic synthetic Story Plan also receives an explicit `ja` or `en`
output language and generates its title, chapter titles, and rationales in that
language. Event IDs, chapter IDs, roles, status values, and other domain
contracts remain unchanged.

An optional Gemini Story copy boundary can rewrite only the fixed synthetic
plan into Japanese or English. It sends sanitized chapter metadata, constrains
the response with JSON Schema, and rejects changed chapter IDs or counts. The
live synthetic English probe succeeded with `gemini-2.5-flash` without printing
or saving generated text. Real route/media-derived prose remains disabled until
separately approved and human-reviewed; see
[`docs/google-story-copy.md`](docs/google-story-copy.md).

The deterministic synthetic Story Agent uses the same language boundary for
its scenario label, evidence-decision reason, final story role, and flow steps.
`/api/demo?...&lang=en` therefore returns an English evidence record instead of
relying on the page to hide Japanese agent text. Its event ID, evidence flag,
asset hint, and decision status stay identical across languages.

The deterministic candidate-plan endpoint follows the same presentation
boundary. It localizes the synthetic story title, notice, and quality-review
reasons from structural duration/evidence fields while leaving every clip,
status, duration, and evidence ID unchanged.

The loopback-only GPX summary endpoint also receives the selected language. It
localizes its in-memory notice, synthetic story title, and review reasons while
returning the same aggregate route/event values and never returning coordinates.
Public demo mode continues to reject this endpoint entirely.

## Day 11: candidate edit planning and quality gate

`app.edit` maps the selected Story Plan events to requested source intervals. This
is deliberately a **candidate plan**, not a rendered edit list: every clip stays
`awaiting_video_evidence` until the real source clip has been retrieved and
reviewed. The quality gate fails closed when either the requested duration is
short of the story target or any candidate lacks video evidence. The local UI's
**候補クリップ計画を見る** button shows this state using synthetic data only.

## Day 12: dense GPS-event consolidation

`consolidate_events` keeps the full output of `extract_events` available for audit,
but reduces nearby `speed_change` and `direction_change` candidates to one
representative per 15-minute window before Story Plan selection. This prevents dense
telemetry from overwhelming the planning stage. The window is an initial policy, not
a tuned travel-specific threshold; compare multiple private GPX logs before changing it.

## Day 13: private video catalog, clock correction, and exports

Create a private catalog from video metadata using
`docs/private-video-catalog.example.json` as the shape. It contains only file names,
recorded start times, durations, and an optional `video_to_gps_offset_s` correction:
add this number to a camera-recorded timestamp to obtain its GPS-clock equivalent.
Do not commit the completed catalog.

After both a private GPX and catalog exist, create editor-friendly candidate files in an
explicit private directory:

```bash
python -m app.video.export /path/to/private.gpx /path/to/private-video-catalog.json --output /path/to/private-output
```

This creates `ride-storyteller-candidates.json` and
`ride-storyteller-candidates.csv`. They identify only timestamp-matched source intervals;
they do not assert that the clip is visually appropriate or ready to render.

## Local source-video inventory

When the real GoPro files become available, begin with a local-only inventory before
creating a timestamp-matching catalog. It scans file names, relative paths, sizes, and
modified times only; it does not open a video, read GPS data, or contact Box, Gemini,
or any other external service.

```bash
python -m app.video.inventory "/path/to/private-videos" \
  --output "/path/to/private-media/ride-storyteller-local-video-inventory.json"
```

Keep both the source videos and generated inventory outside the public repository.
The inventory is not sufficient for GPS matching: duration, recorded start time, and
camera-to-GPS clock correction must be validated locally in the subsequent catalog step.
See [`docs/local-media-inventory.md`](docs/local-media-inventory.md).

For a terminal-free workflow, open
`http://127.0.0.1:8765/local-media-inventory` and select the private video
folder. This isolated page loads no Google Maps or other third-party scripts,
does not send file metadata to the local server, and creates the same private
inventory shape in the browser without reading video contents.

For an individual selected source file, the optional local metadata probe uses FFmpeg's
`ffprobe` to read container headers (duration, start timestamp when timezone-aware,
codec, resolution, frame rate, and audio presence). It requires a separately installed
`ffprobe`; it never uploads or decodes the source file and does not create a catalog
automatically.

After the camera-to-GPS clock offset has been checked locally, the private catalog builder
can probe all MP4/MOV sources while retaining LRV files as inventory-only proxies.
GoPro chapter names are grouped by recording identity; a complete chapter sequence
with the same container start time receives cumulative start-time correction. Missing
or inconsistent chapter sequences fail closed instead of being guessed:

```bash
python -m app.video.local_catalog "/path/to/private-videos" \
  --output "/path/to/private-output/local-video-catalog.json" \
  --clock-offset-s 0 --clock-offset-confirmed
```

The local E2E preparation command connects private GPX parsing, local catalog coverage,
GPS-event selection, timestamp matching, and FFmpeg-generated 720p review clips. It first
keeps one strong timestamp-covered event per available type, then adds other covered
events by importance until the requested duration is reached. It makes no visual claim,
makes no external call, and stops before visual-evidence confirmation or final rendering:

```bash
python -m app.local_pipeline "/path/to/private.gpx" "/path/to/private-videos" \
  --output "/path/to/private-output" \
  --clock-offset-s 0 --clock-offset-confirmed
```

After reviewing every generated clip, update the private `evidence-review.json`
records to `confirmed` or `rejected` with a non-empty `evidence_source`. Rendering
remains blocked until every candidate is timestamp-matched and confirmed. You can
also set `RIDE_PRIVATE_EVIDENCE_REVIEW_DIRECTORY` in the ignored local `.env` to the
private output directory and open `/private-evidence-review` on the loopback-only
server. The page streams only server-owned review clips through opaque review IDs,
writes a single human `confirmed`, `rejected`, or `awaiting_video_evidence` decision,
and never exposes or uploads event IDs, source asset IDs, file names, paths, offsets,
or coordinates. It is disabled in public-demo mode. Evidence decisions are written by
an atomic local replacement, so an interrupted save keeps the previous review file.

To generate a local-only DirectorScript from the confirmed events, rerun the same
private output folder with `--overwrite --director-mode`. This uses the offline
RuleBased Director and does not call Gemini or upload private media:

```bash
python -m app.local_pipeline "/path/to/private.gpx" "/path/to/private-videos" \
  --output "/path/to/private-output" \
  --clock-offset-s 0 --clock-offset-confirmed \
  --overwrite --director-mode
```

```bash
python -m app.local_render "/path/to/private-output"
```

When a private `local-director-script.json` has been created, its story order can
be applied to the silent local render. The script is revalidated against the
matched clips and confirmed-evidence allow-list before FFmpeg starts:

```bash
python -m app.local_render "/path/to/private-output" \
  --director-script "/path/to/private-output/local-director-script.json"
```

The current local render is a silent review film. Copyright-free music selection,
attribution, and final audio mixing remain a separate step.

See [`docs/local-e2e-pipeline.md`](docs/local-e2e-pipeline.md).

## Local highlight-method comparison

Timestamp coverage alone does not make a clip interesting. The local comparison pass
uses an LRV proxy when available and otherwise analyzes MP4/MOV directly at one
frame per second after an early 320-pixel downscale. It combines those metrics
with GPX motion, ranks 12-second moving/non-straight windows by ten methods, and
extracts only selected source intervals as 720p review clips. It does not upload
media and does not auto-confirm visual evidence:

```bash
python -m app.video.highlight_discovery \
  "/path/to/private.gpx" \
  "/path/to/private-videos" \
  "/path/to/private/local-video-catalog.json" \
  --output "/path/to/private-highlight-output" \
  --top-k 3
```

The methods cover GPS curvature, moving speed variation, elevation change, visual
motion, scene variation, sharpness, exposure, color richness, visual complexity, and a
combined cinematic score. All outputs remain comparison candidates for human review.
See [`docs/highlight-selection-experiments.md`](docs/highlight-selection-experiments.md).

The current local research pass adds fail-closed continuous-speed, centered GPS
turn, GoPro GPMF gyro, three-frame Apple Vision road-context/aesthetic, Feature
Print deduplication, and MMR diversity gates. Quality observations cover every
strict candidate in bounded Vision batches; the expensive Feature Print matrix
is calculated only for the union of the top 96 candidates per strategy (at most
384 candidates). GoPro chapter files that share one recording identity are placed
on a cumulative logical timeline before GPS matching. The command defaults to a
six-second survey stride and eight non-overlapping review candidates per strategy
because the stricter experiments could not safely produce ten without weakening
the quality criteria:

```bash
python -m app.video.highlight_research \
  "/path/to/private.gpx" \
  "/path/to/private-videos" \
  "/path/to/private/local-video-catalog.json" \
  --output "/path/to/private-highlight-research"
```

This command is macOS-only because Apple Vision is local platform infrastructure.
It must run with native access to macOS Vision; a restricted process sandbox can
fail to create the required pixel buffers even when the frames are valid. It
makes no network call, keeps all frames and clips in an ignored private directory,
and never confirms evidence automatically. Its `metric-cache/` subdirectory keeps
only derived FFmpeg and GPMF numeric samples. Cache JSON never stores source paths,
file names, recorded timestamps, coordinates, or frames; changed sources receive a
new bounded local-content fingerprint and are analyzed again. Apple Vision and clip
extraction remain local work on each research run. The final accept/reject decision
remains human review.

The local UI also has a **私用GPXのローカル検証** section. It parses a selected GPX in
memory, returns aggregate values only, and neither saves the GPX nor contacts an external
service.

## Private highlight review

After a local highlight-research pass has produced its private review package, set
`RIDE_PRIVATE_HIGHLIGHT_REVIEW_DIRECTORY` in the ignored local `.env` to that package
directory. Then open `/private-highlight-review` on the loopback-only local server. The
page streams only the selected local thumbnails and clips through opaque candidate IDs,
and writes fixed-vocabulary `approved`, `rejected`, or `awaiting` decisions back to the
package's `highlight-review.json`. It exposes no source paths, filenames, timestamps,
coordinates, frames, or free-form notes, and is unavailable in public-demo mode. Each
save atomically replaces the review file; a failed save leaves the previous decisions
intact rather than writing partial JSON.

## Private DirectorScript preview

Once the local Director pipeline has written a private `local-director-script.json`, set
`RIDE_PRIVATE_DIRECTOR_SCRIPT_PATH` in the ignored local `.env` to that file and open
`/private-director-preview` on the loopback-only local server. The page is read-only and
returns only the story roles, clip counts, transitions, and optional overlay text. Event IDs,
asset IDs, source intervals, file names, paths, and coordinates remain in the private Editor
artifact and are never returned by this browser endpoint. The page and its API are disabled in
public-demo mode.

## Local Google Maps route display

The local UI can draw a selected GPX track as a Google Maps polyline. This is
optional and uses only Maps JavaScript API; it does not use Directions, Routes,
or Places APIs.

1. Rotate any Maps key that was exposed in a screenshot, then retain the API
   restriction to **Maps JavaScript API** and the local referrer restriction
   `http://127.0.0.1:8765/*`.
2. In the ignored local `.env` file, set `GOOGLE_MAPS_API_KEY` to the replacement
   key. Never add it to this repository or `.env.example`.
3. Start `python -m app.web.server`, open `http://127.0.0.1:8765/`, select a GPX,
   and choose **GPXを検証**.

The GPX file remains in the browser and local server memory. When the map is
drawn, the browser sends the displayed route coordinates to Google Maps; use this
feature only for GPS data you are comfortable sharing with Google for map display.

## Current hackathon runtime direction

The runtime target is Gemini plus Google ADK / Google Cloud Agent Builder.
`app.agent_runtime` now includes a minimal Vertex AI/Gemini connection probe that
uses local Application Default Credentials (ADC) and a fixed synthetic prompt; it
does not read GPX or media. It also produces a credential-free structured handoff
for the later ADK/Agent Builder adapter. The project now also contains a local
Google ADK agent whose only tool returns a fixed synthetic event; it cannot access
or transfer GPX, route coordinates, video, Box content, or credentials. Box remains
optional. See [`docs/google-adk-runtime.md`](docs/google-adk-runtime.md).

`GoogleCloudRuntimeSettings` reads only the non-secret local configuration needed
for the local Gemini/ADK runtime: project ID, location, `GOOGLE_GENAI_USE_VERTEXAI=true`,
and model name. Its `configuration_present` state means only that those values
exist; it is not an authentication or Gemini-call success. The synthetic probe is
the separate live check for basic Gemini reachability. See
[`docs/google-cloud-runtime-setup.md`](docs/google-cloud-runtime-setup.md).

The local ADK app is also wrapped as the official Agent Platform `AdkApp` type.
One approved synthetic-only Runtime is now deployed through the object-style
`AdkApp` path in `asia-northeast1` (Tokyo), with 4 CPU / 4 GiB, minimum zero and
maximum one instance. The dedicated Tokyo staging bucket and Runtime resource
name are configured only in the ignored local environment. The local Gemini
inference endpoint remains `global` and must not be reused as the Agent Runtime
location. Runtime creation uses `agentplatform.Client`; verification temporarily
uses the legacy-compatible client because the pinned new-client streaming path
does not reliably return the final event. See
[`docs/agent-platform-deployment-preflight.md`](docs/agent-platform-deployment-preflight.md).

The authenticated Devpost workflow was audited on 2026-08-17. The five Partner
tracks are IBM, Grafana, Parallel, ClickHouse, and Replit; Box is not a track.
The IBM-specific rule requires demonstrable IBM Bob use during development and
describes Confluent as optional. Ride Storyteller therefore confirms IBM as the
submission track, backed by a retained Bob review and implemented
finding-to-test evidence. Registration and the explicit rules/eligibility
agreements were completed and verified live on 2026-08-24. A sanitized Bob
screenshot with a Ride Storyteller-specific render-gate finding was captured,
checked against the current source, and retained on 2026-08-24. The legal
terms and Devpost dates endpoint agree on the deadline: 2026-09-10 06:00 JST.
Final validation should finish at least 24 hours earlier. See
[`docs/submission/official-rules-audit.md`](docs/submission/official-rules-audit.md)
and [`docs/ibm-mcp-integration-gate.md`](docs/ibm-mcp-integration-gate.md).

After timestamp matching and explicit visual-evidence confirmation, `app.edit` can
produce an inspectable FFmpeg command plan. It does not execute FFmpeg automatically;
the output remains blocked while a source is missing or a clip's visual evidence is not
confirmed.

## Offline submission preparation

English write-up, three-minute demo script, recording runbook, screenshot plan,
five synthetic-only English UI captures, a sanitized IBM Bob evidence image and
capture checklist, Devpost registration worksheet, official-rules audit, Devpost form
draft, and technical/test evidence are kept locally. They are not submitted
automatically. Run the safe local preflight:

```bash
python -m app.submission
```

This checks offline artifacts, a recognizable root OSI license, and private-file
protections only. It never treats local state as live Devpost proof, so current
registration/form status must be re-verified at final submission. The public
source repository now exists, but the public application, final video, and
human-approved real-media proof remain separate external gates. The
repository-root AGPL-3.0 license is checked as part of this preflight.

## Safe public demo mode

The default `local` mode is loopback-only. A separate `public_demo` mode can bind
to a hosted port, but disables private GPX input, Google Maps, local ADK/Gemini
execution, hosted Runtime calls, and runtime-configuration endpoints. It leaves
only deterministic synthetic views and the client-only video inventory enabled.
The hosted page renders a bilingual AGPL Source link only when
`RIDE_SOURCE_REPOSITORY_URL` is a validated HTTPS GitHub, GitLab, or Bitbucket
repository-root URL. With no URL, the page shows a not-public-ready warning and
the Cloud Run plan refuses to generate unauthenticated-public-access arguments.

```bash
RIDE_WEB_MODE=public_demo RIDE_WEB_HOST=0.0.0.0 RIDE_WEB_PORT=8080 \
  RIDE_UI_DEFAULT_LANGUAGE=en \
  RIDE_SOURCE_REPOSITORY_URL=https://github.com/TKMT-ish/ride-storyteller \
  python -m app.web.server
```

The reviewed source repository is the exact root URL shown above. The hosted
Cloud Run service remains private even though its authenticated UI exposes the
validated source link.

For a production-style local container check:

```bash
docker build --platform linux/amd64 \
  --tag ride-storyteller:public-demo-cloud-run .
docker run --rm --publish 127.0.0.1:8767:8080 \
  ride-storyteller:public-demo-cloud-run
```

The image uses Gunicorn 26, runs as a non-root user, copies only the application
allowlist, and refuses to start outside `public_demo` mode. `/health` exposes
safe mode/capability flags only; `/healthz` remains a local compatibility alias
but is not used on Cloud Run because paths ending in `z` may be reserved. The
public mode accepts body-free GET requests only, applies a fixed-window limit of
60 non-health requests per minute in each of at most two worker processes, and
returns 429 with `Retry-After` after the limit. This is a dependency-free
baseline guard, not a distributed rate limiter or DDoS service. The
image has been built and health-checked locally for Cloud Run's `linux/amd64`
target. The current private Tokyo Cloud Run revision is Ready, its HTTP startup
probe and authenticated `/health` request both pass, and unauthenticated access
remains disabled. A
credential-free, non-mutating Cloud Run plan is available with
`python -m app.web.cloud_run`. See
[`docs/public-demo-hosting.md`](docs/public-demo-hosting.md) and
[`docs/cloud-run-public-demo.md`](docs/cloud-run-public-demo.md).

## License

Ride Storyteller source code and original text documentation are available under
the [GNU Affero General Public License version 3 only](LICENSE) (`AGPL-3.0-only`),
except where a file or directory explicitly states otherwise. Commercial use is
permitted under that license, while modified network services must offer their
corresponding source as required by AGPL section 13.

Third-party dependencies retain their own licenses. Private GPX/video, music,
credentials, and other excluded media are not licensed by this repository. The
Ride Storyteller name and any logo are not granted for use in a way that implies
endorsement. See [`docs/licensing.md`](docs/licensing.md) for scope and the
publication checklist.
