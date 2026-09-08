"""Synthetic-fixture tests for buying the model's order over near-equal windows.

The comparator and the uploader are stubs; nothing reaches Google. What is
held is which windows get compared, how groups become one global order,
that the order is written down and read back, and that a judgement no
model was paid for is never ranked.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.agents import StoryOutputLanguage
from app.analysis_ranking import (
    DEFAULT_GROUP_SIZE,
    WINDOW_RANKING_FILE_NAME,
    AnalysisRankingError,
    WindowRanking,
    load_window_ranking,
    plan_ranking_cost,
    rank_windows,
    ranks_for,
    windows_worth_ranking,
    write_window_ranking,
)
from app.analysis_record import (
    VIDEO_ANALYSIS_RECORD_FILE_NAME,
    AnalysedEvent,
    VideoAnalysisRecord,
    write_video_analysis_record,
)
from app.analysis_run import PROXY_DIRECTORY_NAME, plan_analysis_run
from app.contracts import VideoAnalysis
from app.local_pipeline import LocalPipelineInputs
from app.video import VideoCatalog, VideoCatalogEntry

_RIDE_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _gpx(path: Path, *, span_s: float = 4 * 3600.0, point_count: int = 60) -> Path:
    step = span_s / (point_count - 1)
    points = "".join(
        '<trkpt lat="{lat:.6f}" lon="{lon:.6f}"><ele>100</ele><time>{t}</time></trkpt>'.format(
            lat=35.0 + 0.001 * i,
            lon=139.0 + 0.001 * i,
            t=(_RIDE_START + timedelta(seconds=step * i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        for i in range(point_count)
    )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="t" '
        'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        + points
        + "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    return path


def _package(root: Path, *, recording_s: float = 900.0) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "synthetic.mp4").write_bytes(b"a recording")
    inputs = LocalPipelineInputs(
        gpx_path=_gpx(root / "ride.gpx").resolve(),
        video_root=root.resolve(),
        video_to_gps_offset_s=0.0,
        target_duration_s=300.0,
        output_language=StoryOutputLanguage.JAPANESE,
    )
    (root / "local-pipeline-inputs.json").write_text(json.dumps(inputs.to_dict()), encoding="utf-8")
    catalog = VideoCatalog(
        entries=(
            VideoCatalogEntry(
                asset_id="asset-1",
                file_name="synthetic.mp4",
                recorded_start_time=_RIDE_START + timedelta(seconds=600),
                duration_s=recording_s,
            ),
        ),
        video_to_gps_offset_s=0.0,
    )
    (root / "local-video-catalog.json").write_text(json.dumps(catalog.to_dict()), encoding="utf-8")
    return root


def _judge(package: Path, scores: dict[int, float], *, provider: str = "gemini") -> list[str]:
    """Write a judgement whose i-th candidate scores as given (others 0.3)."""
    plan = plan_analysis_run(package)
    proxies = package / PROXY_DIRECTORY_NAME
    proxies.mkdir(exist_ok=True)
    analysed = []
    for index, candidate in enumerate(plan.candidates):
        score = scores.get(index, 0.3)
        (proxies / f"{candidate.event_id}.mp4").write_bytes(b"copy")
        analysed.append(
            AnalysedEvent(
                event_id=candidate.event_id,
                analysis=VideoAnalysis(
                    asset_id=candidate.asset_id,
                    start_offset_s=candidate.start_offset_s,
                    end_offset_s=candidate.end_offset_s,
                    visual_description="a road",
                    road_type="highway",
                    scenery_tags=("sky",),
                    weather_visible="clear",
                    visual_interest_score=score,
                    story_relevance_score=score,
                    confidence=0.9,
                    analysis_provider=provider,
                ),
            )
        )
    write_video_analysis_record(
        package / VIDEO_ANALYSIS_RECORD_FILE_NAME,
        VideoAnalysisRecord(tuple(analysed)),
        overwrite=True,
    )
    return [c.event_id for c in plan.candidates]


def _upload(proxy: Path, event_id: str) -> str:
    return f"gs://bucket/{event_id}.mp4"


# --- which windows are worth comparing ------------------------------------------


def test_the_windows_around_the_cut_are_compared_not_only_the_best(tmp_path: Path) -> None:
    """The decision is made at the last slot, where the ties are."""
    package = _package(tmp_path / "package")
    ids = _judge(package, {0: 0.9, 1: 0.7, 2: 0.66, 3: 0.66, 4: 0.66, 5: 0.5})

    # Three slots: the cut is the third best (0.66); everything down to
    # 0.66 - band is worth comparing, including the tied fourth and fifth.
    assert windows_worth_ranking(package, band=0.0, slots=3) == [
        ids[0],
        ids[1],
        ids[2],
        ids[3],
        ids[4],
    ]
    assert windows_worth_ranking(package, band=0.0, slots=1) == [ids[0]]
    assert windows_worth_ranking(package, band=0.2, slots=3) == ids[:6]


def test_a_wide_tie_is_capped_so_it_costs_a_few_yen(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=2_000.0)
    ids = _judge(package, {i: 0.66 for i in range(40)})

    assert windows_worth_ranking(package, band=0.0, slots=20, max_windows=25) == ids[:25]


def test_a_judgement_nobody_bought_is_not_ranked(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _judge(package, {0: 0.7, 1: 0.7}, provider="stub-dry-run")

    with pytest.raises(AnalysisRankingError, match="not bought"):
        windows_worth_ranking(package)


# --- groups become one global order ---------------------------------------------


def test_the_comparator_sees_near_equals_and_its_order_becomes_the_rank(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    ids = _judge(package, {0: 0.7, 1: 0.7, 2: 0.7, 3: 0.7})
    seen: list[list[str]] = []

    def compare(pairs):
        seen.append([e for e, _ in pairs])
        return [e for e, _ in reversed(pairs)]  # the model prefers the later ones

    path = rank_windows(package, compare=compare, upload=_upload, slots=4)

    ranking = load_window_ranking(path)
    assert seen == [[ids[0], ids[1], ids[2], ids[3]]]
    assert ranking.ranks == {ids[3]: 1, ids[2]: 2, ids[1]: 3, ids[0]: 4}
    assert ranking.provider == "gemini"


def test_groups_are_formed_in_score_order_and_ranked_globally(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=2_000.0)
    top = {i: 0.7 for i in range(15)}  # fifteen near-equals: a group of ten and one of five
    ids = _judge(package, top)
    groups: list[int] = []

    def compare(pairs):
        groups.append(len(pairs))
        return [e for e, _ in pairs]

    ranking = load_window_ranking(rank_windows(package, compare=compare, upload=_upload, slots=15))

    assert groups == [DEFAULT_GROUP_SIZE, 5]
    assert [ranking.ranks[i] for i in ids[:15]] == list(range(1, 16))


def test_a_comparator_that_drops_or_invents_a_window_is_refused(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    ids = _judge(package, {0: 0.7, 1: 0.7, 2: 0.7})

    with pytest.raises(AnalysisRankingError, match="incomplete order"):
        rank_windows(package, compare=lambda pairs: [ids[0], ids[1]], upload=_upload, slots=3)
    with pytest.raises(AnalysisRankingError, match="incomplete order"):
        rank_windows(
            package, compare=lambda pairs: [ids[0], ids[1], "footage-x"], upload=_upload, slots=3
        )
    assert not (package / WINDOW_RANKING_FILE_NAME).exists()


def test_a_group_answered_with_a_hole_is_asked_once_more(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    ids = _judge(package, {0: 0.7, 1: 0.7, 2: 0.7})
    calls: list[int] = []

    def flaky(pairs):
        calls.append(len(pairs))
        if len(calls) == 1:
            raise RuntimeError("Vertex AI Gemini returned an incomplete ranking")
        return [e for e, _ in pairs]

    ranking = load_window_ranking(rank_windows(package, compare=flaky, upload=_upload, slots=3))

    assert calls == [3, 3], "the same group, asked twice"
    assert [ranking.ranks[i] for i in ids[:3]] == [1, 2, 3]


def test_a_group_that_fails_twice_is_left_unranked_and_the_rest_still_count(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=2_000.0)
    ids = _judge(package, {i: 0.7 for i in range(15)})  # a group of ten, then five

    def second_group_broken(pairs):
        if len(pairs) == 5:
            raise RuntimeError("Vertex AI Gemini returned an incomplete ranking")
        return [e for e, _ in pairs]

    ranking = load_window_ranking(
        rank_windows(package, compare=second_group_broken, upload=_upload, slots=15)
    )

    assert [ranking.ranks[i] for i in ids[:10]] == list(range(1, 11))
    assert all(i not in ranking.ranks for i in ids[10:15]), "the broken group stays unranked"


def test_an_error_that_is_not_a_hole_in_the_answer_is_not_swallowed(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _judge(package, {0: 0.7, 1: 0.7, 2: 0.7})

    def broken(pairs):
        raise RuntimeError("the network went away")

    with pytest.raises(RuntimeError, match="network"):
        rank_windows(package, compare=broken, upload=_upload, slots=3)


def test_a_missing_copy_stops_the_ranking_before_anything_is_bought(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    ids = _judge(package, {0: 0.7, 1: 0.7})
    (package / PROXY_DIRECTORY_NAME / f"{ids[1]}.mp4").unlink()
    called: list = []

    with pytest.raises(AnalysisRankingError, match="copy is missing"):
        rank_windows(package, compare=lambda pairs: called.append(1) or [], upload=_upload, slots=2)
    assert called == []


def test_fewer_than_two_near_equals_is_nothing_to_rank(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _judge(package, {0: 0.9})

    with pytest.raises(AnalysisRankingError, match="fewer than two"):
        rank_windows(package, compare=lambda pairs: [], upload=_upload, band=0.05, slots=1)


# --- written down, read back, and refused when not bought -----------------------


def test_a_ranking_is_read_back_by_the_film_and_a_stub_one_is_refused(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    assert ranks_for(package) is None

    write_window_ranking(
        package / WINDOW_RANKING_FILE_NAME, WindowRanking(provider="gemini", ranks={"a": 1, "b": 2})
    )
    assert ranks_for(package) == {"a": 1, "b": 2}

    write_window_ranking(
        package / WINDOW_RANKING_FILE_NAME,
        WindowRanking(provider="stub", ranks={"a": 1}),
        overwrite=True,
    )
    with pytest.raises(AnalysisRankingError, match="not bought"):
        ranks_for(package)


def test_a_ranking_must_be_one_to_n_without_gaps() -> None:
    with pytest.raises(ValueError, match="without gaps"):
        WindowRanking(provider="gemini", ranks={"a": 1, "b": 3})
    with pytest.raises(ValueError, match="needs a provider"):
        WindowRanking(provider="", ranks={"a": 1})


def test_buying_a_ranking_twice_needs_saying_so(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    _judge(package, {0: 0.7, 1: 0.7})
    rank_windows(package, compare=lambda pairs: [e for e, _ in pairs], upload=_upload, slots=2)

    with pytest.raises(FileExistsError):
        rank_windows(package, compare=lambda pairs: [e for e, _ in pairs], upload=_upload, slots=2)


def test_the_cost_of_a_ranking_is_small_and_sends_nothing(tmp_path: Path) -> None:
    package = _package(tmp_path / "package", recording_s=2_000.0)
    _judge(package, {i: 0.7 for i in range(15)})

    cost = plan_ranking_cost(package, slots=15)

    assert cost["windows_to_rank"] == 15
    assert cost["groups"] == 2
    assert 0 < cost["estimated_jpy"] < 5.0


def test_importing_the_ranking_module_reaches_no_google_library() -> None:
    import ast

    tree = ast.parse(Path("app/analysis_ranking.py").read_text(encoding="utf-8"))
    names = [a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names] + [
        n.module or "" for n in tree.body if isinstance(n, ast.ImportFrom)
    ]
    assert not any(name.startswith("google") for name in names)


# --- selection uses the rank first among ties -------------------------------------


def test_selection_takes_the_model_ranked_window_first_among_ties() -> None:
    from app.gemini_selection import JudgedCandidate, select_judged_candidates

    def judged(event_id: str, at_s: float, road: str) -> JudgedCandidate:
        return JudgedCandidate(
            event_id=event_id,
            start_time=_RIDE_START + timedelta(seconds=at_s),
            duration_s=12.0,
            analysis=VideoAnalysis(
                asset_id="asset-1",
                start_offset_s=at_s,
                end_offset_s=at_s + 12.0,
                visual_description="a road",
                road_type=road,
                scenery_tags=("sky",),
                weather_visible="clear",
                visual_interest_score=0.6,
                story_relevance_score=0.7,
                confidence=0.9,
                analysis_provider="gemini",
            ),
        )

    candidates = (judged("early", 0, "highway"), judged("later", 600, "street"))

    # Without a rank the heuristics take the earliest of two novel kinds.
    assert select_judged_candidates(candidates, footage_target_s=12.0).selected_event_ids == (
        "early",
    )
    # With the model's rank, its preference wins the tie.
    assert select_judged_candidates(
        candidates, footage_target_s=12.0, ranks={"later": 1, "early": 2}
    ).selected_event_ids == ("later",)


# --- the transport's ranking call, with a fake client -----------------------------


def test_the_transport_labels_clips_and_maps_the_answer_back() -> None:
    from app.video.vertex_transport import VertexAIGeminiVideoTransport

    class _Response:
        parsed = {"order": ["c", "A", "B"]}

    class _Models:
        def __init__(self) -> None:
            self.calls: list = []

        def generate_content(self, *, model, contents, config):
            self.calls.append((model, contents, config))
            return _Response()

    class _Client:
        def __init__(self) -> None:
            self.models = _Models()

    client = _Client()
    transport = VertexAIGeminiVideoTransport(client, model="gemini-2.5-flash")

    labels = transport.rank_clips(
        source_uris=["gs://b/one.mp4", "gs://b/two.mp4", "gs://b/three.mp4"],
        mime_type="video/mp4",
        prompt="order them",
    )

    assert labels == ["C", "A", "B"]
    contents = client.models.calls[0][1]
    assert contents[0] == "Window A:" and contents[2] == "Window B:" and contents[4] == "Window C:"
    assert contents[-1] == "order them"


def test_the_transport_refuses_an_incomplete_order() -> None:
    from app.video.gemini_client import GeminiVideoAnalysisError
    from app.video.vertex_transport import VertexAIGeminiVideoTransport

    class _Response:
        parsed = {"order": ["A", "A"]}

    class _Models:
        def generate_content(self, **kwargs):
            return _Response()

    class _Client:
        models = _Models()

    transport = VertexAIGeminiVideoTransport(_Client(), model="m")
    with pytest.raises(GeminiVideoAnalysisError, match="incomplete ranking"):
        transport.rank_clips(
            source_uris=["gs://b/1.mp4", "gs://b/2.mp4"], mime_type="video/mp4", prompt="p"
        )
    with pytest.raises(ValueError, match="between two and ten"):
        transport.rank_clips(source_uris=["gs://b/1.mp4"], mime_type="video/mp4", prompt="p")
    with pytest.raises(ValueError, match="between two and ten"):
        transport.rank_clips(
            source_uris=[f"gs://b/{i}.mp4" for i in range(11)], mime_type="video/mp4", prompt="p"
        )


def test_the_transport_reads_window_c_as_c() -> None:
    """The model answers "Window C" more often than "C"."""
    from app.video.vertex_transport import VertexAIGeminiVideoTransport

    class _Response:
        parsed = {"order": ["Window B", "window a"]}

    class _Models:
        def generate_content(self, **kwargs):
            return _Response()

    class _Client:
        models = _Models()

    transport = VertexAIGeminiVideoTransport(_Client(), model="m")
    assert transport.rank_clips(
        source_uris=["gs://b/1.mp4", "gs://b/2.mp4"], mime_type="video/mp4", prompt="p"
    ) == ["B", "A"]
