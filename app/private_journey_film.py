"""Make one ride's film from one private package, in one call.

Gate 3 of docs/completion-roadmap-ja.md. Everything the film needs already
exists as a separate contract — the gaps, the order, the chapter text, the
plan, the cards, the cut, the subtitles. This is the seam that runs them in
sequence, so a finished package becomes a finished film without anyone
having to remember the order.

The whole run is local. It reads the package's own exports and the GPX the
package was built from; it opens no network client and takes no path to
material outside the package, so the reviewed journey cannot be swapped for
another one at the last step.

One detail decides whether the film is honest about its own length: a clip's
place on the ride is the window the camera actually filmed, which is the
asset's recorded start shifted onto GPS time plus the clip's own offsets --
not the window of the GPS event that suggested it. Those differ by an order
of magnitude, and using the event window would both understate the film and
tell `app.journey_gaps` the ride was uncovered while the camera was running.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import unicodedata
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.agents.story_planner import StoryOutputLanguage
from app.analysis_look import AnalysisLookError, looks_for
from app.analysis_ranking import ranks_for
from app.analysis_record import (
    BOUGHT_ANALYSIS_PROVIDERS,
    VIDEO_ANALYSIS_RECORD_FILE_NAME,
    load_video_analysis_record,
)
from app.analysis_screening import halts, measure_stillness
from app.contracts import RoutePoint
from app.ferries import afloat, crossing_distance_m, ferries_or_none, ferry_crossings
from app.fixed_shots import FIXED_SHOT_STILL_S, choose_shots, filmed_moments, fixed_shots_for
from app.footage_candidates import DEFAULT_WINDOW_S, recording_spans
from app.gemini_selection import JudgedCandidate, clears_the_floor, window_moments
from app.gps import parse_gpx
from app.gps.moments import Moment, MomentKind, day_moments
from app.gps.turns import sharp_turns
from app.highlights import HIGHLIGHT_S, pick_highlights
from app.journey_gaps import build_journey_gap_plan
from app.local_pipeline import load_local_pipeline_inputs
from app.map_background import background_or_none, chosen_style_name
from app.place_names import PlaceName, PlaceNames, PlaceNamesError, leg_names, point_at
from app.place_shots import StopPicture, lodging_picture, stop_pictures
from app.places import landmark_crossings, landmarks_or_none, place_passages, places_or_none
from app.portable_package import FILM_SOURCES_DIRECTORY_NAME, film_sources_or_none
from app.private_package_health import (
    BLOCKING_REASONS,
    PrivatePackageHealth,
    check_private_package_health,
)
from app.ride_chapters import (
    STOP_MIN_S,
    build_chapter_timeline,
    chapter_cards,
    day_account,
    long_halts,
    segment_ride,
)
from app.route_references import (
    clear_of_crossings,
    ferry_moments,
    highway_runs,
    is_route_name,
    real_scenic,
    road_moments,
    road_runs,
    scenic_or_none,
)
from app.scenic_routes import (
    ScenicStretch,
    advanced_m,
)
from app.stop_kinds import StopKind, aboard_a_ferry, at_a_ferry
from app.story_film import (
    QUICK_LOOK,
    CardRasteriser,
    FootageSource,
    StoryFilmError,
    StoryFilmResult,
    build_story_film_segments,
    chosen_rasteriser,
    render_story_film,
    write_chapter_cards,
    write_position_maps,
    write_section_strips,
)
from app.story_music import (
    MUSIC_CATALOGUE_FILE_NAME,
    StoryMusicError,
    load_music_catalogue,
    mix_music_into_film,
)
from app.story_opening import frame_the_film
from app.story_pacing import (
    DEFAULT_FOOTAGE_TARGET_S,
    chapter_openers,
    footage_for,
    select_by_chapter,
)
from app.story_package import (
    JOURNEY_STORY_PLAN_FILE_NAME,
    JourneyStoryPlan,
    build_journey_story_plan,
    load_journey_story_plan,
    write_journey_story_plan,
)
from app.story_sections import (
    SectionEvent,
    SectionKind,
    arrival_line,
    attach_sections,
    departure_line,
    ferry_off_line,
    ferry_on_line,
    highway_entries,
    highway_exits,
    pass_line,
    place_line,
    road_line,
    scenic_events,
    stop_line,
    town_in_line,
    town_line,
    with_clock,
)
from app.story_subtitles import build_subtitle_cues, render_srt, render_webvtt
from app.story_timeline import TimelineFootage, build_story_timeline
from app.town_passages import town_passages
from app.trip_days import day_label, local_offset_s, trip_day
from app.video import (
    VideoCatalog,
    VideoMatchStatus,
    evaluate_local_evidence_review,
    load_local_evidence_review,
    load_resolved_candidate_export,
    load_video_catalog,
)

DEFAULT_FILM_FILE_NAME = "ride-storyteller-story-film.mp4"
# Set to "none" to cut a film without asking the place service for names.
PLACE_NAMES_ENV = "RIDE_PLACE_NAMES"
# A stop this long is a stopover said in a section; the long halts cut the legs.
STOPOVER_MIN_S = 5 * 60.0
# Within this long of a leg's ends, its own town is not "passed through", and
# within this long of the day's ends, a short stop is parking, not a stopover.
SECTION_EDGE_S = 15 * 60.0
# The language the place service answers in. Defaults to the film's own
# language; set it to the country's language when the film's would give a
# mixture (a Japanese film of a ride abroad gets katakana for the famous
# places and Latin script for the rest, and a title in both looks wrong).
PLACE_LANGUAGE_ENV = "RIDE_PLACE_LANGUAGE"
DEFAULT_SCORED_FILM_FILE_NAME = "ride-storyteller-story-film-scored.mp4"


class PrivateJourneyFilmError(RuntimeError):
    """Raised when a package cannot be turned into a film."""


@dataclass(frozen=True)
class PrivateJourneyFilmResult:
    """What one run produced, with nothing private in it."""

    health: PrivatePackageHealth
    film: StoryFilmResult
    subtitle_file_names: tuple[str, ...]
    plan_beat_count: int
    plan_total_screen_duration_s: float
    music_attribution: str | None = None
    scored_film_file_name: str | None = None
    map_background: str = "none"
    """Which map the route figures were drawn on: a style name, or "none" for black."""

    def to_dict(self) -> dict[str, object]:
        return {
            "health": self.health.to_dict(),
            "film": self.film.to_dict(),
            "map_background": self.map_background,
            "subtitle_file_names": list(self.subtitle_file_names),
            "music": {
                "scored_film_file_name": self.scored_film_file_name,
                # Carried here so a run's own output shows what must be credited.
                "attribution": self.music_attribution,
            },
            "plan": {
                "beat_count": self.plan_beat_count,
                "total_screen_duration_s": round(self.plan_total_screen_duration_s, 3),
            },
            "local_only": True,
            "external_data_sent": False,
        }


def plan_journey_film(
    package_directory: Path, *, allow_unbought_judgement: bool = False
) -> JourneyStoryPlan:
    """Work out what this package's film is, and write it into the package.

    Only clips that matched a source asset and were confirmed take part.
    Everything else the ride did becomes an uncovered stretch, so the film
    still runs from departure to arrival without claiming footage that does
    not exist.

    When the package carries judgements from Gemini, those decide the film
    outright -- which is the point of buying them -- and the older candidate
    export is not read at all. A package judged from its footage need never
    have one: nothing in the film comes from it.

    A package without judgements behaves exactly as before and uses every
    confirmed clip, so a ride can still be cut when the analysis has not been
    run, or could not be.
    """
    inputs = load_local_pipeline_inputs(package_directory / "local-pipeline-inputs.json")
    catalog = load_video_catalog(package_directory / "local-video-catalog.json")

    judged = _judged_candidates(
        package_directory, catalog, allow_unbought_judgement=allow_unbought_judgement
    )
    # A portable package is cut from the clips it carries and no others, so a
    # re-plan elsewhere cannot reach for footage that was never shipped.
    portable = film_sources_or_none(package_directory)
    if judged is not None and portable is not None:
        shipped = {source.event_id for source in portable}
        judged = tuple(candidate for candidate in judged if candidate.event_id in shipped)
        if not judged:
            raise PrivateJourneyFilmError("the portable package carries no judged window")
    route = parse_gpx(inputs.gpx_path)
    if judged is not None:
        # A judged film has a day with a shape: a few chapters cut where
        # the track says the ride changed, each named from its own evidence
        # and from what the model said about the windows inside it. The
        # film's minutes are then shared out chapter by chapter, and each
        # window is held for a length that fits how the model placed it.
        points = route.points
        ranks = ranks_for(package_directory)
        offset = local_offset_s(package_directory)
        names = _names_or_none(package_directory, inputs.output_language)
        stops = long_halts(points, minimum_s=STOP_MIN_S)
        # The hours on a ferry are the ship's, not the ride's (app.ferries):
        # a chapter of their own, no highway exit as the ship leaves the
        # wharf, and no kilometres on the closing card. The camera must
        # have seen the deck, or it was a road along the water.
        crossings = ferry_crossings(
            points,
            ferries_or_none(),
            witnessed=tuple(c.start_time for c in judged if c.analysis and at_a_ferry(c.analysis)),
            aboard=tuple(c.start_time for c in judged if c.analysis and aboard_a_ferry(c.analysis)),
            halts=stops,
        )
        runs = highway_runs(points)
        # Roads with a name worth saying, from the map and the place service;
        # a signposted route among them is a chapter like a scenic route.
        roads = road_runs(points, names)
        signposted = tuple(r for r in roads if is_route_name(r.route))
        # A scenic route's end that falls in the middle of a highway run is
        # the reference's edge, not the ride's: it neither cuts nor speaks.
        stretches = real_scenic(
            tuple(sorted((*scenic_or_none(points), *signposted), key=lambda r: r.start_time)),
            runs,
        )
        stretches = tuple(s for s in stretches if not afloat(crossings, s.start_time))
        chapters = segment_ride(
            points, hints=_chapter_hints(judged), scenic=stretches, ferries=crossings
        )
        looks = _looks_or_none(package_directory, tuple(c.event_id for c in judged))
        moments = window_moments(judged, sharp_turns(points))
        # The moments the track proves -- setting off, each stop's two ends,
        # joining and leaving a highway, riding off the ferry, arriving --
        # are kept whatever they scored (app.fixed_shots).
        proven = filmed_moments(
            (
                *day_moments(points, stops),
                *clear_of_crossings(road_moments(points, runs), crossings),
                *ferry_moments(points, crossings),
            ),
            recording_spans(catalog),
            window_s=DEFAULT_WINDOW_S,
            points=points,
        )
        # Each moment bought a fan of windows; the model's answers -- setting
        # off, pulling in, standing still -- choose the one that shows it.
        fixed = choose_shots(
            fixed_shots_for(judged, proven, window_s=DEFAULT_WINDOW_S),
            judged,
            window_s=DEFAULT_WINDOW_S,
        )
        # Every stop gets what it was and one picture of its place (the
        # owner, 2026-09-07: the fuel station, the museum's outside, the
        # lunch place), and the day's ends a picture of the lodging.
        pictures = stop_pictures(judged, stops, taken=fixed, local_offset_s=offset)
        places = tuple(p.event_id for p in pictures if p.event_id is not None)
        lodging = _lodging_shots(judged, proven, taken={*fixed, *places})
        pinned = frozenset(fixed) | frozenset(places) | frozenset(lodging)
        # Before the ride sets off and after it comes to rest there is no
        # ride to show: a bike standing at the lodging is not the day (the
        # owner's day-1 note). Only the pinned shots may sit there.
        candidates = _within_the_ride(judged, proven, pinned)
        # The opening's four pictures are chosen among the whole day first
        # and kept: a window worth the opening is worth its chapter.
        highlights = pick_highlights(
            tuple(c for c in candidates if clears_the_floor(c)),
            ride_start=points[0].timestamp,
            ride_end=points[-1].timestamp,
        )
        required = pinned | frozenset(h.event_id for h in highlights)
        chosen = select_by_chapter(
            candidates,
            chapters,
            ranks=ranks,
            looks=looks,
            moments=moments,
            required=required,
            # The moments, the places and the lodging may show a car park or
            # a bike at rest; nothing else in the film may.
            parked_allowed=pinned,
            fixed=pinned,
        )
        if not chosen:
            raise PrivateJourneyFilmError(
                "the judgement rejected every window; nothing would be shown"
            )
        # The chosen windows' looks decide their holds and which half plays
        # (E-2); the series is measured only for the chosen, once.
        detailed = _looks_or_none(package_directory, tuple(chosen), need_series=True)
        if looks is not None and detailed is not None:
            looks = {**looks, **detailed}
        footage = footage_for(
            chosen,
            judged,
            ranks=ranks,
            looks=looks,
            openers=chapter_openers(chosen, judged, chapters),
            footage_target_s=DEFAULT_FOOTAGE_TARGET_S,
            fixed=pinned,
        )
        timeline = build_chapter_timeline(chapters, tuple(footage), points)
        # Where each leg went from and to, asked of the place service and
        # kept in the package; a film without names is still a film.
        named = _leg_names_or_none(package_directory, points, chapters, inputs.output_language)
        cards = chapter_cards(chapters, output_language=inputs.output_language, names=named)
        plan = build_journey_story_plan(
            timeline, output_language=inputs.output_language, cards=cards
        )
        # Four highlights first, the chapters full-screen, the day's account
        # last -- labelled with the day on a trip of several (2026-09-07).
        distance_m, duration_s, gain_m, loss_m = day_account(points)
        distance_m = max(0.0, distance_m - crossing_distance_m(points, crossings))
        plan = frame_the_film(
            plan,
            preference=_window_preference(package_directory, judged),
            distance_m=distance_m,
            duration_s=duration_s,
            elevation_gain_m=gain_m,
            elevation_loss_m=loss_m,
            from_to=(named[0][0].place, named[-1][1].place) if named else None,
            route_chain=_route_chain(named),
            label=day_label(trip_day(package_directory, local_offset=offset)),
            highlight_ids=tuple(h.event_id for h in highlights),
            highlight_s=HIGHLIGHT_S,
        )
        # The story's turns -- setting off, a town, off the highway, onto a
        # scenic route, a named road, a pass, the ferry, each stop and what
        # it was, arriving -- said with the local time in the lower third
        # of the nearest window (点 8, 9).
        plan = attach_sections(
            plan,
            _section_events(
                package_directory,
                points,
                chapters,
                judged,
                stretches,
                named,
                proven,
                offset,
                crossings=crossings,
                pictures=pictures,
                roads=roads,
                by_id={c.event_id: c for c in judged},
            ),
            {item.event_id: item.start_time for item in footage},
            within_by_kind=SECTION_REACH_S,
        )
    else:
        footage = _confirmed_clip_footage(package_directory, catalog)
        if not footage:
            raise PrivateJourneyFilmError("no confirmed clip is available for the film")
        footage.sort(key=lambda item: item.start_time)
        covered = tuple((item.start_time, item.end_time) for item in footage)
        timeline = build_story_timeline(
            tuple(footage), build_journey_gap_plan(route.points, covered)
        )
        plan = build_journey_story_plan(timeline, output_language=inputs.output_language)
    write_journey_story_plan(package_directory / JOURNEY_STORY_PLAN_FILE_NAME, plan)
    return plan


def _section_events(
    package_directory: Path,
    points: tuple[RoutePoint, ...],
    chapters: tuple,
    judged: tuple[JudgedCandidate, ...],
    stretches: tuple[ScenicStretch, ...],
    named: list[tuple[PlaceName, PlaceName]] | None,
    proven: tuple[Moment, ...] = (),
    local_offset: float | None = None,
    *,
    crossings: Sequence = (),
    pictures: Sequence[StopPicture] = (),
    roads: Sequence[ScenicStretch] = (),
    by_id: Mapping[str, JudgedCandidate] | None = None,
) -> tuple[SectionEvent, ...]:
    """Every section of the day the track and the references prove, with its line."""
    language = load_local_pipeline_inputs(
        package_directory / "local-pipeline-inputs.json"
    ).output_language
    ride_start, ride_end = points[0].timestamp, points[-1].timestamp
    edge = timedelta(seconds=SECTION_EDGE_S)
    names = _names_or_none(package_directory, language)
    windows = by_id or {c.event_id: c for c in judged}

    def leg_of(when: datetime) -> int | None:
        for index, chapter in enumerate(chapters):
            if chapter.start_time <= when < chapter.end_time:
                return index
        return None

    def name_at(when: datetime) -> PlaceName:
        if names is None:
            return PlaceName(place=None, road=None)
        point = point_at(points, when)
        try:
            return names.name_at(point.latitude, point.longitude)
        except PlaceNamesError:
            return PlaceName(place=None, road=None)

    def near_a_ship(when: datetime) -> bool:
        return afloat(crossings, when, slack_s=SHIP_EDGE_S)

    events: list[SectionEvent] = [
        e
        for e in scenic_events(
            stretches, ride_start=ride_start, ride_end=ride_end, language=language
        )
        if not near_a_ship(e.at)
    ]
    runs = highway_runs(points)
    advanced = lambda since, until: advanced_m(points, since, until)  # noqa: E731
    events.extend(
        e
        for e in highway_entries(runs, ride_start=ride_start, language=language, advanced=advanced)
        if not near_a_ship(e.at)
    )
    # Setting off, arriving, riding off the ferry: on their own shots, with the place.
    for moment in proven:
        if moment.kind is MomentKind.DEPARTURE:
            place = named[0][0].place if named else None
            events.append(
                SectionEvent(SectionKind.DEPARTURE, moment.at, departure_line(place, language))
            )
        elif moment.kind is MomentKind.ARRIVAL:
            place = named[-1][1].place if named else None
            events.append(
                SectionEvent(SectionKind.ARRIVAL, moment.at, arrival_line(place, language))
            )
        elif moment.kind is MomentKind.FERRY_OFF:
            events.append(
                SectionEvent(
                    SectionKind.FERRY_OFF,
                    moment.at,
                    ferry_off_line(name_at(moment.at).place, language),
                )
            )
    # Off the highway, toward the end of the leg the ride was in.
    toward: dict[datetime, str | None] = {}
    for run in runs:
        for index, chapter in enumerate(chapters):
            if chapter.start_time <= run.end_time < chapter.end_time:
                toward[run.end_time] = named[index][1].place if named else None
    events.extend(
        e
        for e in highway_exits(
            runs, ride_end=ride_end, toward=toward, language=language, advanced=advanced
        )
        if not near_a_ship(e.at)
    )
    # A road with a name worth saying, once, as the ride gets onto it.
    for run in roads:
        if not is_route_name(run.route) and not near_a_ship(run.start_time):
            events.append(
                SectionEvent(SectionKind.ROAD, run.start_time, road_line(run.route, language))
            )
    # A pass the ride crossed.
    for crossing in landmark_crossings(points, landmarks_or_none()):
        events.append(
            SectionEvent(
                SectionKind.PASS,
                crossing.at,
                pass_line(crossing.name, crossing.elevation_m, language),
            )
        )
    # The ferry: boarding, said on the picture of the terminal, and setting sail.
    for crossing in crossings:
        boarding = next(
            (
                p
                for p in pictures
                if p.kind is StopKind.FERRY
                and p.start_time <= crossing.end_time
                and p.end_time >= crossing.start_time - edge
            ),
            None,
        )
        line = ferry_on_line(crossing.name, language)
        if boarding is not None and boarding.event_id in windows:
            events.append(
                SectionEvent(SectionKind.FERRY_ON, windows[boarding.event_id].start_time, line)
            )
        else:
            events.append(SectionEvent(SectionKind.FERRY_ON, crossing.start_time, line))
    # A town the ride came through, said as it enters -- not the town a leg
    # starts from or ends in, which its title already says -- and "into"
    # the town when the ride stops in it (the owner, 2026-09-07).
    halts = [(p.start_time, p.end_time) for p in pictures]
    events.extend(
        _town_events(points, judged, chapters, named, halts, name_at, language, near_a_ship)
    )
    # Each stop, said as the ride pulls in, by what it was; its spot's name
    # on the picture of the place. Not at the day's own ends, where the
    # ride is only parking, and not the ferry's, which is said above.
    for picture in pictures:
        if picture.start_time < ride_start + edge or picture.start_time > ride_end - edge:
            continue
        if picture.kind in (StopKind.FERRY, StopKind.RESIDENCE):
            # The ferry says itself, above; a home is never said at all. A
            # lodging in the middle of the day is a stop like any other --
            # only the day's two ends are the rider checking in or out, and
            # the edge check above has already dropped those.
            continue
        minutes = int((picture.end_time - picture.start_time).total_seconds() // 60)
        here = name_at(picture.start_time)
        where = here.place
        if picture.kind in _NAMED_STOPS:
            where = picture.spot or here.finer
        events.append(
            SectionEvent(
                SectionKind.HALT_PLACE,
                picture.start_time,
                stop_line(picture.kind, where, minutes, language),
            )
        )
        if picture.spot and not _same_name(picture.spot, where) and picture.event_id in windows:
            events.append(
                SectionEvent(
                    SectionKind.PLACE,
                    windows[picture.event_id].start_time,
                    place_line(picture.spot, language),
                )
            )
    events = _merge_coincident(events, language)
    # Every line carries the local time (点 9).
    clocked = [SectionEvent(e.kind, e.at, with_clock(e.text, e.at, local_offset)) for e in events]
    return tuple(sorted(clocked, key=lambda e: e.at))


# The stops whose line names the spot rather than the town: a museum, a
# lookout, a lunch place. Fuel and a break are said with the town.
_NAMED_STOPS = frozenset(
    {StopKind.ATTRACTION, StopKind.LOOKOUT, StopKind.LUNCH, StopKind.MEAL, StopKind.STOPOVER}
)
# Highway and route lines this close to a ferry's ends are the ship's doing.
SHIP_EDGE_S = 20 * 60.0
# How long a line may wait for a window. A town's name goes stale as the
# ride leaves it; a turn off the highway does not (the owner, 2026-09-07).
SECTION_REACH_S: dict[SectionKind, float] = {
    SectionKind.TOWN: 5 * 60.0,
    SectionKind.TOWN_IN: 5 * 60.0,
    SectionKind.PASS: 5 * 60.0,
    SectionKind.PLACE: 3 * 60.0,
    SectionKind.HALT_PLACE: 8 * 60.0,
    SectionKind.ROAD: 8 * 60.0,
}


def _same_name(one: str | None, other: str | None) -> bool:
    """Whether two names are the same place, ignoring case and accents."""
    if not one or not other:
        return False

    def plain(text: str) -> str:
        stripped = "".join(
            ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
        )
        return " ".join(stripped.casefold().split())

    return plain(one) == plain(other)


# A village is said only when no town was said for this long before it.
VILLAGE_QUIET_S = 30 * 60.0
# Two lines this close about the same turn are one line.
COINCIDENT_S = 120.0
_PLACE_ORDER = {"city": 0, "town": 1, "village": 2}


def _town_events(
    points: tuple[RoutePoint, ...],
    judged: tuple[JudgedCandidate, ...],
    chapters: tuple,
    named: list[tuple[PlaceName, PlaceName]] | None,
    halts: Sequence[tuple[datetime, datetime]],
    name_at: Callable[[datetime], PlaceName],
    language: StoryOutputLanguage,
    near_a_ship: Callable[[datetime], bool],
) -> list[SectionEvent]:
    """The towns the ride came through, from the places reference, else from the track's pace."""
    ride_start, ride_end = points[0].timestamp, points[-1].timestamp
    edge = timedelta(seconds=SECTION_EDGE_S)

    def leg_of(when: datetime) -> int | None:
        for index, chapter in enumerate(chapters):
            if chapter.start_time <= when < chapter.end_time:
                return index
        return None

    def says_it_already(town: str, when: datetime) -> bool:
        leg = leg_of(when)
        if leg is None or named is None or leg >= len(named):
            return False
        return town in (named[leg][0].place, named[leg][1].place)

    events: list[SectionEvent] = []
    passages = place_passages(points, places_or_none())
    if not passages:
        for passage in town_passages(points, _chapter_hints(judged), halts=halts):
            town = name_at(passage.middle).place
            if not town or says_it_already(town, passage.middle) or near_a_ship(passage.middle):
                continue
            events.append(
                SectionEvent(SectionKind.TOWN, passage.start_time, town_line(town, language))
            )
        return events
    last_said: datetime | None = None
    for passage in passages:
        at = passage.start_time
        if at < ride_start + edge or at > ride_end - edge or near_a_ship(at):
            continue
        # A suburb inside a city is the city's passage.
        if any(
            _PLACE_ORDER.get(o.kind, 9) < _PLACE_ORDER.get(passage.kind, 9)
            and o.start_time <= passage.end_time
            and passage.start_time <= o.end_time
            for o in passages
        ):
            continue
        if passage.kind == "village" and (
            last_said is not None and (at - last_said).total_seconds() < VILLAGE_QUIET_S
        ):
            continue
        if says_it_already(passage.name, passage.middle):
            last_said = at
            continue
        stops_here = any(passage.start_time <= s <= passage.end_time for s, _ in halts)
        line = (
            town_in_line(passage.name, language)
            if stops_here
            else town_line(passage.name, language)
        )
        kind = SectionKind.TOWN_IN if stops_here else SectionKind.TOWN
        events.append(SectionEvent(kind, at, line))
        last_said = at
    return events


def _merge_coincident(
    events: list[SectionEvent], language: StoryOutputLanguage
) -> list[SectionEvent]:
    """One line where two say the same turn: the route's name wins over the highway's.

    The owner's day-3 note (2026-09-07): leaving a named route and leaving
    the highway it runs along fired a few seconds apart, saying the same
    moment twice, and neither line said where the ride was going. The
    route's line keeps the highway line's destination.
    """
    close = timedelta(seconds=COINCIDENT_S)
    dropped: set[int] = set()
    merged = list(events)
    for i, scenic in enumerate(events):
        if scenic.kind not in (SectionKind.SCENIC_IN, SectionKind.SCENIC_OUT):
            continue
        for j, road in enumerate(events):
            if j in dropped or road.kind not in (SectionKind.HIGHWAY_ON, SectionKind.HIGHWAY_OFF):
                continue
            if abs(road.at - scenic.at) > close:
                continue
            dropped.add(j)
            if scenic.kind is SectionKind.SCENIC_OUT and road.kind is SectionKind.HIGHWAY_OFF:
                toward = _destination_of(road.text, language)
                if toward:
                    text = scenic.text + (
                        f"、{toward}へ" if _japanese(language) else f", toward {toward}"
                    )
                    merged[i] = SectionEvent(scenic.kind, scenic.at, text)
    return [e for k, e in enumerate(merged) if k not in dropped]


def _japanese(language: StoryOutputLanguage) -> bool:
    return language is StoryOutputLanguage.JAPANESE


def _destination_of(highway_off_text: str, language: StoryOutputLanguage) -> str | None:
    """The place a highway-exit line points at, if it names one."""
    if _japanese(language):
        head, sep, tail = highway_off_text.rpartition("、")
        return tail[:-1] if sep and tail.endswith("へ") else None
    head, sep, tail = highway_off_text.partition(", toward ")
    return tail or None


def _names_or_none(package_directory: Path, output_language: StoryOutputLanguage):
    if os.environ.get(PLACE_NAMES_ENV, "").strip().lower() == "none":
        return None
    language = os.environ.get(PLACE_LANGUAGE_ENV, "").strip().lower() or (
        "ja" if output_language is StoryOutputLanguage.JAPANESE else "en"
    )
    try:
        return PlaceNames(package_directory, language=language)
    except PlaceNamesError:
        return None


def _route_chain(named: list[tuple[PlaceName, PlaceName]] | None) -> tuple[str, ...]:
    """Every named place the legs passed, in order, for the closing card."""
    if not named:
        return ()
    places: list[str] = []
    for start, end in named:
        for place in (start.place, end.place):
            if place:
                places.append(place)
    return tuple(places)


def _within_the_ride(
    judged: tuple[JudgedCandidate, ...],
    proven: tuple[Moment, ...],
    pinned: Collection[str],
) -> tuple[JudgedCandidate, ...]:
    """The windows between setting off and coming to rest, plus the pinned shots."""
    began = next((m.at for m in proven if m.kind is MomentKind.DEPARTURE), None)
    ended = next((m.at for m in proven if m.kind is MomentKind.ARRIVAL), None)
    slack = timedelta(seconds=FIXED_SHOT_STILL_S)
    kept = []
    for candidate in judged:
        if candidate.event_id in pinned:
            kept.append(candidate)
            continue
        if began is not None and candidate.start_time < began - slack:
            continue
        if ended is not None and candidate.start_time > ended:
            continue
        kept.append(candidate)
    return tuple(kept)


def _lodging_shots(
    judged: tuple[JudgedCandidate, ...], proven: tuple[Moment, ...], taken: Collection[str]
) -> tuple[str, ...]:
    """The lodging before the day's departure and after its arrival, where the camera saw it."""
    shots: list[str] = []
    for moment in proven:
        if moment.kind is MomentKind.DEPARTURE:
            found = lodging_picture(judged, at=moment.at, after=False, taken=taken)
        elif moment.kind is MomentKind.ARRIVAL:
            found = lodging_picture(judged, at=moment.at, after=True, taken=taken)
        else:
            continue
        if found is not None and found not in shots:
            shots.append(found)
    return tuple(shots)


def _leg_names_or_none(
    package_directory: Path,
    points: tuple,
    chapters: tuple,
    output_language: StoryOutputLanguage,
) -> list[tuple[PlaceName, PlaceName]] | None:
    """Each leg's two ends named, or None when the place service cannot be asked.

    No key, a refusal, an unreachable service: the cards keep the titles
    the track alone allows. Nothing about a missing name stops the film.
    """
    if os.environ.get(PLACE_NAMES_ENV, "").strip().lower() == "none":
        return None
    language = os.environ.get(PLACE_LANGUAGE_ENV, "").strip().lower() or (
        "ja" if output_language is StoryOutputLanguage.JAPANESE else "en"
    )
    try:
        names = PlaceNames(package_directory, language=language)
        return leg_names(names, points, [(c.start_time, c.end_time) for c in chapters])
    except PlaceNamesError:
        return None


def _window_preference(
    package_directory: Path, judged: tuple[JudgedCandidate, ...]
) -> dict[str, float]:
    """Which window to open on: the model's rank, else its score, lower first.

    A window from a halt never opens the film. On the real second day the
    model's first-ranked window was a museum exhibit, and a film of a ride
    that opens indoors opens on the wrong thing however well it scored;
    the ride is what the viewer came for. Halted windows are pushed behind
    every moving one and can still open a film that has nothing else.
    """
    ranks = ranks_for(package_directory) or {}
    preference: dict[str, float] = {}
    for candidate in judged:
        rank = ranks.get(candidate.event_id)
        order = float(rank) if rank is not None else 1000.0 + (1.0 - candidate.score())
        if candidate.halt is not None:
            order += 10_000.0
        preference[candidate.event_id] = order
    return preference


def _looks_or_none(
    package_directory: Path, event_ids: tuple[str, ...], *, need_series: bool = False
) -> dict | None:
    """The windows' looks, or None when the copies cannot be read.

    A look is a refinement of the selection, not a condition of it: a
    package whose copies are gone, or a machine without FFmpeg, still gets
    its film, cut as it was before looks existed.
    """
    try:
        return looks_for(package_directory, event_ids, need_series=need_series)
    except AnalysisLookError:
        return None


def _chapter_hints(judged: tuple[JudgedCandidate, ...]) -> dict[datetime, str]:
    """The model's words about every judged window, keyed by ride time.

    Every window the judgement saw counts, not only the adopted ones: a
    chapter is named for what the ride was like there, and the model looked
    at all of it.
    """
    hints: dict[datetime, str] = {}
    for candidate in judged:
        analysis = candidate.analysis
        if analysis is None:
            continue
        hints[candidate.start_time] = " ".join(
            (analysis.road_type, " ".join(analysis.scenery_tags), analysis.visual_description)
        )
    return hints


def _confirmed_clip_footage(
    package_directory: Path, catalog: VideoCatalog
) -> list[TimelineFootage]:
    """The confirmed clips, for a package nobody has paid to judge."""
    clips = load_resolved_candidate_export(package_directory / "ride-storyteller-candidates.json")
    review = load_local_evidence_review(package_directory / "evidence-review.json")
    confirmed = set(evaluate_local_evidence_review(clips, review).confirmed_event_ids)

    asset_starts = {entry.asset_id: entry.recorded_start_time for entry in catalog.entries}
    footage: list[TimelineFootage] = []
    for clip in clips:
        if clip.event_id not in confirmed or clip.status is not VideoMatchStatus.MATCHED:
            continue
        if clip.asset_id is None or clip.start_offset_s is None or clip.end_offset_s is None:
            raise PrivateJourneyFilmError("a confirmed clip is missing its source window")
        start = asset_starts.get(clip.asset_id)
        if start is None:
            raise PrivateJourneyFilmError("a confirmed clip names an asset the catalog lacks")
        # The camera's clock shifted onto GPS time, then the clip's own window.
        base = start + timedelta(seconds=catalog.video_to_gps_offset_s)
        footage.append(
            TimelineFootage(
                event_id=clip.event_id,
                start_time=base + timedelta(seconds=clip.start_offset_s),
                end_time=base + timedelta(seconds=clip.end_offset_s),
            )
        )
    return footage


def write_subtitle_files(
    package_directory: Path, plan: JourneyStoryPlan, *, film_file_name: str
) -> tuple[str, ...]:
    """Write the film's subtitles beside it, named to match so players pair them."""
    stem = Path(film_file_name).stem
    cues = build_subtitle_cues(plan)
    written: list[str] = []
    for suffix, render in ((".srt", render_srt), (".vtt", render_webvtt)):
        path = package_directory / f"{stem}{suffix}"
        if path.is_symlink():
            raise PrivateJourneyFilmError("a subtitle output path is unsafe")
        path.write_text(render(cues), encoding="utf-8")
        written.append(path.name)
    return tuple(written)


def run_private_journey_film(
    package_directory: Path,
    *,
    output_file_name: str = DEFAULT_FILM_FILE_NAME,
    overwrite: bool = False,
    rasteriser: CardRasteriser = QUICK_LOOK,
    music_track_id: str | None = None,
    music_directory: Path | None = None,
    card_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    film_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    music_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    map_style: str | None = None,
    map_fetch: Callable[[str], bytes] | None = None,
) -> PrivateJourneyFilmResult:
    """Take one reviewed package all the way to a film and its subtitles.

    Gate 1 is binding and is asked once. It used to be asked twice, because
    one of its questions -- is the film long enough -- was not a fact about
    the package until the film had a shape. The 2026-09-03 design review
    removed that question: the film's length follows its material. What is
    left is settled evidence, which is true of a package as it stands.
    """
    health = check_private_package_health(package_directory)
    if not health.is_ready:
        raise PrivateJourneyFilmError(
            "the package is not ready to render: "
            + ", ".join(sorted(set(health.blocking_reasons) & BLOCKING_REASONS))
        )

    plan = plan_journey_film(package_directory)
    route = parse_gpx(
        load_local_pipeline_inputs(package_directory / "local-pipeline-inputs.json").gpx_path
    )
    # A real map behind every route figure when one can be had (E-10); the
    # centre and zoom of the ride's bounds are all that leaves the machine.
    background = background_or_none(
        package_directory, route.points, style_name=map_style, fetch=map_fetch
    )
    # The corner map is a fifth of the frame high: place names there are
    # noise, so it takes the same map without text.
    corner_background = (
        background_or_none(package_directory, route.points, style_name="plain", fetch=map_fetch)
        if background is not None
        else None
    )
    rasters = write_chapter_cards(
        plan,
        package_directory,
        route_points=route.points,
        rasteriser=rasteriser,
        runner=card_runner,
        background=background,
    )
    # Where the ride is, in the corner of every clip (E-9).
    position_maps = write_position_maps(
        plan,
        package_directory,
        route_points=route.points,
        ride_times=_ride_times(package_directory),
        rasteriser=rasteriser,
        runner=card_runner,
        background=corner_background,
    )
    # The sections' one-line strips (点 8).
    section_strips = write_section_strips(
        plan, package_directory, rasteriser=rasteriser, runner=card_runner
    )
    segments = build_story_film_segments(
        plan,
        rasters,
        _confirmed_footage_sources(package_directory),
        position_maps=position_maps,
        section_strips=section_strips,
    )
    film = render_story_film(
        segments,
        package_directory / output_file_name,
        overwrite=overwrite,
        runner=film_runner,
    )
    subtitles = write_subtitle_files(package_directory, plan, film_file_name=output_file_name)

    attribution: str | None = None
    scored_name: str | None = None
    if music_track_id is not None:
        track = _catalogue_track(music_directory, music_track_id)
        directory = music_directory
        scored = mix_music_into_film(
            package_directory / output_file_name,
            track,
            directory,
            package_directory / DEFAULT_SCORED_FILM_FILE_NAME,
            film_duration_s=film.duration_s,
            overwrite=overwrite,
            runner=music_runner,
        )
        attribution = track.attribution
        scored_name = scored.name

    return PrivateJourneyFilmResult(
        health=health,
        film=film,
        subtitle_file_names=subtitles,
        plan_beat_count=len(plan.beats),
        plan_total_screen_duration_s=plan.total_screen_duration_s,
        map_background=(map_style or chosen_style_name()) if background is not None else "none",
        music_attribution=attribution,
        scored_film_file_name=scored_name,
    )


def _judged_candidates(
    package_directory: Path,
    catalog: VideoCatalog,
    *,
    allow_unbought_judgement: bool = False,
) -> tuple[JudgedCandidate, ...] | None:
    """The windows Gemini judged worth using, or nothing if none were judged.

    A judgement is about windows of footage, which is a wider set than the
    clips GPS events happened to fall inside, so when one exists it replaces
    that set rather than filtering it. Returning `None` says there is no
    judgement here and the caller should fall back to the confirmed clips.

    A record that cannot be read is an error rather than a silent fallback:
    falling back would cut a different film from the one that was paid to be
    judged, and nobody would see it happen.

    A record has to say a real model made it. Dry runs put a stub in
    Gemini's place -- that is how this path is exercised without spending --
    and a stub's judgement is written to the same file, in the same shape,
    and produces a film that looks exactly like a bought one. A film is
    shown to people as evidence of what the model saw; one cut from invented
    scores is not that, and nothing downstream could tell the difference.
    So an unbought judgement is refused unless a caller says plainly that it
    wants one.
    """
    record_path = package_directory / VIDEO_ANALYSIS_RECORD_FILE_NAME
    if not record_path.exists():
        return None
    record = load_video_analysis_record(record_path)
    if not allow_unbought_judgement:
        invented = {
            item.analysis.analysis_provider
            for item in record.analysed
            if item.analysis.analysis_provider not in BOUGHT_ANALYSIS_PROVIDERS
        }
        if invented:
            raise PrivateJourneyFilmError(
                "this judgement was not bought from a model, so a film from it "
                "would show invented scores as evidence; "
                "pass allow_unbought_judgement to build one anyway"
            )
    shift = timedelta(seconds=catalog.video_to_gps_offset_s)
    asset_starts = {entry.asset_id: entry.recorded_start_time for entry in catalog.entries}
    # Where the ride stood still, off the track: a place is shown once.
    halted = halts(measure_stillness(package_directory))

    judged: list[JudgedCandidate] = []
    for item in record.analysed:
        start = asset_starts.get(item.analysis.asset_id)
        if start is None:
            raise PrivateJourneyFilmError("a judged window names an asset the catalog lacks")
        base = start + shift
        window = TimelineFootage(
            event_id=item.event_id,
            start_time=base + timedelta(seconds=item.analysis.start_offset_s),
            end_time=base + timedelta(seconds=item.analysis.end_offset_s),
        )
        judged.append(
            JudgedCandidate(
                event_id=item.event_id,
                start_time=window.start_time,
                duration_s=(window.end_time - window.start_time).total_seconds(),
                analysis=item.analysis,
                halt=halted.get(item.event_id),
            )
        )

    return tuple(judged)


def _catalogue_track(music_directory: Path | None, track_id: str):
    """Find the chosen track, refusing to guess where the music lives.

    The music library belongs to the installation, not to any one ride, so
    there is no reliable way to derive its path from a package's. Guessing
    produced a wrong directory and a confusing "catalogue unavailable" after
    a five-minute render had already succeeded.
    """
    if music_directory is None:
        raise PrivateJourneyFilmError(
            "scoring the film needs the directory the music library lives in"
        )
    return load_music_catalogue(music_directory / MUSIC_CATALOGUE_FILE_NAME).track(track_id)


def score_existing_film(
    package_directory: Path,
    music_directory: Path,
    track_id: str,
    *,
    film_file_name: str = DEFAULT_FILM_FILE_NAME,
    overwrite: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, str]:
    """Put music under a film that has already been cut.

    Trying a different track should not mean re-encoding the picture: the
    cut has not changed, and the mix copies the video stream anyway. Returns
    the scored film's name and the credit line the track requires.
    """
    film_path = package_directory / film_file_name
    if film_path.is_symlink() or not film_path.is_file():
        raise PrivateJourneyFilmError("there is no cut film here to score")
    plan = load_journey_story_plan(package_directory / JOURNEY_STORY_PLAN_FILE_NAME)
    track = _catalogue_track(music_directory, track_id)
    scored = mix_music_into_film(
        film_path,
        track,
        music_directory,
        package_directory / DEFAULT_SCORED_FILM_FILE_NAME,
        film_duration_s=plan.total_screen_duration_s,
        overwrite=overwrite,
        runner=runner,
    )
    return scored.name, track.attribution


def _confirmed_footage_sources(package_directory: Path) -> dict[str, FootageSource]:
    """Find the recording and window behind every confirmed event.

    The film is cut from the ride's own footage, not from the 720p proxies in
    `review-clips`. Those exist so a person can watch a candidate in a
    browser; they are a ninth of the source's pixels, and since the
    2026-09-01 decision nobody has to watch them for a clip to be confirmed.
    What identifies a clip is its event and its window, and both survive
    going back to the original file.
    """
    inputs = load_local_pipeline_inputs(package_directory / "local-pipeline-inputs.json")
    catalog = load_video_catalog(package_directory / "local-video-catalog.json")
    file_names = {entry.asset_id: entry.file_name for entry in catalog.entries}

    # A portable package carries one small clip per window instead of the
    # recordings (app.portable_package), because a day of those is 56.6 GiB
    # and has not been looked at. Its map is also the allow-list: nothing
    # outside it can be cut, on this machine or anyone else's.
    portable = film_sources_or_none(package_directory)
    if portable is not None:
        clips = package_directory / FILM_SOURCES_DIRECTORY_NAME
        sources: dict[str, FootageSource] = {}
        for source in portable:
            path = clips / source.file_name
            if not path.is_file() or path.is_symlink():
                raise PrivateJourneyFilmError("a portable package is missing one of its clips")
            sources[source.event_id] = FootageSource(path=path, start_s=source.start_s)
        return sources

    # A judged package's film is cut from the windows that were judged, so
    # that is where its sources come from too. Reading them from the older
    # candidate export would look up clips the plan no longer names.
    record_path = package_directory / VIDEO_ANALYSIS_RECORD_FILE_NAME
    if record_path.exists():
        sources: dict[str, FootageSource] = {}
        for item in load_video_analysis_record(record_path).analysed:
            file_name = file_names.get(item.analysis.asset_id)
            if file_name is None:
                raise PrivateJourneyFilmError("a judged window names an asset the catalog lacks")
            sources[item.event_id] = FootageSource(
                path=_source_recording(inputs.video_root, file_name),
                start_s=item.analysis.start_offset_s,
            )
        return sources

    clips = load_resolved_candidate_export(package_directory / "ride-storyteller-candidates.json")
    review = load_local_evidence_review(package_directory / "evidence-review.json")
    confirmed = set(evaluate_local_evidence_review(clips, review).confirmed_event_ids)
    sources: dict[str, FootageSource] = {}
    for clip in clips:
        if clip.event_id not in confirmed or clip.status is not VideoMatchStatus.MATCHED:
            continue
        if clip.asset_id is None or clip.start_offset_s is None:
            raise PrivateJourneyFilmError("a confirmed clip is missing its source window")
        file_name = file_names.get(clip.asset_id)
        if file_name is None:
            raise PrivateJourneyFilmError("a confirmed clip names an asset the catalog lacks")
        path = _source_recording(inputs.video_root, file_name)
        sources[clip.event_id] = FootageSource(path=path, start_s=clip.start_offset_s)
    return sources


def _ride_times(package_directory: Path) -> dict[str, datetime]:
    """When, on the ride's own clock, each judged window begins.

    The recording's start on the camera's clock, corrected by the confirmed
    offset, plus the window's offset in the recording. Only judged packages
    have this; an unjudged one gets no corner maps.
    """
    record_path = package_directory / VIDEO_ANALYSIS_RECORD_FILE_NAME
    if not record_path.exists():
        return {}
    catalog = load_video_catalog(package_directory / "local-video-catalog.json")
    shift = timedelta(seconds=catalog.video_to_gps_offset_s)
    starts = {entry.asset_id: entry.recorded_start_time + shift for entry in catalog.entries}
    times: dict[str, datetime] = {}
    for item in load_video_analysis_record(record_path).analysed:
        start = starts.get(item.analysis.asset_id)
        if start is not None:
            times[item.event_id] = start + timedelta(seconds=item.analysis.start_offset_s)
    return times


def _source_recording(video_root: Path, file_name: str) -> Path:
    """Find one catalogued recording under the ride's own video directory."""
    if Path(file_name).name != file_name:
        raise PrivateJourneyFilmError("a catalogued recording name must not be a path")
    for candidate in video_root.rglob(file_name):
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise PrivateJourneyFilmError("a catalogued recording is no longer where it was")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Make one private Ride Storyteller film, with chapter cards and "
            "subtitles, from one reviewed package. Local only."
        )
    )
    parser.add_argument("package", type=Path, help="private local pipeline package")
    parser.add_argument("--output-file-name", default=DEFAULT_FILM_FILE_NAME)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--cards",
        choices=("auto", "quick-look", "chromium"),
        default="auto",
        help="what draws the chapter cards; auto is Quick Look on macOS and Chromium elsewhere",
    )
    parser.add_argument(
        "--music",
        dest="music_track_id",
        help="track ID from the music catalogue to score the film with",
    )
    parser.add_argument(
        "--music-directory",
        type=Path,
        default=Path("private-media/music"),
        help="directory holding the music library and its catalogue",
    )
    parser.add_argument(
        "--music-only",
        action="store_true",
        help="score the film already cut here instead of cutting it again",
    )
    parser.add_argument(
        "--map-style",
        choices=("labels", "plain", "none"),
        default=None,
        help=(
            "the map behind the route figures: towns named, no text, or black; "
            "defaults to RIDE_MAP_STYLE or labels"
        ),
    )
    args = parser.parse_args()
    try:
        if args.music_only:
            if args.music_track_id is None:
                raise SystemExit("--music-only needs --music to say which track")
            scored_name, attribution = score_existing_film(
                args.package,
                args.music_directory,
                args.music_track_id,
                film_file_name=args.output_file_name,
                overwrite=args.overwrite,
            )
            print(
                json.dumps(
                    {
                        "scored_film_file_name": scored_name,
                        "attribution": attribution,
                        "local_only": True,
                        "external_data_sent": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        cards = (
            chosen_rasteriser()
            if args.cards == "auto"
            else chosen_rasteriser(environ={"RIDE_CARD_RASTERISER": args.cards})
        )
        result = run_private_journey_film(
            args.package,
            output_file_name=args.output_file_name,
            overwrite=args.overwrite,
            music_track_id=args.music_track_id,
            music_directory=args.music_directory,
            map_style=args.map_style,
            rasteriser=cards,
        )
    except (PrivateJourneyFilmError, StoryFilmError, StoryMusicError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
