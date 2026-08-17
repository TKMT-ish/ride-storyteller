from collections.abc import Mapping

import pytest

from app.agents import (
    GeminiStoryCopyError,
    GeminiStoryCopyGenerator,
    StoryOutputLanguage,
)
from app.demo import build_demo_story_plan


def _response() -> dict[str, object]:
    return {
        "title": "A Synthetic Ride",
        "chapters": [
            {
                "chapter_id": "chapter_01",
                "title": "Departure",
                "selection_rationale": "Establishes the start of the ride.",
            },
            {
                "chapter_id": "chapter_02",
                "title": "Changing Scenery",
                "selection_rationale": "Marks a GPS-derived transition.",
            },
            {
                "chapter_id": "chapter_03",
                "title": "Arrival",
                "selection_rationale": "Closes the route.",
            },
        ],
    }


class RecordingTransport:
    def __init__(self, response: Mapping[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def generate_story_copy(
        self,
        *,
        prompt: str,
        story_payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        self.calls.append({"prompt": prompt, "story_payload": dict(story_payload)})
        return self.response


def test_story_copy_generates_english_without_sending_private_identifiers() -> None:
    transport = RecordingTransport(_response())
    source = build_demo_story_plan()

    generated = GeminiStoryCopyGenerator(transport).generate(
        source,
        output_language=StoryOutputLanguage.ENGLISH,
        synthetic_input=True,
    )

    assert generated.language is StoryOutputLanguage.ENGLISH
    assert generated.title == "A Synthetic Ride"
    assert [chapter.chapter_id for chapter in generated.chapters] == [
        chapter.chapter_id for chapter in source.chapters
    ]
    assert generated.generation_provider == "gemini"
    assert len(transport.calls) == 1
    request = transport.calls[0]
    assert "in English" in str(request["prompt"])
    serialized = repr(request["story_payload"])
    for forbidden in (
        "event_id",
        "latitude",
        "longitude",
        "asset_name",
        "source_uri",
        "/Users/",
        "gs://",
        "box://",
    ):
        assert forbidden not in serialized


def test_story_copy_refuses_non_synthetic_input_before_transport_call() -> None:
    transport = RecordingTransport(_response())

    with pytest.raises(ValueError, match="synthetic input only"):
        GeminiStoryCopyGenerator(transport).generate(
            build_demo_story_plan(),
            output_language=StoryOutputLanguage.ENGLISH,
            synthetic_input=False,
        )

    assert transport.calls == []


@pytest.mark.parametrize(
    "mutate",
    (
        lambda response: response.update(extra="not allowed"),
        lambda response: response["chapters"].pop(),  # type: ignore[union-attr]
        lambda response: response["chapters"][0].update(  # type: ignore[index,union-attr]
            chapter_id="changed"
        ),
        lambda response: response["chapters"][0].update(  # type: ignore[index,union-attr]
            title=""
        ),
        lambda response: response["chapters"][0].update(  # type: ignore[index,union-attr]
            unexpected="field"
        ),
    ),
)
def test_story_copy_rejects_responses_that_change_or_weaken_structure(
    mutate: object,
) -> None:
    response = _response()
    mutate(response)  # type: ignore[operator]

    with pytest.raises(GeminiStoryCopyError, match="invalid structured story copy"):
        GeminiStoryCopyGenerator(RecordingTransport(response)).generate(
            build_demo_story_plan(),
            output_language=StoryOutputLanguage.ENGLISH,
            synthetic_input=True,
        )


def test_story_copy_hides_transport_failure_details() -> None:
    class FailingTransport:
        def generate_story_copy(self, **_kwargs: object) -> Mapping[str, object]:
            raise RuntimeError("sensitive provider response")

    with pytest.raises(GeminiStoryCopyError, match="unavailable") as caught:
        GeminiStoryCopyGenerator(FailingTransport()).generate(
            build_demo_story_plan(),
            output_language=StoryOutputLanguage.ENGLISH,
            synthetic_input=True,
        )

    assert "sensitive provider response" not in str(caught.value)
