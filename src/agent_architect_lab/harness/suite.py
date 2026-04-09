from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from agent_architect_lab.models import Task


@dataclass(slots=True)
class ExperimentSuite:
    name: str
    tasks: list[Task]

    @classmethod
    def from_jsonl(cls, name: str, path: Path) -> "ExperimentSuite":
        tasks = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            payload = json.loads(stripped)
            tasks.append(Task(**payload))
        return cls(name=name, tasks=tasks)
