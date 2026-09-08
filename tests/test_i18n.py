import re
from pathlib import Path

import pytest

from app.web.i18n import (
    DEFAULT_UI_LANGUAGE,
    UiLanguage,
    configured_default_language,
    copy_for,
    resolve_language,
    translation_keys,
)
from app.web.server import application

_PLACEHOLDER = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")


def _get(path: str, query: str = "") -> str:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(
        application(
            {"PATH_INFO": path, "QUERY_STRING": query, "REQUEST_METHOD": "GET"},
            start_response,
        )
    )
    assert captured["status"] == "200 OK"
    return body.decode()


def test_translation_dictionaries_have_identical_nonempty_keys() -> None:
    expected = translation_keys()

    assert expected
    for language in UiLanguage:
        copy = copy_for(language)
        assert set(copy) == expected
        assert all(value.strip() for value in copy.values())


def test_language_resolution_is_validated_and_japanese_fails_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RIDE_UI_DEFAULT_LANGUAGE", raising=False)

    assert DEFAULT_UI_LANGUAGE is UiLanguage.JAPANESE
    assert configured_default_language() is UiLanguage.JAPANESE
    assert resolve_language("en-US") is UiLanguage.ENGLISH
    assert resolve_language("ja_JP") is UiLanguage.JAPANESE
    assert resolve_language("unsupported") is UiLanguage.JAPANESE


def test_english_can_be_the_nonsecret_local_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIDE_UI_DEFAULT_LANGUAGE", "en")

    assert configured_default_language() is UiLanguage.ENGLISH
    assert resolve_language(None) is UiLanguage.ENGLISH
    assert resolve_language("ja") is UiLanguage.JAPANESE


def test_main_page_query_switches_to_english_and_preserves_inventory_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("RIDE_UI_DEFAULT_LANGUAGE", raising=False)

    page = _get("/", "lang=en")

    assert '<html lang="en">' in page
    assert "Run decision demo" in page
    assert "Agent Platform cloud synthetic demo" in page
    assert "Built with IBM Bob review" in page
    assert "Added Google ADK agent and tool wiring" in page
    assert "Open video folder inventory" in page
    assert 'href="/local-media-inventory?lang=en"' in page
    assert 'href="/?lang=ja"' in page


def test_english_page_requests_english_google_maps_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-browser-key")

    page = _get("/", "lang=en")

    assert "language=en" in page
    assert "key=test-browser-key" in page


def test_inventory_page_switches_to_english_without_external_scripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    page = _get("/local-media-inventory", "lang=en")

    assert '<html lang="en">' in page
    assert "Local video inventory" in page
    assert "Create inventory JSON" in page
    assert 'href="/?lang=en"' in page
    assert "maps.googleapis.com" not in page
    assert "fetch(" not in page


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("EN", UiLanguage.ENGLISH),
        ("En", UiLanguage.ENGLISH),
        ("en-GB", UiLanguage.ENGLISH),
        ("en_US", UiLanguage.ENGLISH),
        ("  en  ", UiLanguage.ENGLISH),
        ("en-", UiLanguage.ENGLISH),
        ("JA", UiLanguage.JAPANESE),
        ("ja-JP", UiLanguage.JAPANESE),
        ("ja_JP", UiLanguage.JAPANESE),
    ],
)
def test_resolve_language_normalizes_case_region_and_whitespace(
    raw: str, expected: UiLanguage
) -> None:
    assert resolve_language(raw) is expected


@pytest.mark.parametrize(
    "raw",
    [None, "", "   ", "fr", "-en", "123", "japanese", "en,us"],
)
def test_resolve_language_falls_back_to_configured_default_on_bad_input(
    raw: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RIDE_UI_DEFAULT_LANGUAGE", raising=False)

    assert resolve_language(raw) is DEFAULT_UI_LANGUAGE


def test_configured_default_language_ignores_invalid_env_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIDE_UI_DEFAULT_LANGUAGE", "not-a-real-language")

    assert configured_default_language() is DEFAULT_UI_LANGUAGE


def test_configured_default_language_ignores_blank_env_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIDE_UI_DEFAULT_LANGUAGE", "   ")

    assert configured_default_language() is DEFAULT_UI_LANGUAGE


def test_configured_default_language_reads_local_env_file_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RIDE_UI_DEFAULT_LANGUAGE", raising=False)
    (tmp_path / ".env").write_text('RIDE_UI_DEFAULT_LANGUAGE="en"\n', encoding="utf-8")

    assert configured_default_language() is UiLanguage.ENGLISH


def test_configured_default_language_prefers_process_env_over_local_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIDE_UI_DEFAULT_LANGUAGE", "ja")
    (tmp_path / ".env").write_text("RIDE_UI_DEFAULT_LANGUAGE=en\n", encoding="utf-8")

    assert configured_default_language() is UiLanguage.JAPANESE


def test_copy_for_returns_a_read_only_mapping() -> None:
    copy = copy_for(UiLanguage.ENGLISH)

    with pytest.raises(TypeError):
        copy["main.title"] = "tampered"  # type: ignore[index]


def test_translation_keys_matches_each_languages_key_set() -> None:
    keys = translation_keys()

    for language in UiLanguage:
        assert set(copy_for(language)) == keys


@pytest.mark.parametrize("key", sorted(translation_keys()))
def test_translation_placeholders_match_between_languages(key: str) -> None:
    ja_placeholders = set(_PLACEHOLDER.findall(copy_for(UiLanguage.JAPANESE)[key]))
    en_placeholders = set(_PLACEHOLDER.findall(copy_for(UiLanguage.ENGLISH)[key]))

    assert ja_placeholders == en_placeholders
