from dataclasses import dataclass

@dataclass(slots=True)
class Chapter:
    novel_title: str
    volume_index: int
    volume_title: str
    chapter_index: int
    chapter_title: str
    chapter_url: str
    text: str

    @property
    def volume_dir(self) -> str:
        return f"Volume {self.volume_index:02d} - {self.volume_title}"

    @property
    def chapter_dir(self) -> str:
        return f"Chapter {self.chapter_index:04d} - {self.chapter_title}"
