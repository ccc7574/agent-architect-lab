from __future__ import annotations

import json
from pathlib import Path

from agent_architect_lab.models import RunTrace


class CheckpointStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, trace: RunTrace) -> Path:
        path = self.root / f"{trace.run_id}.checkpoint.json"
        path.write_text(json.dumps(trace.to_dict(), indent=2), encoding="utf-8")
        return path

