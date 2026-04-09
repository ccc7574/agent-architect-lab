from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp


@dataclass(slots=True)
class WorkspaceSandbox:
    source_root: Path
    sandbox_root: Path

    @classmethod
    def create(cls, source_root: Path, base_dir: Path | None = None) -> "WorkspaceSandbox":
        sandbox_root = Path(mkdtemp(prefix="agent-lab-", dir=str(base_dir) if base_dir else None))
        copy_root = sandbox_root / "workspace"
        shutil.copytree(source_root, copy_root, dirs_exist_ok=True)
        return cls(source_root=source_root, sandbox_root=copy_root)

    def cleanup(self) -> None:
        shutil.rmtree(self.sandbox_root.parent, ignore_errors=True)

