# Three-minute English demo

Rewritten 2026-09-09 for **scenario v2** ([`demo-scenario-v2-ja.md`](demo-scenario-v2-ja.md),
approved by the owner that day). **The demo is assembled by the repository, not
recorded by hand**: `python -m app.submission.demo_scenario_v2 <english package>`
cuts it from the finished English film, the day's own judged windows and two
screenshots of the local console, and writes the subtitle file beside it from
the same timeline, so captions and subtitles cannot drift apart.

**Every figure on screen comes from the day's records.** The inputs file
(`private-media/work/demo-v2/inputs.json`) carries the measured figures --
35 GoPro files, 108.6 GB, 4 h 43 min, 337 windows, 245.1 MB, ¥49.79, 43 windows
at 0.7 or more, 63 beats, 380 s, about 80 minutes of machine time, two
confirmations -- and the assembler refuses to run unless the window count,
cost and megabytes agree with what the package's judgement bought. A test
forbids any id, file name, path, coordinate or capture time appearing in any
caption, card, tag, badge or judgement panel.

**Three kinds of screen, told apart on sight.** Raw footage (the day's own
480p judging copies) fills the frame under a `RAW GoPro · unedited` tag; the
local console fills the picture area under a `Local console` tag with the
caption in a band below; **the finished film is the only thing shown at 80 %**,
top-right in a thin frame under the badge `Ride Storyteller output · day 7 · no
one edited this`, and goes full-screen only for the last ten seconds of the
result.

**The demo uses the real film.** The published video shows a real ride, so
**every frame of the joined demo is read for faces and plate-shaped text on
this machine before it is kept** (`app.plate_blur`, Apple Vision); plates are
blurred, and a face anywhere removes the file. Publishing remains a separate,
deliberate act by the owner.

---

## The timeline

Two minutes fifty-seven, in ten segments (fourteen cuts). It stops short of the
three-minute ceiling on purpose: an encode lands a few hundredths of a second
over its own sum, and a demo measured at 3:00.02 is one an automated check can
refuse.

| # | Start | Hold | Kind | What is on screen |
|---|-------|------|------|-------------------|
| 1 | 0:00 | 8 s | film, framed | The coast road down from the lookout. "Made by Ride Storyteller from 4 hours 43 minutes of GoPro footage. No one edited this." |
| 2 | 0:08 | 12 s | raw, mosaic | Twelve judged windows at once, all grey road. "One day of riding: 108 GB of video, 4 hours 43 minutes. Nearly all of it looks like this." |
| 3 | 0:20 | 12 s | raw, single | One window alone, nothing happening. "Finding the good minutes means watching all of it. So the footage sat on a hard drive." |
| 4 | 0:32 | 15 s | console | The film's first chapter card with its route. "The GPS track already knows where the day happened … Every leg becomes a chapter." |
| 5 | 0:47 | 18 s | console | The workflow page: 337 clips · 245.1 MB · ¥49.79, copies 337 / 337. "Locally, ffmpeg cuts 337 twelve-second windows and shrinks each to 480p at one frame a second: 245 MB in all. The 4K never leaves the machine." |
| 6 | 1:05 | 15 s | console | The approval card: what is sent, to whom, for how long; the amount to type back. "One page shows the price — ¥49.79 — and waits for a person to type that figure back. Nothing is bought until then." |
| 7 | 1:20 | 30 s | raw + judgement | Four windows, 7.5 s each, with the model's own words and scores beside them: two vistas, a halted bike, a plain road. "Gemini 2.5 Flash judges every window … 337 structured judgements. Only 43 scored 0.7 or more." |
| 8 | 1:50 | 15 s | console | The figures card. "The story planner keeps 63 beats in the order the day happened; ffmpeg cuts the film and adds the music. About 80 minutes of machine time. Two confirmations from a person." |
| 9 | 2:05 | 40 s | film, framed then full | From the lookout stop through the chapter card to the lake road; the last ten seconds full-screen with the badge. "The result: six minutes, chapters named by place, a map in the corner, sections for scenic roads and stops." |
| 10 | 2:45 | 12 s | card | "Open source (AGPL-3.0). Runs on your machine. About ¥50 of Gemini per riding day. Judges: the day-7 package cuts this film on your own computer. Music: Wandering by Numall Fix · CC BY 3.0 · royalty free music by www.free-stock-music.com" |

`--cold-open-s` and `--result-start-s` choose where in the film segments 1 and
9 begin (163 s and 303 s of the English film: the descent from the Bluff
lookout, and the Clyde lookout stop into the chapter card and the lake road).
Both were chosen by reading the film's frames, and both lie well clear of the
only seconds in which a face appears (98–103 s).

## The build

```bash
python -m app.submission.demo_scenario_v2 private-media/work/day-7-en-v1 \
  --inputs private-media/work/demo-v2/inputs.json \
  --film private-media/work/day-7-en-v1/ride-storyteller-story-film-scored.mp4 \
  --cold-open-s 163 --result-start-s 303 \
  --console-copies-png private-media/work/demo-v2/console-copies.png \
  --console-cost-png private-media/work/demo-v2/console-cost.png \
  --skip-inspection --overwrite
python -m app.plate_blur private-media/work/day-7-en-v1/demo/demo-v2-en.mp4 \
  private-media/work/day-7-en-v1/demo/demo-v2-en-published.mp4 --fps 30 --passes 4
```

The English package is the day-7 package re-cut with `output_language: en`
(the judgements are reused; nothing was bought again). The two console
screenshots come from the real `/workflow` page reading a copy of the package
from which the judgement was removed, so the approval card shows the real
figures. The inputs file's windows were chosen from the day's 337 judgements
(monotony by the model's own interest score) and every one of the seventeen
was inspected for faces and plate-shaped text before it was allowed in; two
were dropped for that.

## Narration

There is no spoken track. [`demo-narration-en.md`](demo-narration-en.md) holds
the script the owner may record later (301 spoken words, timed per segment,
with a Japanese gloss), kept in step with this timeline.

## Previous version (v1, 2026-09-07)

### The v1 candidate that was assembled

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
