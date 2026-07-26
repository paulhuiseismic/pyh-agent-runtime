"""长期记忆数据结构：MemoryEntry / ExtractionResult（见 specs/004 data-model.md）。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MemoryEntry:
    content: str
    category: str | None = None


@dataclass(frozen=True)
class ExtractionResult:
    entries: list[MemoryEntry] = field(default_factory=list)
