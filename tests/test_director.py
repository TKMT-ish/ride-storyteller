"""Tests for app/director.py — data contracts, RuleBasedDirector, GeminiDirector."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from app.demo import build_synthetic_director_events
from app.director import (
    Director,
    DirectorMetadata,
    DirectorScript,
    FallbackDirector,
    GeminiDirector,
    GeminiDirectorError,
    GeminiDirectorTransport,
    JourneyCoverage,
    NarrativeArc,
    RuleBasedDirector,
    Scene,
    SceneClip,
    _sanitize_payload,  # noqa: PLC2701 — tested directly
)
from app.scout import UniversalEvent, UniversalEventEvidence, UniversalEventLocationContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EVIDENCE_VIDEO = UniversalEventEvidence(gps=True, video=True)
_EVIDENCE_GPS = UniversalEventEvidence(gps=True, video=False)


def _confirmed_event(
    event_id: str,
    *,
    event_type: str = "elevation_change",
    source_asset_id: str = "asset-abc",
    source_start_sec: float = 10.0,
    source_end_sec: float = 40.0,
    requested_start_sec: float = 10.0,
    requested_end_sec: float = 40.0,
    intensity: float = 0.70,
    ranking_score: float | None = None,
) -> UniversalEvent:
    return UniversalEvent(
        event_id=event_id,
        event_type=event_type,
        sub_category=None,
        source_asset_id=source_asset_id,
        source_start_sec=source_start_sec,
        source_end_sec=source_end_sec,
        requested_start_sec=requested_start_sec,
        requested_end_sec=requested_end_sec,
        intensity=intensity,
        visual_score=None,
        scenic_score=None,
        ranking_score=ranking_score,
        location_context=UniversalEventLocationContext(),
        evidence=_EVIDENCE_VIDEO,
        evidence_confirmed=True,
    )


def _unconfirmed_event(event_id: str) -> UniversalEvent:
    return UniversalEvent(
        event_id=event_id,
        event_type="elevation_change",
        sub_category=None,
        source_asset_id=None,
        source_start_sec=None,
        source_end_sec=None,
        requested_start_sec=10.0,
        requested_end_sec=40.0,
        intensity=0.50,
        visual_score=None,
        scenic_score=None,
        ranking_score=None,
        location_context=UniversalEventLocationContext(),
        evidence=_EVIDENCE_GPS,
        evidence_confirmed=False,
    )


def _four_events() -> tuple[UniversalEvent, ...]:
    """Four confirmed events in chronological order, varying intensity."""
    return (
        _confirmed_event(
            "evt_departure", event_type="departure",
            requested_start_sec=0.0, requested_end_sec=30.0, intensity=0.60,
        ),
        _confirmed_event(
            "evt_mid1", event_type="elevation_change",
            requested_start_sec=100.0, requested_end_sec=130.0, intensity=0.70,
        ),
        _confirmed_event(
            "evt_climax", event_type="scenery_change",
            requested_start_sec=200.0, requested_end_sec=230.0, intensity=0.95,
        ),
        _confirmed_event(
            "evt_arrival", event_type="arrival_candidate",
            requested_start_sec=350.0, requested_end_sec=380.0, intensity=0.55,
        ),
    )


# ---------------------------------------------------------------------------
# 1. SceneClip invariants
# ---------------------------------------------------------------------------

class TestSceneClip:
    def test_valid_scene_clip(self) -> None:
        clip = SceneClip(
            event_id="evt_001",
            source_asset_id="asset-abc",
            source_start_sec=10.0,
            source_end_sec=40.0,
        )
        assert clip.event_id == "evt_001"

    def test_rejects_empty_event_id(self) -> None:
        with pytest.raises(ValueError, match="event_id"):
            SceneClip(
                event_id="", source_asset_id="asset-abc",
                source_start_sec=10.0, source_end_sec=40.0,
            )

    def test_rejects_empty_asset_id(self) -> None:
        with pytest.raises(ValueError, match="source_asset_id"):
            SceneClip(
                event_id="evt_001", source_asset_id="",
                source_start_sec=10.0, source_end_sec=40.0,
            )

    def test_rejects_whitespace_asset_id(self) -> None:
        with pytest.raises(ValueError, match="source_asset_id"):
            SceneClip(
                event_id="evt_001", source_asset_id="   ",
                source_start_sec=10.0, source_end_sec=40.0,
            )

    def test_rejects_negative_start(self) -> None:
        with pytest.raises(ValueError, match="source_start_sec"):
            SceneClip(
                event_id="evt_001", source_asset_id="asset-abc",
                source_start_sec=-1.0, source_end_sec=40.0,
            )

    def test_rejects_inverted_interval(self) -> None:
        with pytest.raises(ValueError, match="source_end_sec"):
            SceneClip(
                event_id="evt_001", source_asset_id="asset-abc",
                source_start_sec=40.0, source_end_sec=10.0,
            )

    def test_source_start_less_than_source_end(self) -> None:
        """source_start_sec < source_end_sec must hold for every valid SceneClip."""
        clip = SceneClip(
            event_id="e", source_asset_id="a",
            source_start_sec=5.0, source_end_sec=6.0,
        )
        assert clip.source_start_sec < clip.source_end_sec


# ---------------------------------------------------------------------------
# 2. Scene invariants
# ---------------------------------------------------------------------------

class TestScene:
    def _clip(self) -> SceneClip:
        return SceneClip(
            event_id="e", source_asset_id="a",
            source_start_sec=5.0, source_end_sec=10.0,
        )

    def test_valid_scene(self) -> None:
        s = Scene(
            scene_id="scene_hook",
            scene_type=NarrativeArc.HOOK,
            clips=(self._clip(),),
            transition_type="cut",
            overlay_text=None,
        )
        assert s.scene_id == "scene_hook"

    def test_rejects_empty_clips(self) -> None:
        with pytest.raises(ValueError, match="clips must not be empty"):
            Scene(
                scene_id="s", scene_type=NarrativeArc.HOOK,
                clips=(), transition_type="cut", overlay_text=None,
            )

    def test_rejects_empty_scene_id(self) -> None:
        with pytest.raises(ValueError, match="scene_id"):
            Scene(
                scene_id="", scene_type=NarrativeArc.HOOK,
                clips=(self._clip(),), transition_type="cut", overlay_text=None,
            )

    def test_rejects_empty_transition_type(self) -> None:
        with pytest.raises(ValueError, match="transition_type"):
            Scene(
                scene_id="s", scene_type=NarrativeArc.HOOK,
                clips=(self._clip(),), transition_type="", overlay_text=None,
            )


# ---------------------------------------------------------------------------
# 3. DirectorScript invariants
# ---------------------------------------------------------------------------

class TestDirectorScript:
    def _scene(self) -> Scene:
        clip = SceneClip(
            event_id="e", source_asset_id="a",
            source_start_sec=5.0, source_end_sec=10.0,
        )
        return Scene(
            scene_id="scene_hook", scene_type=NarrativeArc.HOOK,
            clips=(clip,), transition_type="cut", overlay_text=None,
        )

    def test_rejects_empty_scenes(self) -> None:
        with pytest.raises(ValueError, match="scenes must not be empty"):
            DirectorScript(
                scenes=(),
                metadata=DirectorMetadata(
                    composer="test", event_count_in=1,
                    event_count_used=1, arc_names=(),
                ),
            )

    def test_rejects_out_of_order_scene_roles(self) -> None:
        hook = self._scene()
        climax = Scene(
            scene_id="scene_climax",
            scene_type=NarrativeArc.CLIMAX,
            clips=(self._scene().clips[0],),
            transition_type="cut",
            overlay_text=None,
        )
        with pytest.raises(ValueError, match="Hook, Build-up, Climax, Resolution"):
            DirectorScript(
                scenes=(climax, hook),
                metadata=DirectorMetadata(
                    composer="test",
                    event_count_in=2,
                    event_count_used=2,
                    arc_names=("climax", "hook"),
                ),
            )

    def test_rejects_metadata_that_does_not_match_scenes(self) -> None:
        with pytest.raises(ValueError, match="arc_names"):
            DirectorScript(
                scenes=(self._scene(),),
                metadata=DirectorMetadata(
                    composer="test",
                    event_count_in=1,
                    event_count_used=1,
                    arc_names=("climax",),
                ),
            )

    def test_rejects_an_event_reused_across_scenes(self) -> None:
        clip = self._scene().clips[0]
        hook = Scene(
            scene_id="scene_hook",
            scene_type=NarrativeArc.HOOK,
            clips=(clip,),
            transition_type="cut",
            overlay_text=None,
        )
        build_up = Scene(
            scene_id="scene_build_up",
            scene_type=NarrativeArc.BUILD_UP,
            clips=(clip,),
            transition_type="cut",
            overlay_text=None,
        )
        with pytest.raises(ValueError, match="SceneClip.event_id values must be unique"):
            DirectorScript(
                scenes=(hook, build_up),
                metadata=DirectorMetadata(
                    composer="test",
                    event_count_in=1,
                    event_count_used=2,
                    arc_names=("hook", "build_up"),
                ),
            )


# ---------------------------------------------------------------------------
# 4. Director protocol structural check
# ---------------------------------------------------------------------------

def test_rule_based_director_satisfies_director_protocol() -> None:
    """RuleBasedDirector must satisfy the Director Protocol."""
    assert isinstance(RuleBasedDirector(), Director)


def test_synthetic_director_fixture_has_no_coordinate_or_source_path_fields() -> None:
    """The cloud Director fixture is fixed synthetic story material only."""
    events = build_synthetic_director_events()

    assert len(events) == 4
    serialized = repr(events)
    assert all(event.evidence_confirmed for event in events)
    assert "latitude" not in serialized
    assert "longitude" not in serialized
    assert "path" not in serialized.lower()


def test_browser_safe_script_view_excludes_clip_and_location_identity() -> None:
    """The UI may describe the story but must not receive private source identity."""
    from app.director import browser_safe_script_view

    script = RuleBasedDirector().compose(_four_events())
    view = browser_safe_script_view(script, fallback_used=True)
    serialized = repr(view)

    assert view["composer"] == "rule_based"
    assert view["fallback_used"] is True
    assert view["journey_coverage"] == JourneyCoverage.DEPARTURE_TO_ARRIVAL.value
    assert [scene["role"] for scene in view["scenes"]] == [
        "hook", "build_up", "climax", "resolution"
    ]
    for forbidden in (
        "event_id", "source_asset_id", "source_start_sec", "source_end_sec",
        "file_name", "latitude", "longitude", "path",
    ):
        assert forbidden not in serialized


# ---------------------------------------------------------------------------
# 5. Empty input raises
# ---------------------------------------------------------------------------

def test_compose_with_no_events_raises() -> None:
    director = RuleBasedDirector()
    with pytest.raises(ValueError, match="at least one event"):
        director.compose(())


def test_director_marks_middle_only_evidence_without_inventing_journey_endpoints() -> None:
    script = RuleBasedDirector().compose(
        (
            _confirmed_event("evt_turn", event_type="direction_change"),
            _confirmed_event(
                "evt_speed",
                event_type="speed_change",
                requested_start_sec=50.0,
                requested_end_sec=80.0,
            ),
        )
    )

    assert script.metadata.journey_coverage is JourneyCoverage.MIDDLE_OF_JOURNEY_ONLY


# ---------------------------------------------------------------------------
# 6. Unconfirmed event in input raises
# ---------------------------------------------------------------------------

def test_compose_rejects_unconfirmed_event() -> None:
    """Unconfirmed events must not be accepted even if mixed with confirmed ones."""
    director = RuleBasedDirector()
    confirmed = _confirmed_event("evt_ok")
    unconfirmed = _unconfirmed_event("evt_bad")
    with pytest.raises(ValueError, match="evidence_confirmed=False"):
        director.compose((confirmed, unconfirmed))


def test_compose_rejects_purely_unconfirmed_input() -> None:
    director = RuleBasedDirector()
    with pytest.raises(ValueError, match="evidence_confirmed=False"):
        director.compose((_unconfirmed_event("evt_x"),))


def test_rule_based_director_rejects_duplicate_event_ids() -> None:
    duplicate_events = (
        _confirmed_event("evt_duplicate", source_start_sec=0.0, source_end_sec=30.0),
        _confirmed_event("evt_duplicate", source_start_sec=50.0, source_end_sec=80.0),
    )

    with pytest.raises(ValueError, match="unique event_id"):
        RuleBasedDirector().compose(duplicate_events)


def test_gemini_director_rejects_duplicate_event_ids_before_transport() -> None:
    class _NeverCalledTransport:
        called = False

        def compose_script(
            self, *, prompt: str, story_payload: Mapping[str, object]
        ) -> Mapping[str, object]:
            self.called = True
            return {"scenes": []}

    transport = _NeverCalledTransport()
    duplicate_events = (
        _confirmed_event("evt_duplicate", source_start_sec=0.0, source_end_sec=30.0),
        _confirmed_event("evt_duplicate", source_start_sec=50.0, source_end_sec=80.0),
    )

    with pytest.raises(ValueError, match="unique event_id"):
        GeminiDirector(transport).compose(duplicate_events)

    assert transport.called is False


# ---------------------------------------------------------------------------
# 7. Director does not mutate evidence state
# ---------------------------------------------------------------------------

def test_director_does_not_change_evidence_confirmed() -> None:
    """Director must never change evidence_confirmed on any event."""
    director = RuleBasedDirector()
    evt = _confirmed_event("evt_001")
    original_confirmed = evt.evidence_confirmed

    director.compose((evt,))

    # Frozen dataclass: value cannot change, but we assert for explicitness
    assert evt.evidence_confirmed == original_confirmed


def test_director_does_not_change_evidence_video() -> None:
    director = RuleBasedDirector()
    evt = _confirmed_event("evt_001")
    original_video = evt.evidence.video

    director.compose((evt,))

    assert evt.evidence.video == original_video


# ---------------------------------------------------------------------------
# 8. Single event → at least one scene, no duplication
# ---------------------------------------------------------------------------

def test_single_event_produces_non_empty_script() -> None:
    director = RuleBasedDirector()
    script = director.compose((_confirmed_event("evt_only"),))

    assert len(script.scenes) >= 1


def test_single_event_not_duplicated_across_scenes() -> None:
    """One event must appear in exactly one scene, never duplicated."""
    director = RuleBasedDirector()
    script = director.compose((_confirmed_event("evt_only"),))

    all_event_ids = [clip.event_id for scene in script.scenes for clip in scene.clips]
    assert all_event_ids.count("evt_only") == 1


# ---------------------------------------------------------------------------
# 9. Two events → no duplication
# ---------------------------------------------------------------------------

def test_two_events_no_duplication() -> None:
    director = RuleBasedDirector()
    e1 = _confirmed_event("evt_a", requested_start_sec=0.0, requested_end_sec=30.0)
    e2 = _confirmed_event("evt_b", requested_start_sec=100.0, requested_end_sec=130.0)
    script = director.compose((e1, e2))

    all_event_ids = [clip.event_id for scene in script.scenes for clip in scene.clips]
    assert all_event_ids.count("evt_a") == 1
    assert all_event_ids.count("evt_b") == 1


# ---------------------------------------------------------------------------
# 10. Four events → Hook / Build-up / Climax / Resolution structure
# ---------------------------------------------------------------------------

def test_four_events_produce_all_four_arcs() -> None:
    director = RuleBasedDirector()
    script = director.compose(_four_events())

    arc_types = {scene.scene_type for scene in script.scenes}
    assert NarrativeArc.HOOK in arc_types
    assert NarrativeArc.BUILD_UP in arc_types
    assert NarrativeArc.CLIMAX in arc_types
    assert NarrativeArc.RESOLUTION in arc_types


def test_four_events_arc_order_is_hook_buildup_climax_resolution() -> None:
    """Scenes must appear in narrative presentation order."""
    director = RuleBasedDirector()
    script = director.compose(_four_events())

    arc_order = [scene.scene_type for scene in script.scenes]
    expected_order = [
        NarrativeArc.HOOK, NarrativeArc.BUILD_UP,
        NarrativeArc.CLIMAX, NarrativeArc.RESOLUTION,
    ]
    assert arc_order == expected_order


def test_four_events_no_event_duplicated() -> None:
    director = RuleBasedDirector()
    script = director.compose(_four_events())

    all_event_ids = [clip.event_id for scene in script.scenes for clip in scene.clips]
    assert len(all_event_ids) == len(set(all_event_ids)), "Each event must appear exactly once"


def test_four_events_all_events_used() -> None:
    director = RuleBasedDirector()
    events = _four_events()
    script = director.compose(events)

    all_event_ids = {clip.event_id for scene in script.scenes for clip in scene.clips}
    expected_ids = {e.event_id for e in events}
    assert all_event_ids == expected_ids


# ---------------------------------------------------------------------------
# 11. Climax receives highest-ranked event
# ---------------------------------------------------------------------------

def test_climax_receives_highest_intensity_event() -> None:
    """The Climax scene must contain the highest-ranked event."""
    director = RuleBasedDirector()
    script = director.compose(_four_events())

    climax_scenes = [s for s in script.scenes if s.scene_type is NarrativeArc.CLIMAX]
    assert len(climax_scenes) == 1
    climax_event_ids = {clip.event_id for clip in climax_scenes[0].clips}
    # evt_climax has intensity=0.95, the highest in _four_events()
    assert "evt_climax" in climax_event_ids


def test_climax_uses_ranking_score_over_intensity() -> None:
    """ranking_score takes precedence over intensity for arc assignment."""
    director = RuleBasedDirector()
    # evt_low has high intensity but no ranking_score
    # evt_high has lower intensity but high ranking_score
    low = _confirmed_event(
        "evt_low", requested_start_sec=0.0, requested_end_sec=30.0,
        intensity=0.90, ranking_score=None,
    )
    high = _confirmed_event(
        "evt_high", requested_start_sec=100.0, requested_end_sec=130.0,
        intensity=0.40, ranking_score=0.95,
    )
    last = _confirmed_event(
        "evt_last", requested_start_sec=200.0, requested_end_sec=230.0,
        intensity=0.50, ranking_score=None,
    )

    script = director.compose((low, high, last))

    climax_event_ids = {
        clip.event_id
        for scene in script.scenes
        if scene.scene_type is NarrativeArc.CLIMAX
        for clip in scene.clips
    }
    assert "evt_high" in climax_event_ids


# ---------------------------------------------------------------------------
# 12. Journey anchors and story order
# ---------------------------------------------------------------------------

def test_hook_can_use_a_confirmed_middle_of_trip_event() -> None:
    """A hook may preview a real later event without duplicating the climax."""
    director = RuleBasedDirector()
    script = director.compose(_four_events())

    hook_scenes = [s for s in script.scenes if s.scene_type is NarrativeArc.HOOK]
    assert len(hook_scenes) == 1
    hook_event_ids = {clip.event_id for clip in hook_scenes[0].clips}
    assert hook_event_ids == {"evt_mid1"}


def test_departure_is_build_up_anchor_not_climax() -> None:
    """A high-score departure remains a truthful progression anchor."""
    departure = _confirmed_event(
        "evt_departure", event_type="departure",
        requested_start_sec=0.0, requested_end_sec=30.0, intensity=1.0,
    )
    hook_candidate = _confirmed_event(
        "evt_hook", event_type="direction_change",
        requested_start_sec=100.0, requested_end_sec=130.0, intensity=0.75,
    )
    climax = _confirmed_event(
        "evt_climax", event_type="scenery_change",
        requested_start_sec=200.0, requested_end_sec=230.0, intensity=0.95,
    )
    arrival = _confirmed_event(
        "evt_arrival", event_type="arrival_candidate",
        requested_start_sec=300.0, requested_end_sec=330.0, intensity=0.4,
    )

    script = RuleBasedDirector().compose(
        (departure, hook_candidate, climax, arrival)
    )
    by_arc = {
        scene.scene_type: {clip.event_id for clip in scene.clips}
        for scene in script.scenes
    }

    assert "evt_departure" not in by_arc.get(NarrativeArc.CLIMAX, set())
    assert "evt_departure" in by_arc.get(NarrativeArc.BUILD_UP, set())


def test_arrival_candidate_is_resolution_even_when_not_chronologically_last() -> None:
    """Explicit arrival semantics win over a later generic telemetry event."""
    midpoint = _confirmed_event(
        "evt_mid", requested_start_sec=0.0, requested_end_sec=30.0,
    )
    arrival = _confirmed_event(
        "evt_arrival", event_type="arrival_candidate",
        requested_start_sec=100.0, requested_end_sec=130.0,
    )
    later_telemetry = _confirmed_event(
        "evt_later", event_type="speed_change",
        requested_start_sec=200.0, requested_end_sec=230.0,
    )

    script = RuleBasedDirector().compose((midpoint, arrival, later_telemetry))
    resolution = next(
        scene for scene in script.scenes if scene.scene_type is NarrativeArc.RESOLUTION
    )

    assert {clip.event_id for clip in resolution.clips} == {"evt_arrival"}


def test_resolution_is_chronologically_last_event() -> None:
    director = RuleBasedDirector()
    script = director.compose(_four_events())

    res_scenes = [s for s in script.scenes if s.scene_type is NarrativeArc.RESOLUTION]
    assert len(res_scenes) == 1
    res_event_ids = {clip.event_id for clip in res_scenes[0].clips}
    assert "evt_arrival" in res_event_ids


# ---------------------------------------------------------------------------
# 13. No empty scenes are produced
# ---------------------------------------------------------------------------

def test_no_empty_scenes_in_script() -> None:
    """Every scene in the script must have at least one clip."""
    director = RuleBasedDirector()
    for n in range(1, 6):
        events = tuple(
            _confirmed_event(
                f"evt_{i:02d}",
                requested_start_sec=float(i * 100),
                requested_end_sec=float(i * 100 + 30),
            )
            for i in range(n)
        )
        script = director.compose(events)
        for scene in script.scenes:
            assert len(scene.clips) > 0, f"Scene {scene.scene_id} is empty for {n} events"


# ---------------------------------------------------------------------------
# 14. source_start_sec < source_end_sec in every SceneClip
# ---------------------------------------------------------------------------

def test_all_scene_clips_have_valid_intervals() -> None:
    director = RuleBasedDirector()
    script = director.compose(_four_events())

    for scene in script.scenes:
        for clip in scene.clips:
            assert clip.source_start_sec < clip.source_end_sec, (
                f"Invalid interval in {clip.event_id}: "
                f"{clip.source_start_sec} >= {clip.source_end_sec}"
            )


# ---------------------------------------------------------------------------
# 15. Metadata is correct
# ---------------------------------------------------------------------------

def test_metadata_composer_is_rule_based() -> None:
    script = RuleBasedDirector().compose((_confirmed_event("evt_001"),))
    assert script.metadata.composer == "rule_based"


def test_metadata_event_count_in_matches_input() -> None:
    events = _four_events()
    script = RuleBasedDirector().compose(events)
    assert script.metadata.event_count_in == len(events)


def test_metadata_event_count_used_equals_scenes_clips_total() -> None:
    script = RuleBasedDirector().compose(_four_events())
    total_clips = sum(len(s.clips) for s in script.scenes)
    assert script.metadata.event_count_used == total_clips


def test_metadata_arc_names_match_scenes() -> None:
    script = RuleBasedDirector().compose(_four_events())
    assert list(script.metadata.arc_names) == [s.scene_type.value for s in script.scenes]


# ---------------------------------------------------------------------------
# 16. Pre-filter contract: unconfirmed events excluded before compose
# ---------------------------------------------------------------------------

def test_confirmed_filter_before_compose_matches_director_input_contract() -> None:
    """Caller pre-filters; only confirmed events reach compose()."""
    all_events_mixed = (
        _confirmed_event("evt_confirmed", requested_start_sec=0.0, requested_end_sec=30.0),
        _unconfirmed_event("evt_awaiting"),
    )
    confirmed_only = tuple(e for e in all_events_mixed if e.evidence_confirmed)

    # pre-filtered input must succeed
    script = RuleBasedDirector().compose(confirmed_only)
    all_clip_ids = {clip.event_id for scene in script.scenes for clip in scene.clips}
    assert "evt_confirmed" in all_clip_ids
    assert "evt_awaiting" not in all_clip_ids


# ---------------------------------------------------------------------------
# 17. Small event counts are fail-soft (no exception)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n", [1, 2, 3])
def test_fewer_than_four_events_does_not_raise(n: int) -> None:
    events = tuple(
        _confirmed_event(
            f"evt_{i:02d}",
            requested_start_sec=float(i * 50),
            requested_end_sec=float(i * 50 + 25),
        )
        for i in range(n)
    )
    script = RuleBasedDirector().compose(events)
    assert len(script.scenes) >= 1


@pytest.mark.parametrize("n", [1, 2, 3])
def test_fewer_than_four_events_no_duplication(n: int) -> None:
    events = tuple(
        _confirmed_event(
            f"evt_{i:02d}",
            requested_start_sec=float(i * 50),
            requested_end_sec=float(i * 50 + 25),
        )
        for i in range(n)
    )
    script = RuleBasedDirector().compose(events)
    all_ids = [clip.event_id for scene in script.scenes for clip in scene.clips]
    assert len(all_ids) == len(set(all_ids)), f"Duplication detected for {n} events"


# ---------------------------------------------------------------------------
# 18. SceneClip source fields come from UniversalEvent (not produced by Director)
# ---------------------------------------------------------------------------

def test_scene_clip_source_fields_match_universal_event() -> None:
    evt = _confirmed_event(
        "evt_001",
        source_asset_id="asset-xyz",
        source_start_sec=15.0,
        source_end_sec=35.0,
    )
    script = RuleBasedDirector().compose((evt,))

    clips = [clip for scene in script.scenes for clip in scene.clips]
    assert len(clips) == 1
    assert clips[0].source_asset_id == "asset-xyz"
    assert clips[0].source_start_sec == pytest.approx(15.0)
    assert clips[0].source_end_sec == pytest.approx(35.0)


# ===========================================================================
# GeminiDirector tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Fake transport helpers
# ---------------------------------------------------------------------------

class _OkTransport:
    """Returns a valid four-scene response for the given events."""

    def __init__(self, events: tuple[UniversalEvent, ...]) -> None:
        self._events = events

    def compose_script(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        ids = [e.event_id for e in self._events]
        scenes: list[dict[str, object]] = []
        arc_order = ["hook", "build_up", "climax", "resolution"]
        for i, eid in enumerate(ids[:4]):
            scenes.append({
                "scene_type": arc_order[i % 4],
                "event_ids": [eid],
                "transition_type": "cut",
                "overlay_text": f"Scene {i + 1}",
            })
        return {"scenes": scenes}


class _FailTransport:
    """Always raises a generic exception to simulate a network failure."""

    def compose_script(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        raise RuntimeError("network timeout")


class _BadJsonTransport:
    """Returns a response with a missing top-level key."""

    def compose_script(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        return {"not_scenes": []}


class _UnknownEventTransport:
    """Returns a response that references an event_id not in the input."""

    def compose_script(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        return {
            "scenes": [
                {
                    "scene_type": "hook",
                    "event_ids": ["evt_INVENTED"],
                    "transition_type": "cut",
                    "overlay_text": None,
                }
            ]
        }


class _DuplicateEventTransport:
    """Uses the same event_id in two different scenes."""

    def __init__(self, event_id: str) -> None:
        self._eid = event_id

    def compose_script(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        return {
            "scenes": [
                {
                    "scene_type": "hook",
                    "event_ids": [self._eid],
                    "transition_type": "cut",
                    "overlay_text": None,
                },
                {
                    "scene_type": "climax",
                    "event_ids": [self._eid],
                    "transition_type": "cut",
                    "overlay_text": None,
                },
            ]
        }


class _DuplicateSceneTypeTransport:
    """Uses the Hook role twice for two otherwise distinct events."""

    def __init__(self, event_ids: tuple[str, str]) -> None:
        self._event_ids = event_ids

    def compose_script(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        return {
            "scenes": [
                {
                    "scene_type": "hook",
                    "event_ids": [self._event_ids[0]],
                    "transition_type": "cut",
                    "overlay_text": None,
                },
                {
                    "scene_type": "hook",
                    "event_ids": [self._event_ids[1]],
                    "transition_type": "fade",
                    "overlay_text": None,
                },
            ]
        }


class _OutOfOrderSceneTransport:
    """Returns valid roles in a non-presentation order."""

    def __init__(self, event_ids: tuple[str, str]) -> None:
        self._event_ids = event_ids

    def compose_script(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        return {
            "scenes": [
                {
                    "scene_type": "climax",
                    "event_ids": [self._event_ids[0]],
                    "transition_type": "cut",
                    "overlay_text": None,
                },
                {
                    "scene_type": "hook",
                    "event_ids": [self._event_ids[1]],
                    "transition_type": "fade",
                    "overlay_text": None,
                },
            ]
        }


class _EmptyEventIdsTransport:
    """Returns a scene with an empty event_ids list."""

    def compose_script(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        return {
            "scenes": [
                {
                    "scene_type": "hook",
                    "event_ids": [],
                    "transition_type": "cut",
                    "overlay_text": None,
                }
            ]
        }


class _BadSceneTypeTransport:
    """Returns a scene with an invalid scene_type."""

    def __init__(self, event_id: str) -> None:
        self._eid = event_id

    def compose_script(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        return {
            "scenes": [
                {
                    "scene_type": "intermission",
                    "event_ids": [self._eid],
                    "transition_type": "cut",
                    "overlay_text": None,
                }
            ]
        }


class _BadTransitionTransport:
    """Returns a scene with an invalid transition_type."""

    def __init__(self, event_id: str) -> None:
        self._eid = event_id

    def compose_script(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        return {
            "scenes": [
                {
                    "scene_type": "hook",
                    "event_ids": [self._eid],
                    "transition_type": "wipe",
                    "overlay_text": None,
                }
            ]
        }


class _UnknownFieldTransport:
    """Returns a scene with an extra unrecognised field."""

    def __init__(self, event_id: str) -> None:
        self._eid = event_id

    def compose_script(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        return {
            "scenes": [
                {
                    "scene_type": "hook",
                    "event_ids": [self._eid],
                    "transition_type": "cut",
                    "overlay_text": None,
                    "secret_field": "injected",
                }
            ]
        }


def _make_director(transport: GeminiDirectorTransport) -> GeminiDirector:
    return GeminiDirector(transport)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 19. GeminiDirector satisfies Director protocol
# ---------------------------------------------------------------------------

def test_gemini_director_satisfies_director_protocol() -> None:
    transport = _OkTransport(_four_events())
    director = _make_director(transport)
    assert isinstance(director, Director)


# ---------------------------------------------------------------------------
# 20. Sanitized payload privacy
# ---------------------------------------------------------------------------

def test_sanitized_payload_excludes_latitude_longitude() -> None:
    import json
    events = _four_events()
    payload = _sanitize_payload(events)
    serialized = json.dumps(payload)
    assert "latitude" not in serialized
    assert "longitude" not in serialized


def test_sanitized_payload_excludes_source_asset_id() -> None:
    import json
    events = _four_events()
    payload = _sanitize_payload(events)
    serialized = json.dumps(payload)
    assert "source_asset_id" not in serialized
    assert "source_start_sec" not in serialized
    assert "source_end_sec" not in serialized


def test_sanitized_payload_excludes_file_paths() -> None:
    import json
    events = _four_events()
    payload = _sanitize_payload(events)
    serialized = json.dumps(payload)
    assert ".mp4" not in serialized.lower()
    assert "file_name" not in serialized


def test_sanitized_payload_includes_semantic_fields() -> None:
    ctx = UniversalEventLocationContext(
        place_name="Lindis Pass",
        poi_type="mountain_pass",
        road_context="winding",
        elevation_m=971.0,
    )
    evt = UniversalEvent(
        event_id="evt_001",
        event_type="elevation_change",
        sub_category="mountain_pass",
        source_asset_id="asset-abc",
        source_start_sec=10.0,
        source_end_sec=40.0,
        requested_start_sec=10.0,
        requested_end_sec=40.0,
        intensity=0.8,
        visual_score=0.75,
        scenic_score=0.82,
        ranking_score=0.78,
        location_context=ctx,
        evidence=UniversalEventEvidence(gps=True, video=True),
        evidence_confirmed=True,
    )
    payload = _sanitize_payload((evt,))
    event_entry = payload["events"][0]  # type: ignore[index]
    assert event_entry["place_name"] == "Lindis Pass"  # type: ignore[index]
    assert event_entry["poi_type"] == "mountain_pass"  # type: ignore[index]
    assert event_entry["road_context"] == "winding"  # type: ignore[index]
    assert event_entry["elevation_m"] == 971.0  # type: ignore[index]
    assert event_entry["scenic_score"] == 0.82  # type: ignore[index]
    assert event_entry["ranking_score"] == 0.78  # type: ignore[index]
    assert event_entry["visual_score"] == 0.75  # type: ignore[index]
    assert event_entry["evidence_confirmed"] is True  # type: ignore[index]
    assert event_entry["intensity"] == 0.8  # type: ignore[index]


def test_sanitized_payload_duration_derived_from_source_interval() -> None:
    evt = _confirmed_event(
        "evt_001",
        source_start_sec=10.0,
        source_end_sec=40.0,
    )
    payload = _sanitize_payload((evt,))
    event_entry = payload["events"][0]  # type: ignore[index]
    assert event_entry["duration_s"] == pytest.approx(30.0)  # type: ignore[index]


# ---------------------------------------------------------------------------
# 21. GeminiDirector happy path
# ---------------------------------------------------------------------------

def test_gemini_director_produces_valid_script() -> None:
    events = _four_events()
    director = _make_director(_OkTransport(events))
    script = director.compose(events)

    assert isinstance(script, DirectorScript)
    assert len(script.scenes) >= 1
    assert script.metadata.composer == "gemini"


def test_gemini_director_script_clips_source_from_universal_event() -> None:
    """SceneClip source fields must come from UniversalEvent, not Gemini."""
    events = (
        _confirmed_event(
            "evt_001",
            source_asset_id="my-unique-asset",
            source_start_sec=15.0,
            source_end_sec=45.0,
        ),
    )
    transport = _OkTransport(events)
    script = _make_director(transport).compose(events)

    clips = [clip for scene in script.scenes for clip in scene.clips]
    assert len(clips) == 1
    assert clips[0].source_asset_id == "my-unique-asset"
    assert clips[0].source_start_sec == pytest.approx(15.0)
    assert clips[0].source_end_sec == pytest.approx(45.0)


def test_gemini_director_metadata_event_count_in() -> None:
    events = _four_events()
    script = _make_director(_OkTransport(events)).compose(events)
    assert script.metadata.event_count_in == len(events)


def test_gemini_director_no_empty_scenes() -> None:
    events = _four_events()
    script = _make_director(_OkTransport(events)).compose(events)
    for scene in script.scenes:
        assert len(scene.clips) > 0


def test_gemini_director_source_start_less_than_source_end() -> None:
    events = _four_events()
    script = _make_director(_OkTransport(events)).compose(events)
    for scene in script.scenes:
        for clip in scene.clips:
            assert clip.source_start_sec < clip.source_end_sec


# ---------------------------------------------------------------------------
# 22. GeminiDirector — evidence state not changed
# ---------------------------------------------------------------------------

def test_gemini_director_does_not_change_evidence_confirmed() -> None:
    events = _four_events()
    before = {e.event_id: e.evidence_confirmed for e in events}
    _make_director(_OkTransport(events)).compose(events)
    for evt in events:
        assert evt.evidence_confirmed == before[evt.event_id]


def test_gemini_director_does_not_change_evidence_video() -> None:
    events = _four_events()
    before = {e.event_id: e.evidence.video for e in events}
    _make_director(_OkTransport(events)).compose(events)
    for evt in events:
        assert evt.evidence.video == before[evt.event_id]


# ---------------------------------------------------------------------------
# 23. GeminiDirector — transport failure → GeminiDirectorError
# ---------------------------------------------------------------------------

def test_transport_failure_raises_gemini_director_error() -> None:
    events = (_confirmed_event("evt_001"),)
    with pytest.raises(GeminiDirectorError):
        _make_director(_FailTransport()).compose(events)


def test_missing_scenes_key_raises_gemini_director_error() -> None:
    events = (_confirmed_event("evt_001"),)
    with pytest.raises(GeminiDirectorError, match="missing 'scenes' key"):
        _make_director(_BadJsonTransport()).compose(events)


# ---------------------------------------------------------------------------
# 24. GeminiDirector — structural validation failures
# ---------------------------------------------------------------------------

def test_unknown_event_id_raises_gemini_director_error() -> None:
    events = (_confirmed_event("evt_001"),)
    with pytest.raises(GeminiDirectorError, match="unknown event_id"):
        _make_director(_UnknownEventTransport()).compose(events)


def test_duplicate_event_id_raises_gemini_director_error() -> None:
    events = (_confirmed_event("evt_001"),)
    with pytest.raises(GeminiDirectorError, match="more than one scene"):
        _make_director(_DuplicateEventTransport("evt_001")).compose(events)


def test_duplicate_scene_type_raises_gemini_director_error() -> None:
    events = (_confirmed_event("evt_001"), _confirmed_event("evt_002"))
    with pytest.raises(GeminiDirectorError, match="repeats scene_type"):
        _make_director(
            _DuplicateSceneTypeTransport(("evt_001", "evt_002"))
        ).compose(events)


def test_out_of_order_scenes_raise_gemini_director_error() -> None:
    events = (_confirmed_event("evt_001"), _confirmed_event("evt_002"))
    with pytest.raises(GeminiDirectorError, match="Hook, Build-up, Climax, Resolution"):
        _make_director(
            _OutOfOrderSceneTransport(("evt_001", "evt_002"))
        ).compose(events)


def test_empty_event_ids_raises_gemini_director_error() -> None:
    events = (_confirmed_event("evt_001"),)
    with pytest.raises(GeminiDirectorError, match="must not be empty"):
        _make_director(_EmptyEventIdsTransport()).compose(events)


def test_invalid_scene_type_raises_gemini_director_error() -> None:
    events = (_confirmed_event("evt_001"),)
    with pytest.raises(GeminiDirectorError, match="not a valid NarrativeArc"):
        _make_director(_BadSceneTypeTransport("evt_001")).compose(events)


def test_invalid_transition_type_raises_gemini_director_error() -> None:
    events = (_confirmed_event("evt_001"),)
    with pytest.raises(GeminiDirectorError, match="not allowed"):
        _make_director(_BadTransitionTransport("evt_001")).compose(events)


def test_fade_transition_is_rejected_until_the_editor_implements_it() -> None:
    events = (_confirmed_event("evt_001"),)

    class _FadeTransport:
        def compose_script(
            self, *, prompt: str, story_payload: Mapping[str, object]
        ) -> Mapping[str, object]:
            return {
                "scenes": [
                    {
                        "scene_type": "hook",
                        "event_ids": ["evt_001"],
                        "transition_type": "fade",
                        "overlay_text": None,
                    }
                ]
            }

    with pytest.raises(GeminiDirectorError, match="not allowed"):
        _make_director(_FadeTransport()).compose(events)


def test_unknown_field_in_scene_raises_gemini_director_error() -> None:
    events = (_confirmed_event("evt_001"),)
    with pytest.raises(GeminiDirectorError, match="unexpected fields"):
        _make_director(_UnknownFieldTransport("evt_001")).compose(events)


# ---------------------------------------------------------------------------
# 25. GeminiDirector — unconfirmed event in input raises ValueError (not GDE)
# ---------------------------------------------------------------------------

def test_gemini_director_rejects_unconfirmed_input() -> None:
    unconfirmed = _unconfirmed_event("evt_x")
    with pytest.raises(ValueError, match="evidence_confirmed=False"):
        _make_director(_OkTransport(())).compose((unconfirmed,))


# ---------------------------------------------------------------------------
# 26. FallbackDirector — falls back on GeminiDirectorError
# ---------------------------------------------------------------------------

def test_fallback_director_uses_gemini_on_success() -> None:
    events = _four_events()
    gemini = _make_director(_OkTransport(events))
    fallback = FallbackDirector(gemini=gemini)
    script = fallback.compose(events)
    assert script.metadata.composer == "gemini"


def test_fallback_director_falls_back_on_transport_failure() -> None:
    events = (_confirmed_event("evt_001"),)
    gemini = _make_director(_FailTransport())
    fallback = FallbackDirector(gemini=gemini)
    script = fallback.compose(events)
    # fell back to RuleBasedDirector
    assert script.metadata.composer == "rule_based"


def test_fallback_director_produces_valid_script_after_fallback() -> None:
    events = (
        _confirmed_event("evt_001", requested_start_sec=0.0, requested_end_sec=30.0),
        _confirmed_event("evt_002", requested_start_sec=100.0, requested_end_sec=130.0),
    )
    gemini = _make_director(_FailTransport())
    fallback = FallbackDirector(gemini=gemini)
    script = fallback.compose(events)

    assert isinstance(script, DirectorScript)
    assert len(script.scenes) >= 1
    all_ids = [c.event_id for s in script.scenes for c in s.clips]
    assert len(all_ids) == len(set(all_ids))


def test_fallback_director_propagates_value_error() -> None:
    """ValueError (bad input) must propagate, not be swallowed as a fallback."""
    events = (_unconfirmed_event("evt_bad"),)
    gemini = _make_director(_OkTransport(()))
    fallback = FallbackDirector(gemini=gemini)
    with pytest.raises(ValueError, match="evidence_confirmed=False"):
        fallback.compose(events)


def test_fallback_director_fallback_after_bad_json() -> None:
    events = (_confirmed_event("evt_001"),)
    gemini = _make_director(_BadJsonTransport())
    fallback = FallbackDirector(gemini=gemini)
    script = fallback.compose(events)
    assert script.metadata.composer == "rule_based"


def test_fallback_director_fallback_after_unknown_event_id() -> None:
    events = (_confirmed_event("evt_001"),)
    gemini = _make_director(_UnknownEventTransport())
    fallback = FallbackDirector(gemini=gemini)
    script = fallback.compose(events)
    assert script.metadata.composer == "rule_based"


# ---------------------------------------------------------------------------
# 27. FallbackDirector — evidence state not changed
# ---------------------------------------------------------------------------

def test_fallback_director_does_not_change_evidence_after_fallback() -> None:
    events = (_confirmed_event("evt_001"),)
    before = events[0].evidence_confirmed
    gemini = _make_director(_FailTransport())
    FallbackDirector(gemini=gemini).compose(events)
    assert events[0].evidence_confirmed == before
