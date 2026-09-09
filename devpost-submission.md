# Ride Storyteller

> Devpost working draft only. The participant is registered for Agentic Cinema,
> but no project has been sent to Devpost. `PENDING` values require participant
> input, public verification, or the real-media gate.

## One-line Summary

Turn motorcycle telemetry into questions, video into evidence, and evidence into
an explainable travel story.

## Problem

A motorcycle trip can produce hundreds of gigabytes of footage. The memorable
story is buried across long video files, camera timestamps, and a separate GPS
record. Manually finding the useful moments is slow, while treating GPS events as
visual facts would invent evidence that the camera may never have captured.

## Solution

Ride Storyteller converts a GPS route into explainable candidate events. A Story
Agent decides when route context is insufficient and requests video evidence. A
media-search boundary resolves the relevant source interval, Gemini analyzes only
that interval, and the Story Agent accepts, rejects, or escalates the candidate.
The edit remains blocked until every selected clip is timestamp-matched and its
visual evidence is explicitly confirmed with an attributed source.

The track then gives the film its shape: a day is cut into legs, halt to halt,
and every leg is a chapter titled with where it went from and where it went to.
Moments the track proves — setting off, each stop's arrival and re-departure,
joining and leaving a highway, riding off a ferry, arriving — are always shown,
and the model's own answers choose which neighbouring window actually shows the
moment. The turns of the day are said in the lower third with the local time.

The output is a three-to-seven-minute film per riding day with no voice
narration and existing copyright-free music. Twelve consecutive days of one
tour have been cut this way. The public three-minute hackathon video
demonstrates the functioning workflow rather than substituting a cinematic
trailer for the product demo.

## Why This Matters

Motorcycle riders and travel creators often have far more footage than editing
time. Ride Storyteller reduces the search space while keeping the human in control
of the final visual claim. GPS says where to look; the camera evidence determines
what can honestly enter the story.

## How We Used AI

- Gemini 2.5 Flash watches every candidate window of a real ride's own footage
  (small local proxies, never the 4K source) and answers a fixed schema: road,
  scenery, interest, story relevance, how much of the rider is in frame, whether
  the bike moved, what the road is doing, how photogenic the frame is and of
  what, and what kind of place the bike is standing at. Across twelve riding
  days that is 4,039 stored judgements for about ¥764 in total — some windows
  were bought a second time as the questions asked of the model grew.
- A Google ADK agent receives one fixed synthetic event, invokes a typed evidence
  tool, and produces a structured final response with Gemini 2.5 Flash.
- A synthetic-only Google Cloud Agent Platform Runtime in Tokyo verifies the
  hosted ADK tool/final-response loop without accepting GPX, coordinates, video,
  Box data, credentials, or arbitrary prompts.
- A Vertex AI Gemini video transport prepares schema-constrained analysis for an
  already-approved `gs://` clip. It does not upload local media.
- The Story Agent treats malformed output, missing media, model unavailability,
  and rejected visual evidence as human-review states instead of inventing a
  successful edit.
- An optional Gemini Story-copy boundary rewrites only fixed synthetic chapter
  copy while preserving chapter IDs, order, and count.

## How We Built It With AI Assistants

Two coding assistants were used, in two phases. Until 2026-09-02 Codex was the
primary implementation partner: it turned the product constraints into frozen
data contracts, deterministic GPS and story planning, explicit evidence-state
transitions, Google ADK and Agent Platform adapters, the bilingual
local/public-safe UI, Cloud Run deployment safeguards, tests, and submission
documentation. From 2026-09-02 Claude Code took over core implementation,
review, and the design record, with Codex handling small scoped tasks; the
story structure, the judged-film pipeline, the reference layer, and the film's
own rules were built in that phase. Both ran regression and secret/private-media
checks and kept the Japanese design, decision, history, and test records
synchronized with the repository.

IBM Bob was used separately during development to review the earlier codebase.
Its findings about missing ADK wiring, evidence transitions, video transport, and
boundary tests were then implemented and mapped to focused regression tests.

## Key Features

- Explainable GPS event extraction and stable story identifiers.
- Agentic evidence loop: decide, search, analyze, update, or escalate.
- Explicit `awaiting`, `confirmed`, and `rejected` evidence states with source
  attribution.
- Half-open source intervals and camera/GPS clock correction, read from the
  cameras' own GPS where present so that no one is asked at all.
- A day cut into legs, halt to halt, each a chapter card titled from → to, with
  "Day N" on a multi-day trip detected from sibling packages.
- Moments the track proves are always shown, and the model's answers pick the
  window that shows them.
- Lower thirds with the local time for towns, scenic routes, named roads,
  passes, highways, ferries, and each stop by what kind of place it was.
- An opening of four one-second highlights chosen by a photogenic score, of
  distinct subjects, spread across the day.
- Offline map references (touring routes, highways, ferry lines, towns, passes)
  fetched once per country from OpenStreetMap.
- Fail-closed privacy rules in the cut itself: no window that could identify a
  private home, and no window where the rider fills the frame.
- Inspectable multi-clip FFmpeg planning, and a single normalised render pass
  that leaves no half-written film.
- Japanese/English UI with invariant status and domain contracts.
- Synthetic-only Google cloud path separated from private local media workflows.
- Public-demo mode that removes cloud, GPX, Maps, and private-media controls.
- Root-license, secret, ignored-file, and private-media submission preflight.

## Architecture

```text
private/local route or synthetic event
  -> GPS parser and explainable event extraction
  -> Story Planner
  -> Story Agent decides whether evidence is needed
  -> media-search tool boundary
  -> Gemini video-analysis boundary
  -> attributed evidence decision
  -> candidate edit quality gate
  -> inspectable FFmpeg render plan
```

Google ADK exposes the safe synthetic decision loop as an agent/tool workflow.
The deployed Agent Platform Runtime accepts only a fixed non-private event. The
public Cloud Run image is a separate lean web demonstration and contains no
Google SDK or credentials. IBM Bob is evidenced as a development-process tool,
not falsely presented as a runtime integration.

## Testing Instructions

**Two ways in.** The hosted console (<https://ride-storyteller-public-demo-q53n7masba-an.a.run.app>,
judge credential in the form's Testing instructions field) shows the agent's
decision flow on synthetic data in a browser, in Japanese or English. The
product itself runs on your own machine:

**Cut a film from a real ride, on your own machine.** One day of the tour is
published as a portable package (<https://github.com/TKMT-ish/ride-storyteller/releases/tag/day-7-package>):
one small clip per window the film uses, the judgement Gemini returned for
them, the track, and the music. Its number plates are blurred and every clip
in which a face appeared was removed, both by this repository.

```bash
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -e '.[dev]'
# unpack ride-storyteller-day-7.zip from the release under private-media/portable/ first
python -m app.portable_package private-media/portable/day-7 --install
python -m app.private_journey_film private-media/portable/day-7 \
  --music wandering --music-directory private-media/portable/day-7/music
```

The package is 1.61 GiB and carries 53 clips; the film it produces runs six
minutes and eight seconds, with subtitles and music. Read at every frame, it
shows no legible number plate and no face.

That is the product, not a demo of it: it reads the track, cuts the day into
legs, places the moments the track proves, lays the lower thirds, draws the
cards, cuts the film, writes the subtitles and mixes the music. `ffmpeg` and
`ffprobe` must be on the path; on Linux the cards are drawn by headless
`chromium`.

Python 3.11 or later is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
ruff check .
python -m tests.run_day1_checks
python -m app.submission
```

Start the credential-free public-safe demonstration:

```bash
RIDE_WEB_MODE=public_demo RIDE_UI_DEFAULT_LANGUAGE=en \
  python -m app.web.server
```

Open `http://127.0.0.1:8765/?lang=en`, run the synthetic decision scenarios,
and inspect the candidate-plan evidence gate. Public mode intentionally rejects
private GPX and Google execution endpoints. The selected AGPL-3.0 license is detected
at the repository root, so `python -m app.submission` now passes every offline
preparation check while preserving the separate external gates.

## Public Demo Link

<https://ride-storyteller-public-demo-q53n7masba-an.a.run.app> — the hosted, credential-free
synthetic console: a judge can run the decision scenarios, view the Story Plan
and the candidate clip plan, and read the AGPL source link. Every page except
`/health` asks for the judge's HTTP Basic credential, which is shared only
through the submission form's Testing instructions field. Real footage, GPS,
Gemini calls and every private route are disabled there (403); nothing on that
service can spend money.

## Public Repository Link

<https://github.com/TKMT-ish/ride-storyteller> — `main` is at `548c2b8`
(2026-09-09): the current tree as one commit on top of the 49 commits that were
already public. It carries no place name from the rider's route; the private
development history stays in the private mirror. The owner made the
repository **public** on 2026-09-09 and published the judge package
(`ride-storyteller-day-7.zip`, 1,730,095,484 bytes) as release `day-7-package`:
<https://github.com/TKMT-ish/ride-storyteller/releases/tag/day-7-package> (SHA-256 `d6dedf409fe7c1ea307ba051e8004b5ee6019b9216236f2a45d2e4cde5dc5e1d`).

## Demo Video

`PENDING` — publish a maximum three-minute YouTube or Vimeo demonstration in
English or with complete English subtitles. **The demo is assembled by the
repository**, not recorded by hand, from the real day-7 film (English cut), the
day's own judged windows and two screenshots of the local console:

```bash
python -m app.submission.demo_scenario_v2 private-media/work/day-7-en-v1 \
  --inputs private-media/work/demo-v2/inputs.json \
  --film private-media/work/day-7-en-v1/ride-storyteller-story-film-scored.mp4 \
  --cold-open-s 163 --result-start-s 303 \
  --console-copies-png private-media/work/demo-v2/console-copies.png \
  --console-cost-png private-media/work/demo-v2/console-cost.png --overwrite
```

It runs 2:57 in ten segments -- the problem first (108 GB and 4 h 43 min of
footage that nearly all looks the same), then the local copies, the spend gate,
the model's own judgements beside the windows it judged, and the finished film
at 80 % in a frame so it can be told apart from raw footage -- with subtitles
written from the same timeline. Every figure on screen is cross-checked against
what the package's judgement bought, and every frame is read for faces and
number plates on the owner's machine before the file is kept. See
[`docs/submission/demo-script-en.md`](docs/submission/demo-script-en.md).

## Screenshot Shot List

Captured local synthetic-only candidates:

1. [English home screen](docs/submission/assets/01-home-en-public-safe.jpg) with
   synthetic-data and public-safe-mode labels.
2. [Accepted evidence-decision flow](docs/submission/assets/02-agent-accepted-en.jpg),
   including the tool-call step.
3. [Missing-asset flow](docs/submission/assets/03-agent-missing-asset-en.jpg)
   showing fail-closed escalation.
4. [Candidate plan blocked by unresolved evidence](docs/submission/assets/04-candidate-evidence-blocked-en.jpg).
5. [Synthetic Story Plan](docs/submission/assets/05-story-plan-synthetic-en.jpg).

7. [Local console with one real day complete](docs/submission/assets/07-console-stages-en.png)
   — windows planned, megabytes to send, the yen figure against its ceiling,
   copies made, judgement bought, story planned, film cut, music added. Cropped
   above the chapter titles, which name the towns the ride went through.

Captured partner-development evidence:

6. [IBM Bob review of the video-evidence gate](docs/submission/assets/06-ibm-bob-video-evidence-gate.png),
   showing the product identity, Ride Storyteller context, and a current
   project-specific finding without account data or private paths.

Still required as distinct evidence:

8. Synthetic-only hosted ADK result with `private_data_used=false` and no model
   response text.
9. Architecture and automated-test evidence.

## Submission Readiness Notes

- Devpost authentication and the Agentic Cinema `registered` relationship were
  verified live on 2026-08-24. The project itself has not been sent to Devpost.
- The official submission requirements, judging criteria, and dates were
  rechecked on 2026-08-24 and returned complete data.
- The official dates endpoint and legal rules now agree on
  **2026-09-09 21:00 UTC / 2026-09-10 06:00 JST**. The earlier two-day
  discrepancy is resolved; final validation should finish at least 24 hours
  before the official deadline.
- The four official judging criteria are Technological Implementation, Design,
  Potential Impact, and Quality of the Idea.
- Official deliverables require a hosted-project URL, a public open-source
  repository with a complete visible OSI license, and a public YouTube or Vimeo
  demo of no more than three minutes in English or with English subtitles.
- Partner track: `IBM`; confirmed by the participant on 2026-08-24.
- IBM Bob review transcript, finding-to-fix mapping, and a newly captured
  sanitized project-specific screenshot are present. Its rendered-gate finding
  was checked against the current source and focused test.
- Google Cloud synthetic agent use is verified. Real-media cloud use is not.
- The 2026-09-07 regression run passed 2,246 tests and Ruff check and format.
  All offline preparation checks, including the AGPL-3.0 license and IBM Bob
  evidence image, pass.
- Devpost registration and the explicit rules/eligibility agreements are
  complete and were verified live. The registration identifier is intentionally
  not stored in this repository.
- No Devpost project entry has been created or sent from this draft.

## Known Limitations

- Real footage reaches Gemini only as small local proxies (one frame a second,
  480 lines, no audio). The 4K source never leaves the rider's machine, and the
  hosted agent has still only received synthetic events.
- The public Cloud Run service, public source repository, and public video do not
  yet exist.
- The demo video is assembled locally but has not been reviewed frame by frame
  for identifiable faces and number plates, which is a precondition of
  publishing it.
- Place names come from a Google Geocoding request per rounded coordinate; a
  film cut with that service disabled keeps the titles the track alone allows.
- Stop kinds and ferry crossings are read partly from the model's words about
  older judgements; windows bought before those questions existed answer
  "unknown" and fall back to word matching.
- Box is optional future media infrastructure and is not a valid contest track.

## TODO Official Form Fields

### Project identity

- **Project name:** Ride Storyteller
- **Tagline:** Turn motorcycle telemetry into questions, video into evidence,
  and evidence into a travel story.
- **Private participant fields:** confirmed on 2026-08-24. Exact official values
  are stored only in the ignored local `.devpost-submission-answers.json` file
  and must not be committed or copied to Notion.
- **Partner track:** `IBM` — confirmed
- **Team size:** one — confirmed
- **First time using IBM tools:** confirmed
- **Other-track first-use fields:** confirmed using the exact official `N/A`
  choices
- **Optional IBM contact sharing:** declined

### Links and assets

- **Open-source repository URL:** <https://github.com/TKMT-ish/ride-storyteller>
  — public, at the current tree (2026-09-09)
- **Judge package (GitHub Release):** <https://github.com/TKMT-ish/ride-storyteller/releases/tag/day-7-package>
  — `ride-storyteller-day-7.zip`, SHA-256 `d6dedf409fe7c1ea307ba051e8004b5ee6019b9216236f2a45d2e4cde5dc5e1d`; the archive's `README.txt`
  says how to cut the film from it
- **Hosted project URL:** <https://ride-storyteller-public-demo-q53n7masba-an.a.run.app>
  — reachable without a Google account since 2026-09-09 (the invoker IAM
  check is disabled on the service; the organisation's policy refuses an
  `allUsers` binding, so that is the sanctioned route), and every page except
  `/health` requires the judge's HTTP Basic credential. **Fill the judge
  username and password into the submission form's Testing instructions
  field**; they live only in `private-media/hosting/judge-credential.yaml`
  on the owner's machine, never in this repository. Verified from outside:
  401 without or with a wrong credential, 200 with it (both languages),
  405 for POST, 413 for a request body, 403 for every private route, the
  five protective headers, and 429 with `Retry-After` after sixty requests
  in a minute. See [`docs/public-demo-hosting.md`](docs/public-demo-hosting.md).
- **Public YouTube/Vimeo demo URL:** `PENDING`
- **OSI-approved root license:** `AGPL-3.0-only`; full text is in the repository-root
  `LICENSE` file
- **Music title, creator, license, and source URL:** *Wandering* by Numall Fix
  (https://soundcloud.com/numall-fix), royalty free music by
  https://www.free-stock-music.com, licensed CC BY 3.0 Unported
  (https://creativecommons.org/licenses/by/3.0/). Every track the repository
  carries is credited in [`docs/music-credits.md`](docs/music-credits.md)

### Product lists

- **Google Cloud products:** Vertex AI / Gemini, Google ADK, Google Cloud Agent
  Platform Runtime, Cloud Run, Artifact Registry, and Cloud Storage staging.
- **Other tools/products:** IBM Bob, Python, Gunicorn, FFmpeg/ffprobe planning,
  Garmin Connect GPX export, and GoPro source footage.

### Registration profile and agreements

- **Hackathon registration:** completed and verified live on 2026-08-24.
- **Rules, eligibility, and Devpost terms:** explicitly agreed for registration.
- Registration answers and identifiers are intentionally not duplicated in this
  public-submission draft. Submission-specific fields above still require their
  own participant confirmation.
