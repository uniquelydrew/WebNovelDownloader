from __future__ import annotations
from pathlib import Path
import json
from models.chapter import Chapter

def _sanitize(name: str, max_len: int = 140) -> str:
    # Windows-safe basic sanitize
    bad = '<>:"/\\|?*'
    out = "".join("_" if c in bad or ord(c) < 32 else c for c in name).strip()
    out = " ".join(out.split())
    out = out.strip(" .")
    if len(out) > max_len:
        out = out[:max_len].rstrip()
    return out or "Unnamed"

class FilesystemPipeline:
    def open_spider(self, spider):
        self.root = Path(getattr(spider, "out_dir", "out")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def process_item(self, item, spider):
        # item is Chapter dataclass
        assert isinstance(item, Chapter)

        novel_dir = self.root / _sanitize(item.novel_title)
        volume_dir = novel_dir / _sanitize(item.volume_dir)
        chapter_dir = volume_dir / _sanitize(item.chapter_dir)
        chapter_dir.mkdir(parents=True, exist_ok=True)

        (chapter_dir / "chapter.txt").write_text(item.text, encoding="utf-8", newline="\n")

        meta = {
            "novel_title": item.novel_title,
            "volume_index": item.volume_index,
            "volume_title": item.volume_title,
            "chapter_index": item.chapter_index,
            "chapter_title": item.chapter_title,
            "chapter_url": item.chapter_url,
        }
        (chapter_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        return item
