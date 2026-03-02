from dataclasses import dataclass, field
from typing import List
from models.volume import Volume

@dataclass(slots=True)
class Series:
    title: str
    index_url: str
    volumes: List[Volume] = field(default_factory=list)
