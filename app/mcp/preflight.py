"""Print a redacted readiness report; it never contacts Box."""

from __future__ import annotations

import json

from .box_config import BoxMcpSettings, preflight_box_mcp


def main() -> None:
    result = preflight_box_mcp(BoxMcpSettings.from_environment())
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
