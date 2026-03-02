from dataclasses import dataclass, field
from typing import List

@dataclass(slots=True)
class ChapterRef:
    index: int
    title: str
    url: str

@dataclass(slots=True)
class Volume:
    index: int
    title: str
    chapters: List[ChapterRef] = field(default_factory=list)
