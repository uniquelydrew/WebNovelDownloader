from __future__ import annotations

import html
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from export.base import BaseExporter
from export.bundle import VolumeExportBundle


def _xml_escape(s: str) -> str:
    return html.escape(s, quote=True)


def _read_style_bytes() -> bytes:
    css_path = Path(__file__).with_name("epub_style.css")
    return css_path.read_bytes()


def _chapter_subtitle(raw_title: str) -> str:
    title = (raw_title or "").strip()
    lower = title.lower()
    if not lower.startswith("chapter"):
        return title

    for sep in (" - ", ": "):
        idx = title.find(sep)
        if idx != -1:
            return title[idx + len(sep):].strip()

    parts = title.split(maxsplit=2)
    if len(parts) >= 3 and parts[1].isdigit():
        return parts[2].strip()
    return ""


def _display_chapter_title(raw_title: str, volume_chapter_index: int) -> str:
    subtitle = _chapter_subtitle(raw_title)
    return f"Chapter {volume_chapter_index} - {subtitle}" if subtitle else f"Chapter {volume_chapter_index}"


class EPUBExporter(BaseExporter):
    """
    Minimal EPUB writer implemented with zipfile to avoid external deps.
    Produces a reader-compatible EPUB with:
      - one XHTML per chapter
      - nav.xhtml + toc.ncx
      - content.opf
      - embedded CSS
    """

    def export(self, bundle: VolumeExportBundle, output_path: str) -> None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        meta = bundle.metadata
        book_id = str(uuid.uuid4())
        volume_title = bundle.volume.title
        title = f"{meta.title} - {volume_title}"
        modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        display_chapters: list[dict[str, str]] = []
        chapter_files: list[tuple[str, str]] = []
        for volume_chapter_index, ch in enumerate(bundle.chapters, start=1):
            href = f"chap_{volume_chapter_index:04d}.xhtml"
            display_title = _display_chapter_title(ch.chapter_title, volume_chapter_index)
            display_chapters.append({"href": href, "title": display_title})
            chapter_files.append((f"OEBPS/{href}", self._chapter_xhtml(meta.language, display_title, ch.text)))

        style_bytes = _read_style_bytes()
        nav_xhtml = self._nav_xhtml(meta.language, title, display_chapters)
        ncx = self._toc_ncx(book_id, title, display_chapters)
        opf = self._content_opf(book_id, title, meta, modified, display_chapters)

        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            z.writestr("META-INF/container.xml", self._container_xml())
            z.writestr("OEBPS/styles/style.css", style_bytes)
            z.writestr("OEBPS/nav.xhtml", nav_xhtml)
            z.writestr("OEBPS/toc.ncx", ncx)
            z.writestr("OEBPS/content.opf", opf)
            for fname, content in chapter_files:
                z.writestr(fname, content)

    def _container_xml(self) -> str:
        return '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
'''

    def _chapter_xhtml(self, lang: str, chapter: str, text: str) -> str:
        paras = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            paras.append(f"<p>{_xml_escape(line)}</p>")
        paras_html = "\n".join(paras)

        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{_xml_escape(lang)}" lang="{_xml_escape(lang)}">\n'
            '<head>\n'
            f'  <title>{_xml_escape(chapter)}</title>\n'
            '  <meta charset="utf-8" />\n'
            '  <link rel="stylesheet" type="text/css" href="styles/style.css" />\n'
            '</head>\n'
            '<body>\n'
            f'  <h1 class="chapter-title">{_xml_escape(chapter)}</h1>\n'
            f'  {paras_html}\n'
            '</body>\n'
            '</html>\n'
        )

    def _nav_xhtml(self, lang: str, title: str, chapters: list[dict[str, str]]) -> str:
        lis = []
        for ch in chapters:
            lis.append(f'<li><a href="{ch["href"]}">{_xml_escape(ch["title"])}</a></li>')
        lis_html = "\n      ".join(lis)
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{_xml_escape(lang)}" lang="{_xml_escape(lang)}">\n'
            '<head>\n'
            f'  <title>{_xml_escape(title)}</title>\n'
            '  <meta charset="utf-8" />\n'
            '  <link rel="stylesheet" type="text/css" href="styles/style.css" />\n'
            '</head>\n'
            '<body>\n'
            '  <nav epub:type="toc" id="toc">\n'
            f'    <h1>{_xml_escape(title)}</h1>\n'
            '    <ol>\n'
            f'      {lis_html}\n'
            '    </ol>\n'
            '  </nav>\n'
            '</body>\n'
            '</html>\n'
        )

    def _toc_ncx(self, book_id: str, title: str, chapters: list[dict[str, str]]) -> str:
        navpoints = []
        for play, ch in enumerate(chapters, start=1):
            navpoints.append(
                "    <navPoint id=\"navPoint-{play}\" playOrder=\"{play}\">\n"
                "      <navLabel><text>{label}</text></navLabel>\n"
                "      <content src=\"{src}\"/>\n"
                "    </navPoint>".format(
                    play=play,
                    label=_xml_escape(ch["title"]),
                    src=ch["href"],
                )
            )

        navpoints_xml = "\n".join(navpoints)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
            '  <head>\n'
            f'    <meta name="dtb:uid" content="{_xml_escape(book_id)}"/>\n'
            '    <meta name="dtb:depth" content="1"/>\n'
            '    <meta name="dtb:totalPageCount" content="0"/>\n'
            '    <meta name="dtb:maxPageNumber" content="0"/>\n'
            '  </head>\n'
            f'  <docTitle><text>{_xml_escape(title)}</text></docTitle>\n'
            '  <navMap>\n'
            f'{navpoints_xml}\n'
            '  </navMap>\n'
            '</ncx>\n'
        )

    def _content_opf(self, book_id: str, title: str, meta, modified: str, chapters: list[dict[str, str]]) -> str:
        manifest_items = [
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
            '<item id="css" href="styles/style.css" media-type="text/css"/>',
        ]
        spine_items = ['<itemref idref="nav"/>']

        for idx, ch in enumerate(chapters, start=1):
            cid = f"chap{idx:04d}"
            manifest_items.append(f'<item id="{cid}" href="{ch["href"]}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'<itemref idref="{cid}"/>')

        author_meta = f"<dc:creator>{_xml_escape(meta.author)}</dc:creator>" if meta.author else ""
        desc_meta = f"<dc:description>{_xml_escape(meta.description)}</dc:description>" if meta.description else ""
        lang_meta = _xml_escape(getattr(meta, "language", None) or "en")
        manifest_block = "\n    ".join(manifest_items)
        spine_block = "\n    ".join(spine_items)

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">\n'
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            f'    <dc:identifier id="bookid">{_xml_escape(book_id)}</dc:identifier>\n'
            f'    <dc:title>{_xml_escape(title)}</dc:title>\n'
            f'    {author_meta}\n'
            f'    {desc_meta}\n'
            f'    <dc:language>{lang_meta}</dc:language>\n'
            f'    <meta property="dcterms:modified">{_xml_escape(modified)}</meta>\n'
            '  </metadata>\n'
            '  <manifest>\n'
            f'    {manifest_block}\n'
            '  </manifest>\n'
            '  <spine toc="ncx">\n'
            f'    {spine_block}\n'
            '  </spine>\n'
            '</package>\n'
        )