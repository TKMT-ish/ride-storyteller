# Three-minute English demo

Rewritten 2026-09-07. **The demo is assembled by the repository, not recorded
by hand**: `python -m app.submission.demo_assembly <package>` cuts it from a
finished film and the package's own console figures, and writes the subtitle
file beside it from the same timeline, so the captions and the subtitles cannot
drift apart. What follows is what that timeline says and why, and what a person
must still do before it is published.

**Every number on screen comes from the package.** The console card is filled
from the same payload the local page reads — window counts, megabytes, yen — and
a test forbids any file name, path, coordinate or capture time appearing in any
card or caption.

**Decided 2026-09-03: the demo uses the real film.** The owner chose real
footage over a labelled synthetic stand-in. The published video therefore shows
a real ride, including other road users who did not consent. **Reviewing the
footage in the assembled demo for identifiable faces and number plates is a
precondition of publishing it**, and publishing is a separate, deliberate act by
the owner.

---

## The timeline

Two minutes fifty-seven, in nine segments. It stops short of the three-minute
ceiling on purpose: an encode lands a few hundredths of a second over its own
sum, and a demo measured at 3:00.02 is one an automated check can refuse.

Five of the nine are stretches of the finished film, cut back to back from one
place in it, each carrying its narration as a caption over the lower third — the
same lower third the film itself uses. Well over half the running time is
footage, because a demo that opens on cards and closes on fifteen seconds of
video reads as a slideshow rather than a video product (Q5 of
`../user-feedback-2026-09-04-ja.md`).

| # | Segment | Hold | What is on screen |
|---|---------|------|-------------------|
| 1 | `problem` | 20 s | Film. "One day, 68 gigabytes of video." / "Somewhere in it is a story worth watching." |
| 2 | `evidence` | 25 s | Film. "The track gives the day its shape." / "Each leg — halt to halt — is a chapter that says where it went from and to." |
| 3 | `clock` | 20 s | Film. "One question needs a person." / "The system proposes the clock offset with its evidence; a person confirms it." |
| 4 | `chapter-a` | 15 s | A chapter card from the film itself, with the route drawn and the stretch picked out. |
| 5 | `chapter-b` | 15 s | A second chapter card, later in the day. |
| 6 | `console` | 25 s | Full-screen card of the console's own figures: windows planned, megabytes to send, yen against the ceiling, copies made, windows judged, beats and seconds planned. |
| 7 | `gemini` | 25 s | Film. "Gemini decides what the film shows." / "Every window is judged on a small copy — the 4K source never leaves the machine." / "Setting off, each stop, joining the highway: the moments the track proves are kept." |
| 8 | `bob` | 15 s | The sanitized IBM Bob review screenshot. |
| 9 | `close` | 17 s | Film. "Telemetry becomes a story." / "The footage that proves it stays on your machine." |

`--excerpt-start-s` chooses where in the film the five stretches begin. Pick a
stretch with open road and no legible plates; the five are contiguous, so
reviewing them is one continuous look rather than five.

## The candidate already assembled

`private-media/work/day-7-v1/demo/demo-en-published.mp4`, 177.03 s, cut with
`--excerpt-start-s 240` from the day's film and then passed through the plate
blur. The owner chose that day (2026-09-08); the excerpt begins where it does
because the whole film was read for faces first and they appear in one place
only, between 98 and 110 seconds, so everything published comes from after
that.

**Checked at every frame.** The published file was read again at 30 frames a
second, which is every frame of it: **no plate-shaped text and no face**. The
looser passes that made it had found four plate regions in all, two of them
only after the sampling rate was doubled.

**What was done to it, and what that is worth.** Every number plate the reader
could make out is blurred (`app.plate_blur`), and no face appears anywhere in
the published minutes. That is a real reduction, not a guarantee: reading is
sampled, and a plate the reader cannot make out is a plate that stays legible.
Raising the sampling rate found plates that a slower pass had missed, twice.
**Watch the five stretches through before publishing.**

## Blurring what is published

```bash
python -m app.plate_blur <film-in> <film-out> --fps 20 --passes 4
```

Each pass reads the blurred copy, adds what it finds to what it already had,
and blurs the **original** again, so the file is encoded once however many
passes it takes. It refuses outright when a face appears, which is the owner's
rule: drop that footage rather than blur the person.

## Assembling it

```bash
python -m app.submission.demo_assembly private-media/work/<package> \
  --excerpt-start-s <seconds> --overwrite
```

It writes `private-media/work/<package>/demo/demo-en.mp4` and
`demo-subtitles-en.srt` beside it. Nothing is published. The film must already be
scored (`ride-storyteller-story-film-scored.mp4`), which the film command
produces when a music track is chosen.

## What this demo must never claim

Kept here because earlier drafts claimed two of them.

- **Not** that Gemini's judgement has been validated against a rider's. Across
  twelve riding days it judged 4,039 real windows and the films were cut from
  those judgements; that is what to show, and what not to overstate.
- **Not** that a human reviews each clip's visual evidence. Since the
  2026-09-01 decision, per-clip evidence follows automatically from timestamp
  matching; the single human confirmation is the clock offset, and on cameras
  with their own GPS not even that is asked.
- **Not** that the hosted agent has processed a real ride. It has only ever
  received fixed synthetic events.
- **Not** that the hosted public demo application carries real material. It is
  synthetic only. This is separate from the demo video, which does show real
  footage by the 2026-09-03 decision — the application and the recording are two
  different things and must not be conflated on camera.
- **Not** that no data leaves the machine. Two things do, deliberately: the
  judged proxy windows, and one coordinate rounded to four decimals per place
  name. Say so plainly rather than claiming more than is true.

## Before publishing

1. Watch the assembled demo end to end.
2. Look at the five footage stretches for identifiable faces and number plates.
   If either appears, re-assemble with a different `--excerpt-start-s`.
3. Check that the console card's figures are the ones you mean to show.
4. Upload to YouTube or Vimeo, public, three minutes or less, with the generated
   `.srt` as the subtitle track. Upload `demo-en-published.mp4`: the blurred
   picture with the chosen music on it. Not `demo-en.mp4`, which is neither.
5. Put the link in the Devpost form and in `devpost-submission.md`.
