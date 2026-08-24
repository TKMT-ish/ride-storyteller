# Ride Storyteller

Ride Storyteller turns motorcycle-touring footage and GPS context into a travel story. This repository currently contains local, deterministic building blocks for the agent loop and edit handoff.

```
GPS event -> Story Agent decides video evidence is needed
          -> media search tool -> video analyser -> Story Agent updates decision
```

## Day 1 boundaries

- The core GPS/video pipeline uses synthetic JSON in `tests/fixtures/`.
- The project never calls Box, Garmin Connect, or FFmpeg automatically.
- A separately invoked Google Cloud probe and ADK demo make real Gemini calls only
  with fixed synthetic text and a fixed synthetic event. They cannot read or send
  GPX, route coordinates, video, or Box content.
- `MockMediaSearchTool` and `MockVideoAnalyzer` are explicit replacement points for Box MCP and Gemini in later days.
- Real GoPro media, Garmin logs, OAuth tokens, and API keys must never be committed. `.env` and private media/GPS formats are ignored.
- A hosted synthetic-only Agent Platform Runtime has been validated separately.
  This does not authorize real GPX, route coordinates, or video transfer and
  does not establish Google Cloud Agent Builder compatibility by itself.

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

The local UI also has a **私用GPXのローカル検証** section. It parses a selected GPX in
memory, returns aggregate values only, and neither saves the GPX nor contacts an external
service.

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
registration/form status must be re-verified at final submission. Publication,
hosting, final video, and real-media proof remain separate external gates. The
repository-root AGPL-3.0 license is checked as part of this preflight.

## Safe public demo mode

The default `local` mode is loopback-only. A separate `public_demo` mode can bind
to a hosted port, but disables private GPX input, Google Maps, local ADK/Gemini
execution, hosted Runtime calls, and runtime-configuration endpoints. It leaves
only deterministic synthetic views and the client-only video inventory enabled.

```bash
RIDE_WEB_MODE=public_demo RIDE_WEB_HOST=0.0.0.0 RIDE_WEB_PORT=8080 \
  RIDE_UI_DEFAULT_LANGUAGE=en python -m app.web.server
```

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
