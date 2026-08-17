"""Local environment loading shared by optional external-service adapters."""

from __future__ import annotations

from pathlib import Path


def load_local_environment(path: Path = Path(".env")) -> dict[str, str]:
    """Read simple KEY=VALUE pairs without changing the process environment.

    This deliberately avoids an extra dotenv dependency. Callers must never log
    values read from the local, Git-ignored `.env` file.
    """
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name:
            values[name] = value.strip().strip('"').strip("'")
    return values
