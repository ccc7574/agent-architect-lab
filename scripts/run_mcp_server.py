from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_architect_lab.config import load_settings
from agent_architect_lab.mcp.server import serve


def main() -> int:
    settings = load_settings()
    serve(settings.notes_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
