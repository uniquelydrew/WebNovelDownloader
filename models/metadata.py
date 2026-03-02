from dataclasses import dataclass
from typing import Optional

@dataclass(slots=True)
class SeriesMetadata:
    title: str
    author: Optional[str] = None
    description: Optional[str] = None
    language: str = "en"
    cover_image_url: Optional[str] = None
