from dataclasses import dataclass, field
from typing import Set, Iterator, Tuple
from models.series import Series
from models.volume import Volume, ChapterRef

@dataclass(slots=True)
class SelectionState:
    selected_volume_indices: Set[int] = field(default_factory=set)
    selected_chapter_urls: Set[str] = field(default_factory=set)

    def to_json(self) -> dict:
        return {
            "selected_volume_indices": sorted(self.selected_volume_indices),
            "selected_chapter_urls": sorted(self.selected_chapter_urls),
        }

    @classmethod
    def from_json(cls, obj: dict) -> "SelectionState":
        return cls(
            selected_volume_indices=set(obj.get("selected_volume_indices", [])),
            selected_chapter_urls=set(obj.get("selected_chapter_urls", [])),
        )

class Selection:
    def __init__(self, series: Series, state: SelectionState | None = None):
        self.series = series
        self.state = state or SelectionState()

    def select_all_volumes(self) -> None:
        for v in self.series.volumes:
            self.state.selected_volume_indices.add(v.index)

    def select_volume(self, volume_index: int) -> None:
        self.state.selected_volume_indices.add(volume_index)

    def select_chapter(self, chapter_url: str) -> None:
        self.state.selected_chapter_urls.add(chapter_url)

    def iter_selected(self) -> Iterator[Tuple[Volume, ChapterRef]]:
        for volume in self.series.volumes:
            if volume.index in self.state.selected_volume_indices:
                for chapter in volume.chapters:
                    yield volume, chapter
            else:
                for chapter in volume.chapters:
                    if chapter.url in self.state.selected_chapter_urls:
                        yield volume, chapter
