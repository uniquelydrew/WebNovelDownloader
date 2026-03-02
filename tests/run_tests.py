import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parsing.html_doc import HtmlDoc
from parsing.volume_parser import HeuristicVolumeParser
from extract.content import find_content_container, extract_text
from clean.cleaner import Cleaner, CleanerConfig
from export.bundle import VolumeExportBundle
from export.service import ExportService
from models.metadata import SeriesMetadata
from models.volume import Volume
from models.chapter import Chapter

INDEX_FILE = r"/mnt/data/index.htm"
CHAPTER_FILE = r"/mnt/data/chapter.htm"

def test_parse_index() -> None:
    html = Path(INDEX_FILE).read_bytes()
    resp = HtmlDoc.from_html(html, url="https://example.test/index")
    parser = HeuristicVolumeParser(chapter_href_contains="chapter")
    series = parser.parse(resp)
    assert series.title
    assert series.index_url
    assert len(series.volumes) >= 1
    print("Index parse OK:", series.title, "volumes:", len(series.volumes))

def test_extract_and_clean_chapter() -> Chapter:
    html = Path(CHAPTER_FILE).read_bytes()
    resp = HtmlDoc.from_html(html, url="https://example.test/chapter/1")
    container = find_content_container(resp)
    assert container is not None
    raw = extract_text(container)
    assert raw
    cleaner = Cleaner(CleanerConfig(aside_mode="balanced", remove_footnote_markers=True))
    cleaned = cleaner.clean(raw)
    assert cleaned
    print("Chapter extraction OK: raw chars:", len(raw), "clean chars:", len(cleaned))
    return Chapter(
        novel_title="Test Series",
        volume_index=1,
        volume_title="Volume 01",
        chapter_index=1,
        chapter_title="Chapter 1",
        chapter_url=resp.url,
        text=cleaned,
    )

def test_export(chapter: Chapter) -> None:
    out_dir = Path("/mnt/data/test_exports")
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in out_dir.glob("*"):
        p.unlink()

    meta = SeriesMetadata(title="Test Series", author="Unknown", description="Test export", language="en")
    vol = Volume(index=1, title="Volume 01", chapters=[])
    bundle = VolumeExportBundle(metadata=meta, volume=vol, chapters=[chapter])

    svc = ExportService()
    epub_path = svc.export_volume(bundle, str(out_dir), "epub")
    pdf_path = svc.export_volume(bundle, str(out_dir), "pdf")

    assert Path(epub_path).exists() and Path(epub_path).stat().st_size > 0
    assert Path(pdf_path).exists() and Path(pdf_path).stat().st_size > 0
    print("Export OK:", epub_path, pdf_path)

def main():
    test_parse_index()
    ch = test_extract_and_clean_chapter()
    test_export(ch)
    print("ALL TESTS PASSED")

if __name__ == "__main__":
    main()
