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
