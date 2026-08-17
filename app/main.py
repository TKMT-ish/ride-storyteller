"""Run the Day 1 synthetic demonstration without credentials or network access."""

from __future__ import annotations

import json

from app.demo import build_demo_event, run_demo  # noqa: F401


def main() -> None:
    result = run_demo()
    print(json.dumps(result.decision.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
