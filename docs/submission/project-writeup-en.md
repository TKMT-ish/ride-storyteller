# Ride Storyteller — English project write-up

> Local working draft, rewritten 2026-09-07. It has not been copied to Devpost.
> Registration and the rules/eligibility agreements were completed and verified
> live on 2026-08-24. The IBM track, submission-specific participant answers,
> and AGPL-3.0 license are confirmed; public deliverables remain pending.
>
> Every measurement here comes from real rides and is reproducible from the
> repository. Nothing in this document describes a capability that has not been
> run. No place name, file name or coordinate from the rider's own material
> appears here, by rule.

## Inspiration

A motorcycle tour produces hours of beautiful footage and no film. One touring
day here left **68.1 GiB** of video; the twelve-day tour behind this submission
left **359 recordings and 50 hours** of it. Of a single day, roughly **three
tenths of one percent** is what a five-minute film actually shows. The problem
was never a shortage of material. It was that finding the story meant scrubbing
through hours of road, and that the story is not "the best-looking clips" — it
is *where the rider went, and what happened on the way*.

## What it does

Ride Storyteller turns one day's GPS track and footage into one short film,
locally, from evidence. Twelve consecutive days of one tour have been cut this
way, each into its own film of three to seven minutes.

**The track decides the shape of the day.** A day is cut into *legs* — halt to
halt — and each leg is a chapter with a full-screen card that says where it
went from and where it went to, plus what the track proves about it: distance,
climb, descent, how long the rider stood at its end. On a trip of several days
the cards carry "Day N", detected from the sibling packages' dates rather than
configured. A day with few stops promotes its short ones so that a film still
has a shape; a day with many folds the shortest legs together so it does not
become a list.

**Exactly one question needs a person.** Whether the camera's clock agreed with
the GPS receiver's cannot be decided from the data: a camera thirteen hours out
and a ride thirteen hours later are identical once you discard the answer. So
the system proposes the offset with its evidence — how many recordings land
wholly inside the ride, how much of it they cover — and a person confirms one
number. On the first real ride it recovered −46,800 s from 49 recordings,
unambiguously. Where the cameras' own GPS is present the offset is read from it
to the second, and no one is asked at all.

**Gemini decides what the film shows.** Candidates are drawn from the footage
itself, not only from where GPS raised an event — on one ride that is 173
twelve-second windows against seven. Each window is copied down locally to a
few hundred kilobytes (one frame a second, 480 lines, no audio), and only those
copies are sent. Across the twelve days that is **4,039 windows and 2.3 GiB of
proxies** in place of a terabyte and a half of 4K. Gemini 2.5 Flash watches each
window and answers a fixed schema: what the road is, what the scenery is, how
interesting and how relevant it is, **how much of the rider is in the frame,
whether the bike moved at all, what the road is doing** (joining or leaving a
highway, entering or leaving a town, setting off, pulling in), **how much a
travel photographer would want the frame and of what**, and **what kind of
place the bike is standing at** and the name on its sign. The whole trip's
judgement cost about **¥764** — under six US dollars for twelve films.

**Moments the track proves are never outvoted.** Setting off, arriving, each
stop's arrival and re-departure, joining and leaving a highway, riding off a
ferry: each becomes a window of its own, bought and judged like any other and
then kept whatever it scored, because a departure that scored 0.3 is still the
departure. Each such moment buys a small fan of neighbouring windows and the
model's own answers choose between them — the one that actually shows the bike
rolling away, not the one where it still stands.

**The story is said in the lower third.** Over a moving picture, with the local
time, the film says the turns of the day as they happen: through a town, into a
town the ride then stops in, onto and off a named scenic route, onto and off a
highway, along a road worth naming, over a pass, boarding the ferry and riding
off it, and at each stop what the stop *was* — fuel, lunch, a lookout, a museum,
a shop — with how long it lasted. A stop's kind comes from the model's own
answers about the pictures taken there, so the film says "fuel" because the
camera saw a forecourt, not because a clock says six minutes.

**The map is read, not guessed.** Which road is a designated scenic route, where
the state highways run, which water a ferry crosses, where the towns and the
passes are: all of this is fact about the world, not about the ride, so it is
read from reference files built once from OpenStreetMap and then used offline.
A ferry crossing is claimed only when the charted line, the track's own pace and
distance, *and the camera* all agree — the model must have seen a deck or a bow;
a shore road that follows the same charted line for an hour and a half does not
become a crossing, and the hours afloat are not counted as kilometres ridden.

**What was never filmed is not invented.** Most of a ride has no footage. Each
uncovered stretch is a chapter card carrying only what the track proves, over a
drawing of the route with that stretch picked out. The film is honest about its
own coverage, and it still runs from departure to arrival.

**The opening is four pictures.** Research on what makes a highlight (GoPro's
sensor-driven auto-highlights, egocentric-video summarisation, "picturesque"
highlight selection) points the same way: what holds a viewer at the start is
not the window that moves most but the frame a photographer would keep. So the
film opens on four one-second cuts chosen by the model's photogenic score, of
four different subjects, spread across the day, in ride order — and each comes
back in full inside its own chapter. A frame taken standing still waits until
every moving one has had its turn.

**Spending is gated, not defaulted.** Before anything is sent, the console shows
what judging this ride would send and cost, to the yen. Buying the judgement
starts only when that exact figure is typed back and a bucket named. A judgement
that breaks part-way keeps every window already paid for and asks only about the
rest. A film is never cut from a judgement no model was paid for.

**One page runs it.** The local console takes a new day's GPX and footage,
proposes the clock offset with its evidence, builds the package, makes the
copies, gates the spend, and cuts the film — one job at a time, in the
background. Paths are read only inside one intake folder; what reaches the
browser is counts, sizes, money and fixed reason codes.

## How we built it

- Python frozen dataclasses define validated contracts for routes, events,
  story plans, journey gaps, chapter cards, media assets, evidence decisions,
  and render plans. Every contract is a pure function over JSON.
- Deterministic GPS parsing, halt detection, moment detection and leg
  segmentation remain auditable before any model is involved.
- The agent is built with Google Cloud Agent Builder's **Agent Development
  Kit** and runs on Gemini 2.5 Flash, deciding evidence on fixed synthetic
  events. It is hosted on Agent Builder's **Agent Engine**: one synthetic-only
  runtime, verified in Tokyo. Which Agent Builder components are and are not
  used, and how to verify each, is set out in
  [`agent-builder-conformance.md`](agent-builder-conformance.md).
- Place names come from Google's Geocoding API, one rounded coordinate per
  request (four decimals, about ten metres) and the language wanted — never the
  track, never a time, never a file name — and the answer is cached in the
  package so a re-cut asks nothing again.
- Reference files (touring routes, state highways, ferry lines, towns, passes,
  named roads) are fetched once per region from OpenStreetMap through Overpass,
  by country code alone, and stored outside version control.
- Chapter cards and lower thirds are laid out as HTML and rasterised by the
  operating system — macOS Quick Look locally, headless Chromium in a Linux
  container. The installed FFmpeg was built without freetype or libass, and this
  project carries no runtime dependencies; letting the OS draw the card is what
  makes Japanese text and a drawn route possible at all.
- The route drawing scales longitude by the cosine of the route's mean
  latitude, then fits the shape into its own box. The ride's shape survives; its
  position on Earth does not.
- The film is cut in a single normalised FFmpeg pass and written beside its
  destination, then moved into place only once whole — an interrupted render
  leaves no film rather than an unplayable one.
- Music is mixed without re-encoding the picture. A track shorter than the film
  is looped and a longer one trimmed, so the sound ends with the picture.
- A lean production container runs the public demo through Gunicorn as a
  non-root user, with no Google SDK in the image.

## Safety and privacy

Ride footage contains other people — their faces, their number plates, their
houses. So the material that proves the story never leaves the rider's machine
except as the small judged proxies, and the film's own rules keep the rest out:
a window that could identify a private home — a driveway, a carport, a house's
garage — is refused outright, even when it is the day's own departure.

Real GPX logs and footage are excluded from the public source tree; place names
and media file names are kept out of version control by rule. Cloud probes use
fixed synthetic inputs and retain only safe completion metadata. Every private
view returns aggregates and fixed reason codes only: never an event ID, asset
ID, source file name, path, coordinate, or capture time.

The measured cost of that boundary is nil. Deciding which fraction of a day to
use is done from the GPS track and video metadata alone — the same ordering that
would let an edge agent narrow the material and a cloud service compose it,
without the source video ever moving. That design is written up in
[`../cloud-architecture-ja.md`](../cloud-architecture-ja.md).

## Challenges

**Separating route evidence from visual evidence.** A sharp turn identifies
where to look; it cannot prove a clip is usable. We built explicit evidence
states and fail-closed gates rather than letting the agent quietly produce an
edit.

**A film is not only its footage.** The duration gate first reported a ride as
too short, because it measured confirmed footage against the target while the
uncovered stretches were on screen as chapter cards. That was not a shortage of
material; it was the check measuring the wrong thing.

**Cameras are wrong by time zones, not minutes.** Scoring candidate offsets on
recordings that merely *overlap* the ride produces ties — shifting a four-hour
ride by two hours keeps everything overlapping. Scoring on recordings that lie
*wholly* inside it is what makes the answer unique. A folder holding every day
of a tour then breaks even that, because a wrong shift can pull another day's
recordings inside; reading the cameras' own GPS clock first is what fixed it,
after one wrong day had been paid for.

**A model that scores everything "fine".** The first ride came back with thirty
windows at exactly 0.66 and thirty-three at exactly 0.54, because "score from 0
to 1" says nothing about what a 0.3 or a 0.8 looks like on a road. Anchoring
each number to something visible — a car park, a queue of traffic, a gorge, the
shot of the day — is what made the scores separate.

**A ferry is not a road.** The track of a vessel follows a charted line at a
believable pace, and so does the shore road beside it; a receiver on a vehicle
deck loses the sky and returns readings of a hundred metres a second. Neither
the map nor the track could settle it alone. What settled it was asking the
camera: the model must have seen a deck, a bow, or the inside of the vessel.

**Watching the film is the only test that matters.** Six rounds of the owner's
own viewing notes drove more design than any metric did: a stationary opening
shot, a chapter title that said nothing, a lower third that named a whole city
for a lookout, a fuel stop that disappeared, a museum shown from inside when the
bike outside was the picture.

## Accomplishments

- **Twelve consecutive days of one tour, each cut into its own film**, from a
  single command per day, on real material and with no external transfer beyond
  the judged proxies and one coordinate per place name.
- The whole trip's model spend is about **¥764** — under six US dollars.
- Uncovered stretches are narrated from GPS-proven facts and a drawn route
  rather than filled with footage that does not exist.
- The spend gate cannot be walked around: the figure shown is the figure
  approved, to the yen.
- The single human confirmation is proposed, not guessed — and on cameras with
  their own GPS it is not needed at all.
- Local and hosted Agent Builder verification with Gemini, using no private
  data.
- A bilingual UI and deterministic bilingual Story Plan with invariant
  structural identifiers; subtitle timing is identical across languages by
  construction.
- IBM Bob reviewed the codebase and identified gaps that were then implemented
  and covered by focused tests.
- **2,246 tests, all passing, all built from synthetic fixtures**; nothing in
  the suite reaches Google.

## What we learned

Most of the interesting failures were the system quietly succeeding at the wrong
thing: a duration check measuring footage instead of the film, a render leaving
a file with no index that looked finished and would not play, a plan that did
not survive its own serialisation, a demo script describing analysis that had
never been run, a preflight that reported a 6% overshoot as a 22% saving, a
clock-offset method that pattern-matched a multi-day folder and cost a day's
judgement, a word-match that turned a road sign reading "Ferry Terminal" into a
ferry crossing.

Fail-closed gates catch the loud failures. The quiet ones are caught by asking,
repeatedly, whether the thing being measured is the thing that matters — and,
for a film, by watching it.

## What remains before submission

- Record and publish the three-minute English demo video. The demo is assembled
  locally by `python -m app.submission.demo_assembly`; publishing it is a
  separate, deliberate act by the owner, after reviewing the footage in it for
  faces and number plates.
- Make the repository public and verify its license and default branch.
- Publish the hosted application, after a separate public-access approval.
- Copy this write-up into the Devpost form and submit.
