"""Run one synthetic-only Gemini story-copy request and print safe metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.agents import (
    GeminiStoryCopyGenerator,
    StoryOutputLanguage,
    VertexAIGeminiStoryCopyTransport,
)
from app.demo import build_demo_story_plan


@dataclass(frozen=True)
class SyntheticStoryCopyProbe:
    model: str
    language: str
    chapter_count: int
    response_received: bool
    synthetic_input: bool = True
    private_data_used: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "language": self.language,
            "chapter_count": self.chapter_count,
            "response_received": self.response_received,
            "synthetic_input": self.synthetic_input,
            "private_data_used": self.private_data_used,
        }


def run_synthetic_story_copy_probe() -> SyntheticStoryCopyProbe:
    transport = VertexAIGeminiStoryCopyTransport.from_environment()
    source = build_demo_story_plan(StoryOutputLanguage.JAPANESE)
    generated = GeminiStoryCopyGenerator(transport).generate(
        source,
        output_language=StoryOutputLanguage.ENGLISH,
        synthetic_input=True,
    )
    return SyntheticStoryCopyProbe(
        model=transport.model,
        language=generated.language.value,
        chapter_count=len(generated.chapters),
        response_received=bool(generated.title and generated.chapters),
    )


def main() -> None:
    result = run_synthetic_story_copy_probe()
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
