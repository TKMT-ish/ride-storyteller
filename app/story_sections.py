"""Sections: the lines of story laid over a window inside a leg (節).

The owner's frame (2026-09-06, point 8): a chapter says where the leg
went from and to; a section, said in the lower third over a moving
picture, says where the ride is now and where the story turns -- through
a town, leaving the highway toward somewhere, onto a scenic route and
off it again, at a stop. Sections come from the track and the reference
files, are named by the place service, and are laid on the window nearest
their moment. A moment with no window near it is simply not said.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from app.agents.story_planner import StoryOutputLanguage
from app.gap_chapters import GapCharacter
from app.scenic_routes import ScenicStretch
from app.stop_kinds import StopKind
from app.story_package import JourneyStoryPlan, SectionNote, StoryPlanBeat
from app.story_timeline import StoryBeatKind

# A section line stays up this long, and leaves the window clean at the end.
SECTION_S = 4.0
SECTION_CLEAR_TAIL_S = 1.0
MIN_SECTION_S = 2.5
# A window may begin this long before the moment and still show it, and
# the line may wait this long for a window after the moment (a "leaving
# the route" said twenty minutes late still tells the story).
SECTION_LEAD_S = 30.0
SECTION_WITHIN_S = 20 * 60.0
# The ride is off a highway once it has been off for this long, and has
# ridden this far off it: a stop beside the road is not an exit.
OFF_HIGHWAY_FOR_S = 10 * 60.0
OFF_HIGHWAY_M = 5_000.0
# The same line within this long of itself is said once.
REPEAT_WITHIN_S = 30 * 60.0


class SectionKind(StrEnum):
    TOWN = "town"
    HALT_PLACE = "halt_place"
    STOPOVER = "stopover"
    SCENIC_IN = "scenic_in"
    SCENIC_OUT = "scenic_out"
    HIGHWAY_OFF = "highway_off"
    HIGHWAY_ON = "highway_on"
    DEPARTURE = "departure"
    ARRIVAL = "arrival"
    # Into a town the ride then stops in, a named road, a pass, the ferry's
    # two ends, and the name of a stop's own place (2026-09-07).
    TOWN_IN = "town_in"
    ROAD = "road"
    PASS = "pass"
    FERRY_ON = "ferry_on"
    FERRY_OFF = "ferry_off"
    PLACE = "place"


@dataclass(frozen=True)
class SectionEvent:
    """A section's moment on the ride's clock, and its line."""

    kind: SectionKind
    at: datetime
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("a section needs its line")


# --- the lines ------------------------------------------------------------------


def _ja(language: StoryOutputLanguage) -> bool:
    return language is StoryOutputLanguage.JAPANESE


def town_line(town: str, language: StoryOutputLanguage) -> str:
    return f"{town}を通る" if _ja(language) else f"Through {town}"


def town_in_line(town: str, language: StoryOutputLanguage) -> str:
    return f"{town}に入る" if _ja(language) else f"Into {town}"


def road_line(road: str, language: StoryOutputLanguage) -> str:
    return f"{road}を走る" if _ja(language) else f"Along {road}"


def pass_line(name: str, elevation_m: float | None, language: StoryOutputLanguage) -> str:
    line = f"{name}を越える" if _ja(language) else f"Over {name}"
    if elevation_m is not None and elevation_m > 0:
        line += f" · 標高{int(elevation_m)}m" if _ja(language) else f" · {int(elevation_m)} m"
    return line


def ferry_on_line(name: str | None, language: StoryOutputLanguage) -> str:
    line = "フェリーに乗船" if _ja(language) else "Boarding the ferry"
    return f"{line} · {name}" if name else line


def ferry_off_line(place: str | None, language: StoryOutputLanguage) -> str:
    if place:
        return f"{place}でフェリーを下船" if _ja(language) else f"Off the ferry at {place}"
    return "フェリーを下船" if _ja(language) else "Off the ferry"


def place_line(spot: str, language: StoryOutputLanguage) -> str:
    return spot


def stop_line(
    kind: StopKind, place: str | None, minutes: int, language: StoryOutputLanguage
) -> str:
    """What the stop was, where, and for how long -- by the kind of place it was."""
    where = place or ("ここ" if _ja(language) else "Here")
    tail = f" · {minutes}分" if _ja(language) else f" · {minutes} min"
    if kind is StopKind.FUEL:
        return (f"{where}で給油" if _ja(language) else f"{where} · fuel") + tail
    if kind is StopKind.LUNCH:
        return (f"{where}で昼食" if _ja(language) else f"{where} · lunch") + tail
    if kind is StopKind.MEAL:
        return (f"{where}で食事" if _ja(language) else f"{where} · a meal") + tail
    if kind is StopKind.ATTRACTION:
        return (f"{where}を見学" if _ja(language) else f"{where} · a visit") + tail
    if kind is StopKind.LOOKOUT:
        return (f"{where} · 展望" if _ja(language) else f"{where} · lookout") + tail
    if kind is StopKind.SHOP:
        return (f"{where}で買い物" if _ja(language) else f"{where} · shopping") + tail
    if kind is StopKind.LODGING:
        return (f"{where}に立ち寄る" if _ja(language) else f"{where} · a stop") + tail
    if kind is StopKind.STOPOVER:
        return stopover_line(place, minutes, language)
    return halt_line(place, minutes, language)


def halt_line(place: str | None, minutes: int, language: StoryOutputLanguage) -> str:
    where = place or ("ここ" if _ja(language) else "Here")
    return f"{where}で休憩 · {minutes}分" if _ja(language) else f"{where} · {minutes} min stop"


def stopover_line(place: str | None, minutes: int, language: StoryOutputLanguage) -> str:
    where = place or ("ここ" if _ja(language) else "Here")
    return f"{where}に立ち寄る · {minutes}分" if _ja(language) else f"{where} · {minutes} min"


def scenic_in_line(route: str, language: StoryOutputLanguage) -> str:
    return f"{route}に入る" if _ja(language) else f"Onto the {route}"


def scenic_out_line(route: str, language: StoryOutputLanguage) -> str:
    return f"{route}を離れる" if _ja(language) else f"Leaving the {route}"


def highway_on_line(road: str, language: StoryOutputLanguage) -> str:
    return f"{road}に入る" if _ja(language) else f"Onto {road}"


def departure_line(place: str | None, language: StoryOutputLanguage) -> str:
    if place:
        return f"{place}を出発" if _ja(language) else f"Leaving {place}"
    return "出発" if _ja(language) else "Setting off"


def arrival_line(place: str | None, language: StoryOutputLanguage) -> str:
    if place:
        return f"{place}に到着" if _ja(language) else f"Arriving in {place}"
    return "到着" if _ja(language) else "Arriving"


def with_clock(line: str, at: datetime, local_offset_s: float | None) -> str:
    """The line with the local time in front -- the owner's point 9 (2026-09-07)."""
    if local_offset_s is None:
        return line
    local = at + timedelta(seconds=local_offset_s)
    return f"{local.strftime('%H:%M')} · {line}"


def highway_off_line(road: str, toward: str | None, language: StoryOutputLanguage) -> str:
    if toward:
        return f"{road}を離れ、{toward}へ" if _ja(language) else f"Off {road}, toward {toward}"
    return f"{road}を離れる" if _ja(language) else f"Off {road}"


# --- the moments ----------------------------------------------------------------


def scenic_events(
    stretches: Sequence[ScenicStretch],
    *,
    ride_start: datetime,
    ride_end: datetime,
    language: StoryOutputLanguage,
    edge_s: float = 10 * 60.0,
    out_edge_s: float = 20 * 60.0,
) -> tuple[SectionEvent, ...]:
    """Onto and off each scenic route, except near the day's own ends.

    Off a route within `out_edge_s` of the day's end is where the route
    ends and the day with it; the arrival says that.
    """
    events: list[SectionEvent] = []
    edge = timedelta(seconds=edge_s)
    out_edge = timedelta(seconds=out_edge_s)
    for stretch in stretches:
        if stretch.start_time > ride_start + edge:
            line = scenic_in_line(stretch.route, language)
            events.append(SectionEvent(SectionKind.SCENIC_IN, stretch.start_time, line))
        if stretch.end_time < ride_end - out_edge:
            line = scenic_out_line(stretch.route, language)
            events.append(SectionEvent(SectionKind.SCENIC_OUT, stretch.end_time, line))
    return tuple(sorted(events, key=lambda e: e.at))


def highway_exits(
    runs: Sequence[ScenicStretch],
    *,
    ride_end: datetime,
    toward: Mapping[datetime, str | None] | None = None,
    language: StoryOutputLanguage,
    off_for_s: float = OFF_HIGHWAY_FOR_S,
    advanced: Callable[[datetime, datetime], float] | None = None,
    off_m: float = OFF_HIGHWAY_M,
) -> tuple[SectionEvent, ...]:
    """Where the ride left a highway for good -- the next highway is far off, or none.

    `runs` are the day's runs along the highways (app.scenic_routes on the
    highways reference). `toward` maps a run's end to the place the ride was
    heading for -- the leg's own end -- when one is known. `advanced` says
    how far the track went between two moments; with it, a stop beside the
    highway that rejoins it after less than `off_m` of riding is no exit.
    """
    ordered = sorted(runs, key=lambda r: r.start_time)
    events: list[SectionEvent] = []
    for index, run in enumerate(ordered):
        following = ordered[index + 1] if index + 1 < len(ordered) else None
        next_on = following.start_time if following is not None else ride_end
        if (next_on - run.end_time).total_seconds() < off_for_s:
            continue
        if advanced is not None and advanced(run.end_time, next_on) < off_m:
            continue
        if (ride_end - run.end_time).total_seconds() < off_for_s:
            continue  # the day ends here; the arrival says so
        heading = (toward or {}).get(run.end_time)
        line = highway_off_line(run.route, heading, language)
        events.append(SectionEvent(SectionKind.HIGHWAY_OFF, run.end_time, line))
    return tuple(events)


def highway_entries(
    runs: Sequence[ScenicStretch],
    *,
    ride_start: datetime,
    language: StoryOutputLanguage,
    off_for_s: float = OFF_HIGHWAY_FOR_S,
    advanced: Callable[[datetime, datetime], float] | None = None,
    off_m: float = OFF_HIGHWAY_M,
    settle_s: float = 2 * 60.0,
) -> tuple[SectionEvent, ...]:
    """Where the ride joined a highway after being off one -- or off any, from the start.

    A run that begins within `settle_s` of the day's start is the road the
    day began on, not a joining. Between two runs, the same rule as for an
    exit: ten minutes and five kilometres off, else it never really left.
    """
    ordered = sorted(runs, key=lambda r: r.start_time)
    events: list[SectionEvent] = []
    for index, run in enumerate(ordered):
        previous = ordered[index - 1] if index > 0 else None
        since = previous.end_time if previous is not None else ride_start
        if previous is None and (run.start_time - ride_start).total_seconds() < settle_s:
            continue
        if previous is not None:
            if (run.start_time - since).total_seconds() < off_for_s:
                continue
            if advanced is not None and advanced(since, run.start_time) < off_m:
                continue
        events.append(
            SectionEvent(
                SectionKind.HIGHWAY_ON, run.start_time, highway_on_line(run.route, language)
            )
        )
    return tuple(events)


# --- laying them on the film -------------------------------------------------------


def attach_sections(
    plan: JourneyStoryPlan,
    events: Sequence[SectionEvent],
    ride_starts: Mapping[str, datetime],
    *,
    stays_s: float = SECTION_S,
    lead_s: float = SECTION_LEAD_S,
    within_s: float = SECTION_WITHIN_S,
    within_by_kind: Mapping[SectionKind, float] | None = None,
) -> JourneyStoryPlan:
    """Lay each section's line on the window nearest its moment.

    A window that begins up to `lead_s` before the moment, or up to
    `within_s` after it, can carry the line; the nearest one does, one line
    per window, and a window that opens a chapter with its title is passed
    over so the two never overlap. The line stays `stays_s`, capped so the
    window ends clean; a window too short for that carries nothing.

    `within_by_kind` shortens the wait for the lines that go stale: "through
    a town" laid on a window eight minutes later says it over the wrong
    place, while "off the highway toward X" is still true twenty minutes on.
    """
    if stays_s <= 0 or lead_s < 0 or within_s < 0:
        raise ValueError("the section timings must be positive")
    beats = list(plan.beats)
    taken: set[int] = set()
    # The cold open -- a window before the headline -- carries no line; the
    # headline says where the day is.
    if len(beats) >= 2 and beats[0].kind is StoryBeatKind.FOOTAGE and _is_headline(beats[1]):
        taken.add(0)
    said: list[SectionEvent] = []
    for event in sorted(events, key=lambda e: e.at):
        if any(
            s.kind is event.kind
            and s.text == event.text
            and (event.at - s.at).total_seconds() < REPEAT_WITHIN_S
            for s in said
        ):
            continue
        best: int | None = None
        best_gap = float("inf")
        for index, beat in enumerate(beats):
            if beat.kind is not StoryBeatKind.FOOTAGE or beat.card is not None or index in taken:
                continue
            begins = ride_starts.get(beat.event_id or "")
            if begins is None:
                continue
            gap = (begins - event.at).total_seconds()
            reach = (within_by_kind or {}).get(event.kind, within_s)
            if -lead_s <= gap <= reach and abs(gap) < best_gap:
                best, best_gap = index, abs(gap)
        if best is None:
            continue
        beat = beats[best]
        stays = min(stays_s, beat.screen_duration_s - SECTION_CLEAR_TAIL_S)
        if stays < MIN_SECTION_S:
            continue
        beats[best] = replace(
            beat,
            section=SectionNote(kind=event.kind.value, text=event.text, screen_duration_s=stays),
        )
        taken.add(best)
        said.append(event)
    return replace(plan, beats=tuple(beats))


def _is_headline(beat: StoryPlanBeat) -> bool:
    return (
        beat.kind is StoryBeatKind.GAP_CARD
        and beat.card is not None
        and beat.card.character is GapCharacter.HEADLINE
    )


def sections_of(plan: JourneyStoryPlan) -> tuple[StoryPlanBeat, ...]:
    """The footage beats that carry a section, in order."""
    return tuple(b for b in plan.beats if b.kind is StoryBeatKind.FOOTAGE and b.section is not None)
