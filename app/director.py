"""Director: converts confirmed UniversalEvents into a DirectorScript.

The Director decides *which* confirmed events to use, *in what order*, and
*what narrative role* each should play.  It does not produce FFmpeg commands,
does not read evidence state, and does not call ``confirm_clip_evidence``.

Evidence gate reminder
----------------------
The Director's standard input must consist exclusively of
``UniversalEvent`` instances where ``evidence_confirmed=True``.  Any
filtering to enforce this is the caller's responsibility; the Director
trusts that what it receives has already passed the first line of defence
(see ``app/scout`` module docstring).

The second line of defence — ``build_ffmpeg_render_plan`` in
``app/edit/render_plan`` — remains in place downstream and is not modified
here.

Narrative arc
-------------
The default arc for the Ride Storyteller MVP is::

    Hook → Build-up → Climax → Resolution

When the number of confirmed events is fewer than four, arcs are filled
in priority order and no event is artificially duplicated.  The Director
produces only non-empty scenes.

Director protocol
-----------------
Both ``RuleBasedDirector`` and ``GeminiDirector`` implement the ``Director``
protocol: a single ``compose`` method that accepts a tuple of confirmed
``UniversalEvent`` objects and returns a ``DirectorScript``.

``GeminiDirector`` is the standard path.  ``RuleBasedDirector`` is the
fallback.  ``FallbackDirector`` wraps the two and handles the handover
transparently: callers interact only with ``FallbackDirector.compose``.

GeminiDirector sanitization
----------------------------
Only semantic attributes are forwarded to Gemini — never raw coordinates,
source asset IDs, local file paths, or any internal evidence fields.
Gemini decides *which events* to include and *what story role* each plays.
Actual ``source_asset_id``, ``source_start_sec``, and ``source_end_sec``
values are always restored from the original ``UniversalEvent`` objects
after validation; Gemini never generates or modifies those values.

Gemini response contract
------------------------
Gemini must return JSON with a top-level ``scenes`` list.  Each scene has
``scene_type``, ``event_ids``, ``transition_type``, and ``overlay_text``.
The validator rejects: unknown event_ids, duplicate event_ids across scenes,
unconfirmed event references, empty clip lists, invalid scene_type or
transition_type values, and unknown fields in any scene object.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from app.scout import UniversalEvent

# ---------------------------------------------------------------------------
# Arc ordering
# ---------------------------------------------------------------------------

class NarrativeArc(StrEnum):
    HOOK = "hook"
    BUILD_UP = "build_up"
    CLIMAX = "climax"
    RESOLUTION = "resolution"


class JourneyCoverage(StrEnum):
    """Evidence-backed coverage of the journey anchors in a script input."""

    DEPARTURE_TO_ARRIVAL = "departure_to_arrival"
    DEPARTURE_WITHOUT_ARRIVAL = "departure_without_arrival"
    ARRIVAL_WITHOUT_DEPARTURE = "arrival_without_departure"
    MIDDLE_OF_JOURNEY_ONLY = "middle_of_journey_only"


# Preferred arc assignment order when events are ranked by score/intensity.
# Earlier arcs in this sequence receive higher-ranked events first.
_ARC_PRIORITY: tuple[NarrativeArc, ...] = (
    NarrativeArc.CLIMAX,
    NarrativeArc.HOOK,
    NarrativeArc.RESOLUTION,
    NarrativeArc.BUILD_UP,
)

# Presentation order in the final script (chronological narrative).
_ARC_ORDER: tuple[NarrativeArc, ...] = (
    NarrativeArc.HOOK,
    NarrativeArc.BUILD_UP,
    NarrativeArc.CLIMAX,
    NarrativeArc.RESOLUTION,
)


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SceneClip:
    """One confirmed clip assigned to a scene.

    ``source_asset_id``, ``source_start_sec``, and ``source_end_sec`` are
    copied directly from ``UniversalEvent``; they come from the resolved
    ``ResolvedCandidateClip`` (or refined ``ScoredHighlightWindow``) and are
    never produced by the Director itself.
    """

    event_id: str
    source_asset_id: str
    source_start_sec: float
    source_end_sec: float

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("SceneClip.event_id is required")
        if not self.source_asset_id or not self.source_asset_id.strip():
            raise ValueError("SceneClip.source_asset_id must be a non-empty, non-whitespace string")
        if self.source_start_sec < 0:
            raise ValueError("SceneClip.source_start_sec must be non-negative")
        if self.source_end_sec <= self.source_start_sec:
            raise ValueError("SceneClip.source_end_sec must be after source_start_sec")


@dataclass(frozen=True)
class Scene:
    """One narrative beat containing one or more confirmed clips."""

    scene_id: str
    scene_type: NarrativeArc
    clips: tuple[SceneClip, ...]
    transition_type: str
    overlay_text: str | None

    def __post_init__(self) -> None:
        if not self.scene_id:
            raise ValueError("Scene.scene_id is required")
        if not self.clips:
            raise ValueError("Scene.clips must not be empty")
        if not self.transition_type:
            raise ValueError("Scene.transition_type is required")


@dataclass(frozen=True)
class DirectorMetadata:
    """Provenance record for a DirectorScript."""

    composer: str
    event_count_in: int
    event_count_used: int
    arc_names: tuple[str, ...]
    journey_coverage: JourneyCoverage = JourneyCoverage.MIDDLE_OF_JOURNEY_ONLY


@dataclass(frozen=True)
class DirectorScript:
    """The complete script produced by a Director.

    ``scenes`` are in narrative presentation order (Hook → … → Resolution).
    Only non-empty scenes are included.
    """

    scenes: tuple[Scene, ...]
    metadata: DirectorMetadata

    def __post_init__(self) -> None:
        if not self.scenes:
            raise ValueError("DirectorScript.scenes must not be empty")
        scene_ids = tuple(scene.scene_id for scene in self.scenes)
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("DirectorScript.scene_id values must be unique")
        scene_types = tuple(scene.scene_type for scene in self.scenes)
        if len(scene_types) != len(set(scene_types)):
            raise ValueError("DirectorScript.scene_type values must be unique")
        arc_indexes = tuple(_ARC_ORDER.index(scene_type) for scene_type in scene_types)
        if arc_indexes != tuple(sorted(arc_indexes)):
            raise ValueError(
                "DirectorScript scenes must be in Hook, Build-up, Climax, Resolution order"
            )
        if self.metadata.arc_names != tuple(scene_type.value for scene_type in scene_types):
            raise ValueError("DirectorScript.metadata.arc_names must match scenes")
        clip_count = sum(len(scene.clips) for scene in self.scenes)
        if self.metadata.event_count_used != clip_count:
            raise ValueError(
                "DirectorScript.metadata.event_count_used must match clip count"
            )


def browser_safe_script_view(
    script: DirectorScript,
    *,
    fallback_used: bool,
) -> dict[str, object]:
    """Return the smallest browser-safe representation of a DirectorScript.

    This is intentionally a presentation summary, not an Editor artifact.
    It omits every per-clip identifier and source field, including event IDs,
    asset IDs, local names, source intervals, and any location data.  Browser
    callers can show the narrative structure without gaining access to the
    private media identity required by the deterministic Editor.
    """
    return {
        "composer": script.metadata.composer,
        "fallback_used": fallback_used,
        "event_count_in": script.metadata.event_count_in,
        "event_count_used": script.metadata.event_count_used,
        "journey_coverage": script.metadata.journey_coverage.value,
        "scenes": [
            {
                "role": scene.scene_type.value,
                "event_count": len(scene.clips),
                "transition_type": scene.transition_type,
                "overlay_text": scene.overlay_text,
            }
            for scene in script.scenes
        ],
    }


# ---------------------------------------------------------------------------
# Director protocol (shared by RuleBasedDirector and GeminiDirector)
# ---------------------------------------------------------------------------

@runtime_checkable
class Director(Protocol):
    """Compose a DirectorScript from a sequence of confirmed UniversalEvents."""

    def compose(self, events: tuple[UniversalEvent, ...]) -> DirectorScript: ...


# ---------------------------------------------------------------------------
# RuleBasedDirector
# ---------------------------------------------------------------------------

class RuleBasedDirector:
    """Deterministic fallback Director; no external calls.

    Uses departure and arrival events as journey anchors, then assigns the
    remaining confirmed events to narrative arcs by ``ranking_score`` (when
    present), then ``intensity``.  The strongest non-anchor event becomes the
    Climax; the strongest remaining non-anchor event becomes the Hook.  This
    permits a compelling middle-of-trip event to appear first without
    duplicating footage.  Departure and any remaining route events form the
    Build-up, while an arrival event (or the chronologically last fallback)
    forms the Resolution.

    The director never invents a trip fact: an arc is only a presentation
    role assigned to one of the supplied confirmed events.  No event is ever
    duplicated across arcs.

    This class implements the ``Director`` protocol and is interchangeable
    with ``GeminiDirector`` once that is available.
    """

    # Default transition type used throughout (no cut logic at this layer).
    _DEFAULT_TRANSITION: str = "cut"

    def compose(self, events: tuple[UniversalEvent, ...]) -> DirectorScript:
        """Return a ``DirectorScript`` from *confirmed* events.

        Raises ``ValueError`` if ``events`` is empty or if any event has
        ``evidence_confirmed=False`` (caller must pre-filter).
        """
        if not events:
            raise ValueError("RuleBasedDirector.compose requires at least one event")
        for event in events:
            if not event.evidence_confirmed:
                raise ValueError(
                    f"event {event.event_id!r} has evidence_confirmed=False; "
                    "only confirmed events may be passed to the Director"
                )

        arc_assignments = _assign_arcs(events)
        scenes: list[Scene] = []
        for arc in _ARC_ORDER:
            assigned = arc_assignments.get(arc)
            if not assigned:
                continue
            clips = tuple(_scene_clip(e) for e in assigned)
            scenes.append(
                Scene(
                    scene_id=f"scene_{arc.value}",
                    scene_type=arc,
                    clips=clips,
                    transition_type=self._DEFAULT_TRANSITION,
                    overlay_text=None,
                )
            )

        arc_names = tuple(scene.scene_type.value for scene in scenes)
        return DirectorScript(
            scenes=tuple(scenes),
            metadata=DirectorMetadata(
                composer="rule_based",
                event_count_in=len(events),
                event_count_used=sum(len(s.clips) for s in scenes),
                arc_names=arc_names,
                journey_coverage=_journey_coverage(events),
            ),
        )


# ---------------------------------------------------------------------------
# Arc assignment helpers (module-private)
# ---------------------------------------------------------------------------

def _rank_key(event: UniversalEvent) -> tuple[float, float]:
    """Higher ranking_score / intensity → sorted first (descending)."""
    score = event.ranking_score if event.ranking_score is not None else event.intensity
    return (-score, -event.intensity)


def _assign_arcs(
    events: tuple[UniversalEvent, ...]
) -> dict[NarrativeArc, list[UniversalEvent]]:
    """Assign events to arcs without duplication.

    Strategy (fail-soft for small event counts):
    1. Prefer an explicit arrival candidate as Resolution; otherwise use the
       chronologically last event.
    2. Prefer the highest-ranked non-departure, non-resolution event as
       Climax.
    3. Prefer the next highest-ranked non-departure event as Hook.  This is
       deliberately allowed to be a middle-of-trip event.
    4. Put departure and all remaining events in chronological Build-up.

    When there are too few events for every role, no event is repeated solely
    to fill an arc.
    """
    ordered = sorted(events, key=lambda e: (e.requested_start_sec, e.event_id))
    ranked = sorted(events, key=_rank_key)

    used: set[str] = set()
    result: dict[NarrativeArc, list[UniversalEvent]] = {}

    def _claim(arc: NarrativeArc, event: UniversalEvent) -> None:
        used.add(event.event_id)
        result.setdefault(arc, []).append(event)

    # Resolution: explicit arrival takes precedence over a later non-arrival
    # telemetry event.  A route with no named arrival still closes on its last
    # confirmed event.
    arrivals = [event for event in ordered if _is_arrival(event)]
    if len(ordered) >= 2:
        _claim(NarrativeArc.RESOLUTION, arrivals[-1] if arrivals else ordered[-1])

    # Climax: strongest non-anchor event.  Departure is a progression anchor,
    # not a climax merely because it happens to carry a high numeric score.
    _claim_best_available(
        result,
        used,
        NarrativeArc.CLIMAX,
        ranked,
        exclude_departures=True,
    )

    # Hook: the next strongest available non-departure event.  It can be from
    # the middle of the trip, but remains a real, confirmed event and is never
    # repeated later as a preview.
    _claim_best_available(
        result,
        used,
        NarrativeArc.HOOK,
        ranked,
        exclude_departures=True,
    )

    # If only a departure remains (for example, a two-event trip), it is a
    # truthful hook rather than producing an empty script.
    if NarrativeArc.HOOK not in result:
        _claim_best_available(
            result,
            used,
            NarrativeArc.HOOK,
            ranked,
            exclude_departures=False,
        )

    # Build-up: all remaining events, including departure, stay chronological.
    for event in ordered:
        if event.event_id not in used:
            _claim(NarrativeArc.BUILD_UP, event)

    return result


def _claim_best_available(
    result: dict[NarrativeArc, list[UniversalEvent]],
    used: set[str],
    arc: NarrativeArc,
    ranked: list[UniversalEvent],
    *,
    exclude_departures: bool,
) -> None:
    """Claim the highest-ranked eligible event for one narrative role."""
    for event in ranked:
        if event.event_id in used:
            continue
        if exclude_departures and _is_departure(event):
            continue
        used.add(event.event_id)
        result.setdefault(arc, []).append(event)
        return


def _is_departure(event: UniversalEvent) -> bool:
    return event.event_type == "departure"


def _is_arrival(event: UniversalEvent) -> bool:
    return event.event_type in {"arrival", "arrival_candidate"}


def _journey_coverage(events: tuple[UniversalEvent, ...]) -> JourneyCoverage:
    """Classify only the supplied evidence; do not infer missing route anchors."""
    has_departure = any(_is_departure(event) for event in events)
    has_arrival = any(_is_arrival(event) for event in events)
    if has_departure and has_arrival:
        return JourneyCoverage.DEPARTURE_TO_ARRIVAL
    if has_departure:
        return JourneyCoverage.DEPARTURE_WITHOUT_ARRIVAL
    if has_arrival:
        return JourneyCoverage.ARRIVAL_WITHOUT_DEPARTURE
    return JourneyCoverage.MIDDLE_OF_JOURNEY_ONLY


def _scene_clip(event: UniversalEvent) -> SceneClip:
    """Build a SceneClip from a confirmed UniversalEvent.

    Precondition: ``event.evidence_confirmed=True`` and source fields are
    set (guaranteed by ``UniversalEvent.__post_init__``).
    """
    assert event.source_asset_id is not None
    assert event.source_start_sec is not None
    assert event.source_end_sec is not None
    return SceneClip(
        event_id=event.event_id,
        source_asset_id=event.source_asset_id,
        source_start_sec=event.source_start_sec,
        source_end_sec=event.source_end_sec,
    )


# ---------------------------------------------------------------------------
# GeminiDirector transport protocol and error
# ---------------------------------------------------------------------------

class GeminiDirectorTransport(Protocol):
    """Thin boundary between GeminiDirector and a concrete Gemini SDK adapter.

    The concrete implementation must accept a prompt string and a sanitized
    story payload, forward them to Gemini, and return the raw parsed JSON
    response as a ``Mapping``.  It must not include any SDK-specific types
    in the return value.
    """

    def compose_script(
        self,
        *,
        prompt: str,
        story_payload: Mapping[str, object],
    ) -> Mapping[str, object]: ...


class GeminiDirectorError(RuntimeError):
    """Safe failure from GeminiDirector; must not reveal provider response content.

    Raised when Gemini is unavailable, returns invalid JSON, produces an
    unrecognised structure, references unknown event_ids, duplicates events,
    or produces any other result that cannot be safely adopted.

    The public ``FallbackDirector`` catches this error and delegates to
    ``RuleBasedDirector``.
    """


# ---------------------------------------------------------------------------
# GeminiDirector
# ---------------------------------------------------------------------------

# Allowed scene_type values (must match NarrativeArc values).
_ALLOWED_SCENE_TYPES: frozenset[str] = frozenset(arc.value for arc in NarrativeArc)

# The deterministic local Editor currently implements only hard cuts.  Keep
# the Director contract aligned so an AI cannot produce an artifact that the
# Editor would have to silently reinterpret.
_ALLOWED_TRANSITIONS: frozenset[str] = frozenset({"cut"})

# Exact set of keys expected in each Gemini scene object.
_SCENE_KEYS: frozenset[str] = frozenset(
    {"scene_type", "event_ids", "transition_type", "overlay_text"}
)


class GeminiDirector:
    """Standard Director: uses Gemini to compose a narrative script.

    Gemini receives only sanitized semantic attributes — never raw coordinates,
    source asset IDs, local paths, or evidence internals.  After Gemini
    responds, the validator rehydrates ``SceneClip`` objects exclusively from
    the original ``UniversalEvent`` inputs, so Gemini cannot invent or modify
    source intervals.

    On any failure, raises ``GeminiDirectorError``.  Use ``FallbackDirector``
    to wrap this class with automatic ``RuleBasedDirector`` fallback.
    """

    def __init__(self, transport: GeminiDirectorTransport) -> None:
        self._transport = transport

    def compose(self, events: tuple[UniversalEvent, ...]) -> DirectorScript:
        """Return a ``DirectorScript`` from *confirmed* events via Gemini.

        Raises
        ------
        ValueError
            If ``events`` is empty or contains unconfirmed events.
        GeminiDirectorError
            On transport failure, invalid response structure, or validation
            failure.
        """
        if not events:
            raise ValueError("GeminiDirector.compose requires at least one event")
        for event in events:
            if not event.evidence_confirmed:
                raise ValueError(
                    f"event {event.event_id!r} has evidence_confirmed=False; "
                    "only confirmed events may be passed to the Director"
                )

        events_by_id: dict[str, UniversalEvent] = {e.event_id: e for e in events}
        payload = _sanitize_payload(events)
        prompt = _gemini_director_prompt(len(events))

        try:
            response = self._transport.compose_script(
                prompt=prompt,
                story_payload=payload,
            )
            return _validated_gemini_script(response, events_by_id)
        except GeminiDirectorError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise GeminiDirectorError(
                "Gemini returned an invalid director script"
            ) from error
        except Exception as error:
            raise GeminiDirectorError("Gemini director was unavailable") from error


# ---------------------------------------------------------------------------
# FallbackDirector
# ---------------------------------------------------------------------------

class FallbackDirector:
    """Wraps GeminiDirector with automatic RuleBasedDirector fallback.

    This is the recommended entry point for production use.  Callers compose
    scripts through ``FallbackDirector.compose``; the choice of Gemini vs
    rule-based is transparent to them.

    On ``GeminiDirectorError`` the fallback is applied silently.  All other
    exceptions (including ``ValueError`` for bad inputs) propagate unchanged.
    """

    def __init__(
        self,
        gemini: GeminiDirector,
        fallback: RuleBasedDirector | None = None,
    ) -> None:
        self._gemini = gemini
        self._fallback = fallback or RuleBasedDirector()

    def compose(self, events: tuple[UniversalEvent, ...]) -> DirectorScript:
        """Compose via Gemini; fall back to RuleBasedDirector on failure."""
        try:
            return self._gemini.compose(events)
        except GeminiDirectorError:
            return self._fallback.compose(events)


# ---------------------------------------------------------------------------
# Payload sanitization (module-private)
# ---------------------------------------------------------------------------

def _sanitize_payload(
    events: tuple[UniversalEvent, ...]
) -> dict[str, object]:
    """Build a Gemini-safe payload; never include coordinates or source paths."""
    return {
        "events": [_sanitize_event(e) for e in events],
    }


def _sanitize_event(event: UniversalEvent) -> dict[str, object]:
    """Serialize one event for Gemini — semantic fields only."""
    ctx = event.location_context
    duration_s: float | None = None
    if event.source_start_sec is not None and event.source_end_sec is not None:
        duration_s = round(event.source_end_sec - event.source_start_sec, 3)
    entry: dict[str, object] = {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "sub_category": event.sub_category,
        "duration_s": duration_s,
        "intensity": event.intensity,
        "visual_score": event.visual_score,
        "scenic_score": event.scenic_score,
        "ranking_score": event.ranking_score,
        "evidence_confirmed": event.evidence_confirmed,
        "place_name": ctx.place_name,
        "poi_type": ctx.poi_type,
        "road_context": ctx.road_context,
        "elevation_m": ctx.elevation_m,
    }
    return entry


# ---------------------------------------------------------------------------
# Prompt (module-private)
# ---------------------------------------------------------------------------

def _gemini_director_prompt(event_count: int) -> str:
    return (
        "You are the Director for Ride Storyteller, a motorcycle travel-story generator. "
        "Your task is to compose a short narrative film from the confirmed GPS events "
        "provided. "
        "Arrange the events into a four-act structure: Hook, Build-up, Climax, Resolution. "
        "If there are fewer than four events, use only the acts that can be filled "
        "without repeating the same event in multiple scenes. "
        "Hook should engage the viewer immediately. "
        "Build-up shows the journey's progression. "
        "Climax is the most visually or emotionally compelling moment. "
        "Resolution provides arrival and reflection. "
        "Do NOT invent locations, events, or visual content not present in the input. "
        "Do NOT duplicate the same event_id in more than one scene. "
        "Return ONLY a JSON object with a top-level key 'scenes' containing a list. "
        "Each scene must have exactly these keys: "
        "scene_type (one of: hook, build_up, climax, resolution), "
        "event_ids (list of event_id strings from the input), "
        "transition_type (must be: cut), "
        "overlay_text (a short descriptive phrase in the journey language, or null). "
        f"You have {event_count} confirmed event(s) to work with. "
        "Use only event_id values from the supplied events list."
    )


# ---------------------------------------------------------------------------
# Response validation and script assembly (module-private)
# ---------------------------------------------------------------------------

def _validated_gemini_script(
    response: Mapping[str, object],
    events_by_id: dict[str, UniversalEvent],
) -> DirectorScript:
    """Validate Gemini's response and build a DirectorScript.

    All source identity fields are taken from the original ``UniversalEvent``
    objects; Gemini's response only determines scene structure and event order.

    Raises
    ------
    GeminiDirectorError
        On any structural or semantic validation failure.
    """
    if "scenes" not in response:
        raise GeminiDirectorError("Gemini response missing 'scenes' key")
    raw_scenes = response["scenes"]
    if isinstance(raw_scenes, (str, bytes)) or not isinstance(raw_scenes, (list, tuple)):
        raise GeminiDirectorError("Gemini 'scenes' must be a list")
    if not raw_scenes:
        raise GeminiDirectorError("Gemini returned an empty scenes list")

    seen_event_ids: set[str] = set()
    seen_scene_types: set[NarrativeArc] = set()
    previous_arc_index = -1
    scenes: list[Scene] = []

    for i, raw in enumerate(raw_scenes):
        if not isinstance(raw, Mapping):
            raise GeminiDirectorError(f"scene[{i}] must be an object")

        # Reject unknown fields
        extra = set(raw.keys()) - _SCENE_KEYS
        if extra:
            raise GeminiDirectorError(
                f"scene[{i}] has unexpected fields: {sorted(extra)}"
            )

        # scene_type
        scene_type_raw = raw.get("scene_type")
        if not isinstance(scene_type_raw, str) or scene_type_raw not in _ALLOWED_SCENE_TYPES:
            raise GeminiDirectorError(
                f"scene[{i}] scene_type {scene_type_raw!r} is not a valid NarrativeArc"
            )
        scene_type = NarrativeArc(scene_type_raw)
        if scene_type in seen_scene_types:
            raise GeminiDirectorError(
                f"scene[{i}] repeats scene_type {scene_type.value!r}"
            )
        arc_index = _ARC_ORDER.index(scene_type)
        if arc_index <= previous_arc_index:
            raise GeminiDirectorError(
                "Gemini scenes must be in Hook, Build-up, Climax, Resolution order"
            )

        # transition_type
        transition_raw = raw.get("transition_type")
        if not isinstance(transition_raw, str) or transition_raw not in _ALLOWED_TRANSITIONS:
            raise GeminiDirectorError(
                f"scene[{i}] transition_type {transition_raw!r} is not allowed"
            )

        # overlay_text
        overlay = raw.get("overlay_text")
        if overlay is not None and (not isinstance(overlay, str) or not overlay.strip()):
            raise GeminiDirectorError(
                f"scene[{i}] overlay_text must be a non-empty string or null"
            )
        overlay_text: str | None = overlay if overlay else None

        # event_ids
        event_ids_raw = raw.get("event_ids")
        if (
            isinstance(event_ids_raw, (str, bytes))
            or not isinstance(event_ids_raw, (list, tuple))
        ):
            raise GeminiDirectorError(f"scene[{i}] event_ids must be a list")
        if not event_ids_raw:
            raise GeminiDirectorError(f"scene[{i}] event_ids must not be empty")

        clips: list[SceneClip] = []
        for eid in event_ids_raw:
            if not isinstance(eid, str):
                raise GeminiDirectorError(
                    f"scene[{i}] event_ids contains non-string value {eid!r}"
                )
            if eid not in events_by_id:
                raise GeminiDirectorError(
                    f"scene[{i}] references unknown event_id {eid!r}"
                )
            if eid in seen_event_ids:
                raise GeminiDirectorError(
                    f"scene[{i}] event_id {eid!r} is used in more than one scene"
                )
            event = events_by_id[eid]
            if not event.evidence_confirmed:
                raise GeminiDirectorError(
                    f"scene[{i}] references unconfirmed event {eid!r}"
                )
            seen_event_ids.add(eid)
            clips.append(_scene_clip(event))

        scenes.append(
            Scene(
                scene_id=f"scene_{scene_type.value}",
                scene_type=scene_type,
                clips=tuple(clips),
                transition_type=transition_raw,
                overlay_text=overlay_text,
            )
        )
        seen_scene_types.add(scene_type)
        previous_arc_index = arc_index

    if not scenes:
        raise GeminiDirectorError("Gemini produced no valid scenes")

    arc_names = tuple(s.scene_type.value for s in scenes)
    return DirectorScript(
        scenes=tuple(scenes),
        metadata=DirectorMetadata(
            composer="gemini",
            event_count_in=len(events_by_id),
            event_count_used=len(seen_event_ids),
            arc_names=arc_names,
            journey_coverage=_journey_coverage(tuple(events_by_id.values())),
        ),
    )
