import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from workspaces.epub_project import EpubWorkspaceProject
from workspaces.manager import WorkspaceManager


class WorkspaceProjectTests(unittest.TestCase):
    def test_workspace_round_trip_and_finalize(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws_root = Path(tmp) / "workspaces"
            series_url = "https://example.test/series/demo"
            mgr = WorkspaceManager(workspace_root=ws_root)
            paths = mgr.ensure(series_url, "Demo Series")
            mgr.create_or_update_from_payload(
                {
                    "series_url": series_url,
                    "series_title": "Demo Series",
                    "volumes": [
                        {
                            "title": "Volume Alpha",
                            "chapters": [
                                {"title": "Chapter 2 - Later", "url": "https://example.test/ch2"},
                                {"title": "Chapter 1 - Earlier", "url": "https://example.test/ch1"},
                            ],
                        }
                    ],
                }
            )

            project = EpubWorkspaceProject(paths.root)
            project.write_chapter(
                series_title="Demo Series",
                language="en",
                volume_index=1,
                volume_title="Volume Alpha",
                volume_chapter_index=2,
                global_index=2,
                chapter_title_raw="Chapter 2 - Later",
                url="https://example.test/ch2",
                text="Later text",
            )
            project.write_chapter(
                series_title="Demo Series",
                language="en",
                volume_index=1,
                volume_title="Volume Alpha",
                volume_chapter_index=1,
                global_index=1,
                chapter_title_raw="Chapter 1 - Earlier",
                url="https://example.test/ch1",
                text="Earlier text",
            )
            project.finalize_and_repair(language="en", series_title="Demo Series")

            ws, tree = mgr.load(series_url)
            self.assertEqual(tree["series_title"], "Demo Series")
            self.assertEqual(len(ws["chapters"]), 2)
            self.assertTrue((paths.root / "epub" / "OEBPS" / "nav.xhtml").exists())
            self.assertTrue((paths.root / "epub" / "OEBPS" / "content.opf").exists())
            self.assertEqual(ws["chapters"][0]["chapter_title"], "Chapter 1 — Earlier")
            self.assertEqual(ws["chapters"][1]["chapter_title"], "Chapter 2 — Later")
            self.assertEqual(ws["chapters_by_global"]["1"], 0)
            self.assertEqual(ws["chapters_by_global"]["2"], 1)
