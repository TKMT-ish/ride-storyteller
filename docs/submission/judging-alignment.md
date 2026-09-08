# Judging alignment

> Working evidence map for the four official five-point criteria. Rewritten
> 2026-09-07. It does not invent impact metrics, and it does not treat
> unfinished gates as accomplishments. Every figure is measured from real rides
> and reproducible from the repository.

## Technological Implementation

**Evidence available now**

- **Twelve consecutive riding days of one tour were judged, and twelve films
  were cut from those judgements.** Candidates come from the footage itself:
  **4,039 twelve-second windows**, each copied down locally and sent as a few
  hundred kilobytes — **2.3 GiB in place of some fifty hours of 4K**. Gemini
  2.5 Flash returned a structured judgement for every one, for about **¥764**
  in total — a figure that also covers the windows bought a second time as the
  questions asked of the model grew. The films run three to seven minutes each.
- **The model is asked more than two scores.** Each window also answers how
  much of the rider is in frame, whether the bike moved at all, what the road
  is doing (joining or leaving a highway, entering or leaving a town, setting
  off, pulling in), how photogenic the frame is and of what, and what kind of
  place the bike is standing at with the name on its sign. Those answers are
  what let the film cut on the moment of setting off rather than the minute
  that scored best nearby.
- **Fact about the world is read from the map, not guessed from the track.**
  Touring routes, state highways, ferry lines, towns and passes are fetched
  once per country from OpenStreetMap and then matched offline. A ferry
  crossing is claimed only when the charted line, the track's own pace and
  distance, and the camera all agree — a shore road that followed a charted
  line for ninety minutes is not a crossing.
- The agent is built with Agent Builder's **Agent Development Kit** on Gemini
  2.5 Flash and hosted on Agent Builder's **Agent Engine** in Tokyo, using
  fixed synthetic input. Component-by-component conformance, including what is
  deliberately not used, is in `agent-builder-conformance.md`.
- The one question a person answers — the camera-to-GPS clock offset — is
  proposed with its evidence rather than typed in. It recovered −46,800 s from
  49 recordings, unambiguously, on the real ride.
- Chapter cards are laid out as HTML and rasterised by the operating system,
  because the installed FFmpeg was built without freetype or libass and this
  project carries no runtime dependencies. The same HTML is drawn by macOS
  Quick Look locally and headless Chromium in a Linux container; measured
  against each other, layout and content agree exactly.
- The render writes beside its destination and moves the file into place only
  once whole, so an interrupted encode leaves no film rather than an unplayable
  one.
- A schema-constrained Vertex AI video transport accepts only an already
  approved `gs://` object and cannot upload local files.
- A private Cloud Run revision whose safe health and demo routes pass and whose
  private or Google-execution routes fail closed.
- IBM Bob development findings mapped to implemented changes and tests.
- **2,328 tests, all passing, every one built from synthetic fixtures**;
  nothing in the suite reaches Google or reads a real ride.
- A public AGPL source repository whose exact link is rendered by the
  authenticated private hosted UI.

**Still required**

- Public unauthenticated hosted URL verification.
- The recorded three-minute demo.

## Design

**Evidence available now**

- GPS context proposes where to look but never asserts what the camera saw.
- **The day has a shape, not a ranking.** A film is cut into legs, halt to
  halt; each leg is a chapter whose full-screen card says where it went from
  and to, and carries "Day N" on a multi-day trip. The turns of the day are
  said in the lower third with the local time — through a town, onto a scenic
  route, off the highway toward somewhere, over a pass, boarding the ferry —
  and each stop says what it was: fuel, lunch, a lookout, a visit.
- **The opening is four pictures, chosen as pictures.** Research on highlight
  selection (sensor-driven auto-highlights, egocentric summarisation,
  picturesque frame selection) is written up in
  `../research-touring-video-editing-ja.md`; what came of it is four
  one-second cuts of four different subjects, spread across the day, preferring
  a moving frame to a standing one.
- **Six rounds of the owner's own viewing notes** drove the structure above.
  The design record keeps each round and what changed because of it.
- **The film is honest about its own coverage.** Most of a ride is never
  filmed; rather than fill those stretches with footage that does not exist,
  each becomes a chapter card carrying only what the track proves — duration,
  distance, climb and descent — over a drawing of the route with that stretch
  picked out.
- **Human input is one question, not a queue.** Everything except the clock
  offset is decided from evidence, so the product does not ask a person to
  approve what it could establish itself.
- One local console runs the whole path — intake, copies, judgement, film —
  one job at a time in the background. The one action that spends money
  starts only when the figure the page showed is typed back, to the yen, and
  that check happens before any import that could reach Google.
- Japanese and English presentation share stable internal identifiers, and
  subtitle timing is identical across languages by construction.
- Public mode visibly disables private inputs and billable cloud actions.
- No voice narration. The film uses visual sequence, the route drawing, edit
  rhythm, and copyright-free music credited in `../music-credits.md`.
- Every private view returns aggregates and fixed reason codes only — never an
  event ID, asset ID, source file name, path, coordinate, or capture time.
- **A privacy rule inside the cut itself**: a window that could identify a
  private home — a driveway, a carport, a house's garage — is refused outright,
  even when it is the day's own departure.

**Still required**

- Human review of the final English copy, subtitles, and recording.
- Final screenshot set at submission resolution.

## Potential Impact

**Evidence available now**

- One real touring day produced **68.1 GiB** of video. **219 MiB** — three
  tenths of one percent — is what the five-minute film shows. Manual review of
  the rest is the concrete bottleneck this addresses.
- Which 219 MiB to use is decided from a **2.56 MiB** GPS track and video
  metadata alone, before any pixel is read. That ordering is what would let an
  edge agent narrow the material and a cloud service compose it without the
  source video ever moving — the design in `../cloud-architecture-ja.md`.
- The privacy property is a consequence of that ordering rather than a
  restriction bolted on: ride footage contains other people, and the material
  proving the story never has to leave the rider's machine.
- The same pattern applies to other location-rich unscripted footage, without
  claiming this prototype already serves those users.

**Still required**

- Measure review time and the false-positive rate from user labels. Do not
  infer time savings from candidate counts, and do not publish a
  time-saved percentage until it has been measured.

## Quality of the Idea

**Evidence available now**

- The differentiator is an evidence-seeking story agent, not generic automatic
  video summarisation.
- Telemetry is treated as a question generator and video as the evidence
  source, which is a direct answer to hallucinated visual storytelling.
- **What is not filmed is narrated from what the ride proves, not invented.**
  A gap card states duration, distance and elevation because the GPS track
  establishes them, and says nothing about what the road looked like.
- **The film cannot quietly shrink.** A beat naming footage nobody confirmed
  stops the render rather than producing a shorter film that looks finished.
- Every decision is written down as an inspectable artifact — the story plan,
  the health verdict, the chapter text — so a claim can be checked rather than
  trusted.

**Still required**

- Publish the three-minute demo, which the repository assembles from a
  finished film, after reviewing its footage for faces and number plates.
- Keep the film output distinct from the product demonstration.

## Claims this document must not make

Recorded because earlier versions made the first two.

- **Not** that Gemini's judgement was validated against a person's. It judged
  4,039 real windows across twelve days and the films were cut from them; the
  owner has watched the films and driven six rounds of changes, but nobody has
  compared the model's per-window choices against a rider's own. (Earlier
  versions of this document said Gemini had never analysed real footage. That
  was true until 2026-09-03.)
- **Not** that a person confirms each clip's visual evidence. Since the
  2026-09-01 decision, that follows automatically from timestamp matching;
  since 2026-09-03, the model's judgement decides what the film shows.
- **Not** that the hosted agent has processed a real ride. The real ride was
  judged from the local console; the hosted agent has only ever received
  fixed synthetic events.
- **Not** a measured time saving, until one is measured.
