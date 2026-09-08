"""Synthetic-fixture tests for app.config.load_local_environment.

No real .env, credential, or secret value is used anywhere here -- every
KEY/VALUE pair below is invented for the test. `load_local_environment` is
read by more than a dozen modules (agent runtime, MCP, web) as their one
shared way to read a local, git-ignored `.env` file, but every one of those
callers monkeypatches it away rather than exercising the real parser, so
the parsing rules themselves (comments, quoting, malformed lines) had no
direct coverage before this file.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.config import load_local_environment


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_local_environment(tmp_path / "does-not-exist.env") == {}


def test_empty_file_returns_empty(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    assert load_local_environment(env_file) == {}


def test_a_directory_at_the_path_is_not_a_file(tmp_path: Path) -> None:
    # is_file() is false for a directory -- same "no config" result as a
    # missing path, not an error.
    directory = tmp_path / ".env"
    directory.mkdir()
    assert load_local_environment(directory) == {}


def test_reads_a_simple_key_value_pair(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EXAMPLE_TOKEN=abc123\n", encoding="utf-8")
    assert load_local_environment(env_file) == {"EXAMPLE_TOKEN": "abc123"}


def test_skips_comment_lines(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("# a comment\nEXAMPLE_TOKEN=abc123\n", encoding="utf-8")
    assert load_local_environment(env_file) == {"EXAMPLE_TOKEN": "abc123"}


def test_skips_blank_and_whitespace_only_lines(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("\n   \nEXAMPLE_TOKEN=abc123\n", encoding="utf-8")
    assert load_local_environment(env_file) == {"EXAMPLE_TOKEN": "abc123"}


def test_skips_a_line_without_an_equals_sign(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("not-a-valid-line\nEXAMPLE_TOKEN=abc123\n", encoding="utf-8")
    assert load_local_environment(env_file) == {"EXAMPLE_TOKEN": "abc123"}


def test_skips_a_line_whose_name_is_empty_after_stripping(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("  =nameless\nEXAMPLE_TOKEN=abc123\n", encoding="utf-8")
    assert load_local_environment(env_file) == {"EXAMPLE_TOKEN": "abc123"}


def test_strips_surrounding_whitespace_on_the_whole_line_name_and_value(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("  EXAMPLE_TOKEN = abc123  \n", encoding="utf-8")
    assert load_local_environment(env_file) == {"EXAMPLE_TOKEN": "abc123"}


def test_only_the_first_equals_sign_splits_name_from_value(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EXAMPLE_URL=https://example.test/path?a=b\n", encoding="utf-8")
    assert load_local_environment(env_file) == {"EXAMPLE_URL": "https://example.test/path?a=b"}


def test_strips_matching_double_quotes_from_the_value(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('EXAMPLE_TOKEN="abc123"\n', encoding="utf-8")
    assert load_local_environment(env_file) == {"EXAMPLE_TOKEN": "abc123"}


def test_strips_matching_single_quotes_from_the_value(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EXAMPLE_TOKEN='abc123'\n", encoding="utf-8")
    assert load_local_environment(env_file) == {"EXAMPLE_TOKEN": "abc123"}


def test_a_value_that_is_only_a_pair_of_double_quotes_becomes_empty(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('EXAMPLE_TOKEN=""\n', encoding="utf-8")
    assert load_local_environment(env_file) == {"EXAMPLE_TOKEN": ""}


def test_an_internal_apostrophe_is_not_stripped(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('EXAMPLE_NOTE="it\'s fine"\n', encoding="utf-8")
    assert load_local_environment(env_file) == {"EXAMPLE_NOTE": "it's fine"}


def test_later_lines_override_earlier_ones_for_the_same_name(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EXAMPLE_TOKEN=first\nEXAMPLE_TOKEN=second\n", encoding="utf-8")
    assert load_local_environment(env_file) == {"EXAMPLE_TOKEN": "second"}


def test_reads_multiple_distinct_names(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "EXAMPLE_ONE=first\nEXAMPLE_TWO=second\n",
        encoding="utf-8",
    )
    assert load_local_environment(env_file) == {
        "EXAMPLE_ONE": "first",
        "EXAMPLE_TWO": "second",
    }


def test_reads_non_ascii_values_as_utf8(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EXAMPLE_LABEL=とある値\n", encoding="utf-8")
    assert load_local_environment(env_file) == {"EXAMPLE_LABEL": "とある値"}


def test_default_path_is_dot_env_relative_to_the_current_directory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("EXAMPLE_TOKEN=abc123\n", encoding="utf-8")
    assert load_local_environment() == {"EXAMPLE_TOKEN": "abc123"}


def test_does_not_touch_the_process_environment(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    marker = "RIDE_STORYTELLER_TEST_CONFIG_MARKER"
    assert marker not in os.environ
    env_file.write_text(f"{marker}=abc123\n", encoding="utf-8")
    load_local_environment(env_file)
    assert marker not in os.environ
