from __future__ import annotations

import json
from pathlib import Path

from agent_architect_lab.models import RunTrace


class TraceStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, trace: RunTrace) -> Path:
        path = self.root / f"{trace.run_id}.json"
        path.write_text(json.dumps(trace.to_dict(), indent=2), encoding="utf-8")
        return path

    def load(self, run_id: str) -> dict:
        path = self.root / f"{run_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

