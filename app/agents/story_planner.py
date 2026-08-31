"""Deterministic Story Plan generator for the pre-video prototype."""

from __future__ import annotations

from enum import StrEnum

from app.contracts import GpsEvent, RouteSummary, StoryChapter, StoryPlan
from app.gps import consolidate_events


class StoryOutputLanguage(StrEnum):
    """Supported languages for user-facing deterministic story text."""

    JAPANESE = "ja"
    ENGLISH = "en"


class RuleBasedStoryPlanner:
    """Build an inspectable first story proposal without claiming visual knowledge."""

    roles = {
        StoryOutputLanguage.JAPANESE: {
            "departure": ("出発", "旅の開始地点を示すため。"),
            "stop": ("小休止", "走行のリズムが変わる候補として。"),
            "long_ride": ("走り続ける", "旅の移動量を示すため。"),
            "elevation_change": (
                "景色の変化",
                "高度変化があり、映像確認の価値が高いため。",
            ),
            "scenery_change": (
                "景色の変化",
                "GPS上の変化があり、映像確認の価値が高いため。",
            ),
            "speed_change": ("走行の変化", "走行状況の変化を示す候補として。"),
            "direction_change": ("進路の変化", "ルートの転換点になり得るため。"),
            "arrival_candidate": ("到着と余韻", "ルートの終点を示すため。"),
        },
        StoryOutputLanguage.ENGLISH: {
            "departure": ("Departure", "Establishes the beginning of the journey."),
            "stop": ("Short pause", "Marks a possible change in the ride's rhythm."),
            "long_ride": ("Riding onward", "Shows the distance covered on the journey."),
            "elevation_change": (
                "Changing scenery",
                "An elevation change makes this moment worth checking on video.",
            ),
            "scenery_change": (
                "Changing scenery",
                "A GPS-derived change makes this moment worth checking on video.",
            ),
            "speed_change": (
                "Change in motion",
                "Suggests a possible change in riding conditions.",
            ),
            "direction_change": (
                "Change of direction",
                "May mark a turning point along the route.",
            ),
            "arrival_candidate": (
                "Arrival and reflection",
                "Establishes the end of the route.",
            ),
        },
    }
    fallbacks = {
        StoryOutputLanguage.JAPANESE: ("旅の一場面", "GPSイベントの候補として。"),
        StoryOutputLanguage.ENGLISH: (
            "A moment on the journey",
            "Included as a GPS event candidate.",
        ),
    }
    priority = {
        "departure": 100,
        "arrival_candidate": 99,
        "elevation_change": 80,
        "scenery_change": 80,
        "direction_change": 70,
        "long_ride": 60,
        "speed_change": 50,
        "stop": 40,
    }

    def plan(
        self,
        route_summary: RouteSummary,
        events: tuple[GpsEvent, ...],
        *,
        target_duration_s: float,
        output_language: StoryOutputLanguage = StoryOutputLanguage.JAPANESE,
    ) -> StoryPlan:
        self._validate_plan_inputs(events, target_duration_s)
        chosen = self._select_events(consolidate_events(events))
        return self._build_plan(
            route_summary,
            chosen,
            target_duration_s=target_duration_s,
            output_language=StoryOutputLanguage(output_language),
            planning_provider="rule_based_mock",
        )

    def plan_selected_events(
        self,
        route_summary: RouteSummary,
        selected_events: tuple[GpsEvent, ...],
        *,
        target_duration_s: float,
        output_language: StoryOutputLanguage = StoryOutputLanguage.JAPANESE,
    ) -> StoryPlan:
        """Build a plan from preselected events while preserving repeated types.

        The caller owns the non-visual eligibility decision, such as confirmed
        local timestamp coverage. This method does not infer visual quality or
        evidence status.
        """
        self._validate_plan_inputs(selected_events, target_duration_s)
        event_ids = [event.event_id for event in selected_events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("selected GPS event IDs must be unique")
        chosen = tuple(
            sorted(selected_events, key=lambda event: (event.start_time, event.event_id))
        )
        return self._build_plan(
            route_summary,
            chosen,
            target_duration_s=target_duration_s,
            output_language=StoryOutputLanguage(output_language),
            planning_provider="rule_based_video_coverage",
        )

    def _build_plan(
        self,
        route_summary: RouteSummary,
        chosen: tuple[GpsEvent, ...],
        *,
        target_duration_s: float,
        output_language: StoryOutputLanguage,
        planning_provider: str,
    ) -> StoryPlan:
        duration_per_chapter = target_duration_s / len(chosen)
        chapters = tuple(
            self._chapter(index, event, duration_per_chapter, output_language)
            for index, event in enumerate(chosen, start=1)
        )
        distance_km = route_summary.total_distance_m / 1_000
        title = (
            f"A {distance_km:.1f} km journey"
            if output_language is StoryOutputLanguage.ENGLISH
            else f"{distance_km:.1f}kmをたどる旅"
        )
        return StoryPlan(
            title=title,
            target_duration_s=target_duration_s,
            chapters=chapters,
            selected_event_ids=tuple(event.event_id for event in chosen),
            planning_provider=planning_provider,
        )

    @staticmethod
    def _validate_plan_inputs(events: tuple[GpsEvent, ...], target_duration_s: float) -> None:
        if not events:
            raise ValueError("at least one GPS event is required")
        if not 300 <= target_duration_s <= 600:
            raise ValueError("target_duration_s must be between 300 and 600 seconds")

    def _select_events(self, events: tuple[GpsEvent, ...]) -> tuple[GpsEvent, ...]:
        by_type: dict[str, GpsEvent] = {}
        for event in sorted(
            events,
            key=lambda item: (-item.importance_hint, item.start_time, item.event_id),
        ):
            by_type.setdefault(event.event_type, event)

        selected = sorted(
            by_type.values(),
            key=lambda event: (event.start_time, -self.priority.get(event.event_type, 0)),
        )
        return tuple(selected)

    def _chapter(
        self,
        index: int,
        event: GpsEvent,
        duration_s: float,
        output_language: StoryOutputLanguage,
    ) -> StoryChapter:
        title, rationale = self.roles[output_language].get(
            event.event_type,
            self.fallbacks[output_language],
        )
        return StoryChapter(
            chapter_id=f"chapter_{index:02d}",
            title=title,
            event_id=event.event_id,
            start_time=event.start_time,
            end_time=event.end_time,
            narrative_role=event.event_type,
            selection_rationale=rationale,
            target_duration_s=duration_s,
        )
