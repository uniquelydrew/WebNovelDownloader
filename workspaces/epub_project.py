from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from workspaces.manager import _atomic_write_json, _read_json, _utc_iso


def _xml_escape(s: str) -> str:
    import html
    return html.escape(s or "", quote=True)


def _sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


_CHAPTER_TITLE_RE = re.compile(r"chapter\s*(\d+)\s*[:\-\u2013\u2014]?\s*(.*)", re.IGNORECASE)


def normalize_chapter_title(raw_title: str, volume_chapter_index: int) -> tuple[str, dict[str, Any]]:
    """Return (normalized_title, info).

    Normal form: "Chapter N — Subtitle" (subtitle optional).
    """
    raw = (raw_title or "").strip()
    m = _CHAPTER_TITLE_RE.search(raw)
    info: dict[str, Any] = {"raw": raw, "parsed": False, "parsed_number": None, "parsed_subtitle": None}
    if m:
        info["parsed"] = True
        try:
            num = int(m.group(1))
        except Exception:
            num = volume_chapter_index
        subtitle = (m.group(2) or "").strip()
        info["parsed_number"] = num
        info["parsed_subtitle"] = subtitle
        n = num
    else:
        n = volume_chapter_index
        subtitle = raw

    if subtitle:
        return f"Chapter {n} — {subtitle}", info
    return f"Chapter {n}", info


def _ensure_epub_skeleton(epub_root: Path) -> None:
    """Create minimal unpacked EPUB skeleton if missing."""
    (epub_root / "META-INF").mkdir(parents=True, exist_ok=True)
    (epub_root / "OEBPS" / "chapters").mkdir(parents=True, exist_ok=True)
    (epub_root / "OEBPS" / "styles").mkdir(parents=True, exist_ok=True)

    mimetype = epub_root / "mimetype"
    if not mimetype.exists():
        mimetype.write_text("application/epub+zip", encoding="utf-8", newline="\n")

    container_xml = epub_root / "META-INF" / "container.xml"
    if not container_xml.exists():
        container_xml.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
            encoding="utf-8",
            newline="\n",
        )

    css_path = epub_root / "OEBPS" / "styles" / "style.css"
    if not css_path.exists():
        css_path.write_text(
            "body{font-family:serif;}\n"
            ".volume-title{margin-top:0.5em;}\n"
            ".chapter-title{margin-top:0.5em;}\n",
            encoding="utf-8",
            newline="\n",
        )


def _chapter_filename(volume_index: int, volume_chapter_index: int) -> str:
    return f"v{volume_index:02d}c{volume_chapter_index:03d}.xhtml"


def _render_chapter_xhtml(lang: str, volume_title: str, chapter_title: str, text: str, meta: dict[str, Any]) -> str:
    paras = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        paras.append(f"<p>{_xml_escape(line)}</p>")
    paras_html = "\n  ".join(paras)

    meta_tags = []
    for k, v in (meta or {}).items():
        if v is None:
            continue
        meta_tags.append(f'  <meta name="{_xml_escape(str(k))}" content="{_xml_escape(str(v))}"/>')
    meta_html = "\n".join(meta_tags)

    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{_xml_escape(lang)}" lang="{_xml_escape(lang)}">\n'
        "<head>\n"
        f"  <title>{_xml_escape(chapter_title)}</title>\n"
        '  <meta charset="utf-8" />\n'
        f"{meta_html}\n"
        '  <link rel="stylesheet" type="text/css" href="../styles/style.css" />\n'
        "</head>\n"
        "<body>\n"
        f'  <h1 class="volume-title">{_xml_escape(volume_title)}</h1>\n'
        f'  <h2 class="chapter-title">{_xml_escape(chapter_title)}</h2>\n'
        f"  {paras_html}\n"
        "</body>\n"
        "</html>\n"
    )


@dataclass(slots=True)
class ChapterRecord:
    volume_index: int
    volume_title: str
    volume_chapter_index: int
    global_index: Optional[int]
    chapter_title_raw: str
    chapter_title: str
    url: str
    file: str
    sha256: str
    downloaded: bool
    duplicate_of_global: Optional[int] = None
    issues: Optional[list[str]] = None


class EpubWorkspaceProject:
    """Unpacked EPUB workspace with a workspace.json chapter index."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self.workspace_json = self.workspace_root / "workspace.json"
        self.tree_json = self.workspace_root / "tree.json"
        self.epub_root = self.workspace_root / "epub"
        self.oebps = self.epub_root / "OEBPS"
        self.chapters_dir = self.oebps / "chapters"

        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.epub_root.mkdir(parents=True, exist_ok=True)
        _ensure_epub_skeleton(self.epub_root)

    def _load_ws(self) -> dict:
        return _read_json(
            self.workspace_json,
            default={"schema": 2, "chapters": [], "chapters_by_url": {}, "chapters_by_global": {}, "issues": []},
        )

    def _save_ws(self, ws: dict) -> None:
        ws["last_updated"] = _utc_iso()
        _atomic_write_json(self.workspace_json, ws)

    def write_chapter(
        self,
        *,
        series_title: str,
        language: str,
        volume_index: int,
        volume_title: str,
        volume_chapter_index: int,
        global_index: Optional[int],
        chapter_title_raw: str,
        url: str,
        text: str,
    ) -> ChapterRecord:
        ws = self._load_ws()

        normalized_title, parse_info = normalize_chapter_title(chapter_title_raw, volume_chapter_index)
        sha = _sha256_text(text)

        # Duplicate detection by content hash across existing downloaded chapters.
        existing = ws.get("chapters") or []
        duplicate_of_global = None
        for rec in existing:
            if rec.get("sha256") == sha and rec.get("downloaded"):
                duplicate_of_global = rec.get("global_index")
                break

        fname = _chapter_filename(volume_index, volume_chapter_index)
        rel_file = f"OEBPS/chapters/{fname}"
        abs_file = self.chapters_dir / fname

        meta = {
            "series_title": series_title,
            "global_index": global_index,
            "volume": volume_index,
            "volume_chapter": volume_chapter_index,
            "source_url": url,
        }
        xhtml = _render_chapter_xhtml(language, volume_title, normalized_title, text, meta=meta)
        abs_file.write_text(xhtml, encoding="utf-8", newline="\n")

        rec: dict[str, Any] = {
            "volume_index": volume_index,
            "volume_title": volume_title,
            "volume_chapter_index": volume_chapter_index,
            "global_index": global_index,
            "chapter_title_raw": chapter_title_raw,
            "chapter_title": normalized_title,
            "url": url,
            "file": rel_file,
            "sha256": sha,
            "downloaded": True,
            "duplicate_of_global": duplicate_of_global,
            "title_parse": parse_info,
        }

        # upsert by url
        by_url: dict = ws.get("chapters_by_url") or {}
        prior_idx = by_url.get(url)
        if prior_idx is None:
            ws["chapters"] = list(existing) + [rec]
            by_url[url] = len(ws["chapters"]) - 1
        else:
            ws["chapters"][int(prior_idx)] = rec

        ws["chapters_by_url"] = by_url

        if global_index is not None:
            by_global = ws.get("chapters_by_global") or {}
            by_global[str(int(global_index))] = by_url[url]
            ws["chapters_by_global"] = by_global

        self._save_ws(ws)

        return ChapterRecord(
            volume_index=volume_index,
            volume_title=volume_title,
            volume_chapter_index=volume_chapter_index,
            global_index=global_index,
            chapter_title_raw=chapter_title_raw,
            chapter_title=normalized_title,
            url=url,
            file=rel_file,
            sha256=sha,
            downloaded=True,
            duplicate_of_global=duplicate_of_global,
            issues=[],
        )

    def finalize_and_repair(
        self,
        *,
        language: str,
        series_title: str,
        author: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        """High-value enhancements pass + rebuild OPF/NCX/NAV."""
        ws = self._load_ws()
        chapters = list(ws.get("chapters") or [])

        # Group by volume
        vols: dict[int, list[dict[str, Any]]] = {}
        for rec in chapters:
            vi = int(rec.get("volume_index") or 0)
            vols.setdefault(vi, []).append(rec)

        # Auto-renumber per volume (based on global_index ordering if present).
        renames: list[tuple[Path, Path]] = []
        for vi, recs in sorted(vols.items(), key=lambda x: x[0]):
            def _key(r: dict) -> tuple:
                gi = r.get("global_index")
                if gi is None:
                    return (1, int(r.get("volume_chapter_index") or 0), r.get("url") or "")
                return (0, int(gi), r.get("url") or "")

            recs_sorted = sorted(recs, key=_key)

            for new_idx, rec in enumerate(recs_sorted, start=1):
                old_idx = int(rec.get("volume_chapter_index") or 0)
                if old_idx != new_idx:
                    old_fname = _chapter_filename(vi, old_idx)
                    new_fname = _chapter_filename(vi, new_idx)
                    old_path = self.chapters_dir / old_fname
                    new_path = self.chapters_dir / new_fname

                    if old_path.exists() and not new_path.exists():
                        renames.append((old_path, new_path))
                    elif old_path.exists() and new_path.exists():
                        ws.setdefault("issues", []).append(
                            {
                                "type": "rename_collision",
                                "volume_index": vi,
                                "from": str(old_path),
                                "to": str(new_path),
                                "url": rec.get("url"),
                            }
                        )

                    rec["volume_chapter_index"] = new_idx
                    rec["file"] = f"OEBPS/chapters/{new_fname}"
                    fixed_title, _ = normalize_chapter_title(rec.get("chapter_title_raw") or rec.get("chapter_title") or "", new_idx)
                    rec["chapter_title"] = fixed_title

        for src, dst in renames:
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                src.replace(dst)
            except Exception:
                shutil.copyfile(src, dst)
                try:
                    src.unlink()
                except Exception:
                    pass

        # Rebuild lookup indices
        by_url: dict[str, int] = {}
        by_global: dict[str, int] = {}
        for i, rec in enumerate(chapters):
            url = (rec.get("url") or "").strip()
            if url:
                by_url[url] = i
            gi = rec.get("global_index")
            if gi is not None:
                by_global[str(int(gi))] = i

        ws["chapters"] = chapters
        ws["chapters_by_url"] = by_url
        ws["chapters_by_global"] = by_global

        # Missing detection using tree.json if present (expected URL list)
        try:
            tree = _read_json(self.tree_json, default=None)
        except Exception:
            tree = None
        if isinstance(tree, dict) and tree.get("volumes"):
            expected_urls = []
            for vol in tree.get("volumes") or []:
                for ch in vol.get("chapters") or []:
                    u = (ch.get("url") or "").strip()
                    if u:
                        expected_urls.append(u)
            missing_urls = [u for u in expected_urls if u not in by_url]
            if missing_urls:
                ws.setdefault("issues", []).append(
                    {"type": "missing_urls", "count": len(missing_urls), "sample": missing_urls[:20]}
                )

        # Duplicate detection summary (by sha256)
        sha_map: dict[str, list[dict[str, Any]]] = {}
        for rec in chapters:
            sha = rec.get("sha256") or ""
            if not sha:
                continue
            sha_map.setdefault(sha, []).append(rec)
        dup_groups = {sha: recs for sha, recs in sha_map.items() if len(recs) > 1}
        if dup_groups:
            ws.setdefault("issues", []).append(
                {"type": "duplicate_content", "groups": len(dup_groups), "count": sum(len(v) for v in dup_groups.values())}
            )
