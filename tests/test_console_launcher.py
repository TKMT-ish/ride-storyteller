"""The double-click launcher for the console must exist, parse, and point at the right things.

The owner asked how to see the film and what "the console" was; the answer
must be one file to double-click. Nothing here runs the server.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "scripts" / "open-console.command"


def test_the_launcher_exists_and_is_executable() -> None:
    assert LAUNCHER.is_file()
    assert os.access(LAUNCHER, os.X_OK), "Finder runs a .command only when it is executable"


def test_the_launcher_parses_as_a_shell_script() -> None:
    result = subprocess.run(["bash", "-n", str(LAUNCHER)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_launcher_starts_the_console_module_and_opens_the_private_page() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "-m app.web.server" in text
    assert "/private-journey" in text
    assert "127.0.0.1" in text, "the console listens on this machine only"
    assert "set -euo pipefail" in text
