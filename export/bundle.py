from dataclasses import dataclass
from typing import List
from models.metadata import SeriesMetadata
from models.volume import Volume
from models.chapter import Chapter

@dataclass(slots=True)
class VolumeExportBundle:
    metadata: SeriesMetadata
    volume: Volume
    chapters: List[Chapter]
