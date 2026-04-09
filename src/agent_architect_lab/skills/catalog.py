from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Skill:
    id: str
    name: str
    description: str
    triggers: list[str]
    tools: list[str]
    operating_notes: list[str]


def load_skills(catalog_dir: Path) -> list[Skill]:
    skills = []
    for path in sorted(catalog_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        skills.append(Skill(**payload))
    return skills


def select_skills(goal: str, skills: list[Skill]) -> list[Skill]:
    lowered = goal.lower()
    matched = []
    for skill in skills:
        if any(trigger.lower() in lowered for trigger in skill.triggers):
            matched.append(skill)
    return matched

