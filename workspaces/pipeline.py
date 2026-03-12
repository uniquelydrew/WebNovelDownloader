from __future__ import annotations

from pathlib import Path

from models.chapter import Chapter
from workspaces.epub_project import EpubWorkspaceProject


class EpubWorkspacePipeline:
    """Persist chapters into the workspace's unpacked EPUB project immediately."""

    def open_spider(self, spider):
        workspace_dir = getattr(spider, "workspace_dir", None)
        if not workspace_dir:
            raise RuntimeError("EpubWorkspacePipeline requires spider.workspace_dir")
        self.workspace_root = Path(workspace_dir).resolve()
        self.project = EpubWorkspaceProject(self.workspace_root)
        self.series_title = str(getattr(spider, "series_title", "") or "Unknown Series")
        self.language = str(getattr(spider, "language", "") or "en")

    def process_item(self, item, spider):
        assert isinstance(item, Chapter)
        self.project.write_chapter(
            series_title=item.novel_title or self.series_title,
            language=getattr(item, "language", None) or self.language,
            volume_index=item.volume_index,
            volume_title=item.volume_title,
            volume_chapter_index=item.chapter_index,
            global_index=getattr(item, "global_index", None),
            chapter_title_raw=item.chapter_title,
            url=item.chapter_url,
            text=item.text,
        )
        return item
