"""Synthetic-fixture tests for fitting chapter text to the E-4 lower third."""

from __future__ import annotations

import pytest

from app.lower_third_text import (
    MAX_BODY_CHARS,
    MAX_TITLE_CHARS,
    LowerThirdText,
    LowerThirdTextError,
    display_width,
    fit_body,
    fit_lower_third_text,
    fit_title,
)

# --- fit_title ---------------------------------------------------------------


def test_title_within_limit_is_returned_unchanged() -> None:
    assert fit_title("長い下り") == "長い下り"


def test_title_within_limit_is_only_stripped() -> None:
    assert fit_title("  長い下り  ") == "長い下り"


def test_title_over_limit_is_truncated_with_ellipsis() -> None:
    title = "あ" * (MAX_TITLE_CHARS + 5)
    fitted = fit_title(title)
    assert len(fitted) == MAX_TITLE_CHARS
    assert fitted.endswith("…")
    assert fitted[:-1] == "あ" * (MAX_TITLE_CHARS - 1)


def test_title_exactly_at_limit_is_untouched() -> None:
    title = "あ" * MAX_TITLE_CHARS
    assert fit_title(title) == title


def test_title_fit_never_exceeds_a_tiny_custom_limit() -> None:
    fitted = fit_title("曲がりくねった道", max_chars=3)
    assert len(fitted) <= 3


def test_title_fit_with_limit_at_or_below_ellipsis_length_hard_cuts() -> None:
    # No room for an ellipsis at all: cut straight, no ellipsis appended.
    assert fit_title("曲がりくねった道", max_chars=1) == "曲"


def test_title_fit_rejects_non_positive_limit() -> None:
    with pytest.raises(LowerThirdTextError):
        fit_title("出発", max_chars=0)


def test_title_blank_after_strip_fits_within_any_limit_without_raising() -> None:
    # fit_title alone does not enforce "a title must say something" -- that
    # invariant lives on LowerThirdText.__post_init__. A blank title's width
    # is 0, which always fits, so fit_title returns "" rather than raising;
    # callers that go through fit_lower_third_text still get the invariant
    # enforced once the result reaches LowerThirdText (see below).
    assert fit_title("   ") == ""


def test_title_fit_with_fractional_limit_still_leaves_room_for_the_ellipsis() -> None:
    # _ELLIPSIS_WIDTH is reserved as a full 1.0 even though the ellipsis
    # glyph itself measures as ambiguous-width (0.5) under display_width --
    # a deliberate over-reservation (module comment: "however a font sets
    # it"), so the fitted text should land under the limit, not exactly at
    # it, once a fractional max_chars forces the ellipsis branch.
    fitted = fit_title("abcd", max_chars=1.5)
    assert fitted == "a…"
    assert display_width(fitted) <= 1.5


# --- fit_body -----------------------------------------------------------------


def test_body_within_limit_joins_every_part() -> None:
    assert fit_body(["出発から15分", "1.4km"]) == "出発から15分 · 1.4km"


def test_body_over_limit_drops_least_essential_parts_first() -> None:
    parts = ["出発から3時間06分", "142.0km", "海抜815m → 67m"]
    fitted = fit_body(parts)
    assert len(fitted) <= MAX_BODY_CHARS
    # The most essential part (elapsed time) survives; the least essential
    # (elevation) is what gets dropped first.
    assert "出発から3時間06分" in fitted
    assert "海抜815m" not in fitted


def test_body_drop_stops_as_soon_as_it_fits() -> None:
    # All three parts fit together once they're this short -- nothing should
    # be dropped that didn't need to be.
    fitted = fit_body(["9時", "10km", "+50m"])
    assert fitted == "9時 · 10km · +50m"


def test_body_never_drops_the_first_part() -> None:
    huge_second_part = "あ" * 50
    fitted = fit_body(["9時", huge_second_part])
    assert fitted.startswith("9時")


def test_body_truncates_first_part_when_it_alone_overruns() -> None:
    huge_first_part = "あ" * (MAX_BODY_CHARS + 10)
    fitted = fit_body([huge_first_part])
    assert len(fitted) == MAX_BODY_CHARS
    assert fitted.endswith("…")


def test_body_ignores_blank_and_none_parts() -> None:
    assert fit_body(["9時", "", "  ", "10km"]) == "9時 · 10km"


def test_body_rejects_all_blank_parts() -> None:
    with pytest.raises(LowerThirdTextError):
        fit_body(["", "   "])


def test_body_rejects_empty_parts_list() -> None:
    with pytest.raises(LowerThirdTextError):
        fit_body([])


def test_body_honours_a_custom_separator() -> None:
    assert fit_body(["a", "b"], separator=" / ") == "a / b"


def test_body_rejects_a_zero_max_chars() -> None:
    # fit_body has no explicit guard of its own; a non-positive max_chars
    # only surfaces once dropping parts bottoms out at one and the fallback
    # to fit_title raises on its behalf. Fixed here so that guard staying
    # reachable through fit_body isn't an accident of the two functions'
    # current wiring.
    with pytest.raises(LowerThirdTextError):
        fit_body(["9時", "10km"], max_chars=0)


def test_body_rejects_a_negative_max_chars() -> None:
    with pytest.raises(LowerThirdTextError):
        fit_body(["9時", "10km"], max_chars=-1)


def test_body_single_part_exactly_at_the_limit_is_not_truncated() -> None:
    part = "あ" * MAX_BODY_CHARS
    fitted = fit_body([part])
    assert fitted == part
    assert "…" not in fitted


def test_body_treats_a_literal_none_element_like_a_blank_part() -> None:
    assert fit_body(["9時", None, "10km"]) == "9時 · 10km"


# --- fit_lower_third_text ------------------------------------------------------


def test_fit_lower_third_text_combines_both_fits() -> None:
    result = fit_lower_third_text(
        "曲がりくねった道が続く峠道",
        ["出発から3時間06分", "142.0km", "海抜815m → 67m"],
    )
    assert isinstance(result, LowerThirdText)
    assert len(result.title) <= MAX_TITLE_CHARS
    assert len(result.body) <= MAX_BODY_CHARS


def test_fit_lower_third_text_honours_custom_limits() -> None:
    result = fit_lower_third_text(
        "長い下り",
        ["9時", "10km"],
        max_title_chars=3,
        max_body_chars=5,
    )
    assert display_width(result.title) <= 3
    assert display_width(result.body) <= 5


def test_fit_lower_third_text_raises_when_every_body_part_is_blank() -> None:
    # fit_body's own error (empty-parts) surfaces before the combined result
    # ever reaches LowerThirdText's post-init check.
    with pytest.raises(LowerThirdTextError):
        fit_lower_third_text("出発", ["", "   "])


def test_fit_lower_third_text_raises_when_title_is_blank_even_if_body_fits() -> None:
    # A blank title fits fit_title's own width check (see
    # test_title_blank_after_strip_fits_within_any_limit_without_raising),
    # so it is LowerThirdText's post-init guard -- not fit_title -- that
    # this depends on to keep an empty title from ever reaching the overlay.
    with pytest.raises(LowerThirdTextError):
        fit_lower_third_text("   ", ["9時", "10km"])


# --- LowerThirdText invariants --------------------------------------------------


def test_lower_third_text_accepts_text_within_limits() -> None:
    text = LowerThirdText(title="長い下り", body="9時 · 10km")
    assert text.title == "長い下り"
    assert text.body == "9時 · 10km"


def test_lower_third_text_rejects_title_over_limit() -> None:
    with pytest.raises(LowerThirdTextError):
        LowerThirdText(title="あ" * (MAX_TITLE_CHARS + 1), body="9時")


def test_lower_third_text_rejects_body_over_limit() -> None:
    with pytest.raises(LowerThirdTextError):
        LowerThirdText(title="出発", body="あ" * (MAX_BODY_CHARS + 1))


def test_lower_third_text_rejects_empty_title() -> None:
    with pytest.raises(LowerThirdTextError):
        LowerThirdText(title="", body="9時")


def test_lower_third_text_rejects_blank_title() -> None:
    with pytest.raises(LowerThirdTextError):
        LowerThirdText(title="   ", body="9時")


def test_lower_third_text_rejects_empty_body() -> None:
    with pytest.raises(LowerThirdTextError):
        LowerThirdText(title="出発", body="")


def test_lower_third_text_rejects_blank_body() -> None:
    # Symmetric with test_lower_third_text_rejects_blank_title: whitespace
    # alone must not pass the "or" guard on either field.
    with pytest.raises(LowerThirdTextError):
        LowerThirdText(title="出発", body="   ")


def test_latin_letters_take_half_the_room_of_kanji() -> None:
    """A title in place names -- "Ashton → Karāwera" -- fits where twelve kanji would."""
    assert display_width("Ashton → Karāwera") <= 12
    assert fit_title("Ashton → Karāwera") == "Ashton → Karāwera"
    assert display_width("リヒテンシュタイン") == 9


def test_display_width_of_empty_string_is_zero() -> None:
    assert display_width("") == 0.0


def test_display_width_counts_halfwidth_katakana_as_half_width() -> None:
    # Halfwidth katakana (U+FF61-FF9F) is a distinct Unicode block from the
    # full-width katakana used elsewhere in these fixtures; east_asian_width
    # reports it "H" (halfwidth), not "W"/"F", so it must count as narrow
    # like a Latin letter rather than as a kanji-width character.
    assert display_width("ｱｲｳ") == 1.5
