from __future__ import annotations

from pathlib import Path

from agent_architect_lab.skills.catalog import Skill, load_skills, select_skills


class SkillRouter:
    def __init__(self, catalog_dir: Path) -> None:
        self.catalog_dir = catalog_dir

    def load(self) -> list[Skill]:
        return load_skills(self.catalog_dir)

    def select(self, goal: str) -> list[str]:
        if not goal.strip():
            return []
        matched = select_skills(goal, self.load())
        return [skill.id for skill in matched]
