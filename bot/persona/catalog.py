"""Dynamic persona discovery inspired by Tulpa's Markdown persona catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    path: Path
    prompt: str


class PersonaCatalog:
    """Discover Markdown personas without importing the Tulpa runtime."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @staticmethod
    def _name(path: Path, prompt: str) -> str:
        for line in prompt.splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                return line[:80]
        return path.stem

    def list(self) -> list[Persona]:
        if not self.root.exists():
            return []
        result: list[Persona] = []
        for path in sorted(self.root.glob("*.md")):
            try:
                prompt = path.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                continue
            if not prompt:
                continue
            result.append(Persona(path.stem, self._name(path, prompt), path, prompt))
        return result

    def get(self, persona_id: str) -> Persona | None:
        wanted = str(persona_id or "").strip()
        return next((item for item in self.list() if item.id == wanted), None)

    def resolve(self, active: str, fallback: str | Path) -> tuple[Path, Persona | None]:
        chosen = self.get(active) if active else None
        if chosen is not None:
            return chosen.path, chosen
        return Path(fallback), None

