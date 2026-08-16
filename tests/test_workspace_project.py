import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from workspaces.epub_project import EpubWorkspaceProject
from gui.controllers.workspace_controller import WorkspaceController
from workspaces.manager import WorkspaceManager


class WorkspaceProjectTests(unittest.TestCase):
    def test_workspace_refresh_merges_existing_tree_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws_root = Path(tmp) / "workspaces"
            series_url = "https://example.test/series/demo"
            controller = WorkspaceController(WorkspaceManager(workspace_root=ws_root))

            original_payload = {
                "series_url": series_url,
                "series_title": "Demo Series",
                "volumes": [
                    {"title": "Volume 1", "chapters": [{"title": "Chapter 1", "url": "https://example.test/ch1"}]},
                    {"title": "Volume 2", "chapters": [{"title": "Chapter 2", "url": "https://example.test/ch2"}]},
                ],
            }
            refreshed_payload = {
                "series_url": series_url,
                "series_title": "Demo Series",
                "volumes": [
                    {"title": "Volume 1", "chapters": [{"title": "Chapter 1 Updated", "url": "https://example.test/ch1"}]},
                ],
            }

            controller.create_or_merge_from_payload(original_payload)
            merged, _workspace_dir, _message = controller.create_or_merge_from_payload(refreshed_payload)

            self.assertEqual(len(merged["volumes"]), 2)
            self.assertEqual(merged["volumes"][0]["chapters"][0]["title"], "Chapter 1 Updated")
            self.assertEqual(merged["volumes"][1]["title"], "Volume 2")
            self.assertEqual(merged["volumes"][1]["chapters"][0]["url"], "https://example.test/ch2")

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

    def test_latest_merge_updates_only_the_newest_frontier(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = WorkspaceManager(workspace_root=Path(tmp) / "workspaces")
            original = {
                "series_url": "https://example.test/series/demo",
                "series_title": "Demo Series",
                "volumes": [
                    {"title": "Volume 2", "chapters": [{"title": "Chapter 2", "url": "https://example.test/ch2"}]},
                    {"title": "Volume 1", "chapters": [{"title": "Chapter 1", "url": "https://example.test/ch1"}]},
                ],
            }
            latest = {
                "series_url": original["series_url"],
                "series_title": original["series_title"],
                "volumes": [
                    {
                        "title": "Volume 2",
                        "chapters": [
                            {"title": "Chapter 3", "url": "https://example.test/ch3"},
                            {"title": "Chapter 2", "url": "https://example.test/ch2"},
                        ],
                    }
                ],
            }

            merged, added = mgr.merge_latest_payload(original, latest)

            self.assertEqual(added, 1)
            self.assertEqual([c["url"] for c in merged["volumes"][0]["chapters"]], ["https://example.test/ch3", "https://example.test/ch2"])
            self.assertEqual(merged["volumes"][1]["title"], "Volume 1")

    def test_latest_merge_uses_chapter_urls_when_volume_title_changes(self):
        mgr = WorkspaceManager(workspace_root=Path(tempfile.mkdtemp()) / "workspaces")
        old = {
            "series_url": "https://example.test/series/demo",
            "volumes": [
                {"title": "Old Display Title", "chapters": [{"title": "Chapter 1", "url": "https://example.test/ch1"}]},
            ],
        }
        latest = {
            "series_url": old["series_url"],
            "volumes": [
                {
                    "title": "New Display Title",
                    "chapters": [
                        {"title": "Chapter 1", "url": "https://example.test/ch1"},
                        {"title": "Chapter 2", "url": "https://example.test/ch2"},
                    ],
                }
            ],
        }
        merged, added = mgr.merge_latest_payload(old, latest)

        self.assertEqual(added, 1)
        self.assertEqual(len(merged["volumes"]), 1)
        self.assertEqual(merged["volumes"][0]["title"], "Old Display Title")
        self.assertEqual([chapter["url"] for chapter in merged["volumes"][0]["chapters"]], ["https://example.test/ch1", "https://example.test/ch2"])

    def test_latest_merge_prefers_url_overlap_over_a_reused_volume_title(self):
        mgr = WorkspaceManager(workspace_root=Path(tempfile.mkdtemp()) / "workspaces")
        old = {
            "series_url": "https://example.test/series/demo",
            "volumes": [
                {"title": "Volume 13", "chapters": [{"url": "https://example.test/ch1"}]},
                {"title": "For Champions", "chapters": [{"url": "https://example.test/ch2"}]},
            ],
        }
        latest = {
            "series_url": old["series_url"],
            "volumes": [{"title": "Volume 13", "chapters": [{"url": "https://example.test/ch2"}, {"url": "https://example.test/ch3"}]}],
        }
        merged, added = mgr.merge_latest_payload(old, latest)

        self.assertEqual(added, 1)
        champion_volume = next(volume for volume in merged["volumes"] if volume["title"] == "For Champions")
        self.assertEqual([chapter["url"] for chapter in champion_volume["chapters"]], ["https://example.test/ch2", "https://example.test/ch3"])

    def test_repair_comment_metadata_removes_trailing_paragraph_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = WorkspaceManager(workspace_root=Path(tmp) / "workspaces")
            url = "https://example.test/series/demo"
            paths = mgr.ensure(url, "Demo Series")
            project = EpubWorkspaceProject(paths.root)
            project.write_chapter(
                series_title="Demo Series", language="en", volume_index=1, volume_title="Volume 1",
                volume_chapter_index=1, global_index=1, chapter_title_raw="Chapter 1", url="https://example.test/ch1",
                text="First paragraph.0\nSecond paragraph. 12",
            )

            report = project.repair_comment_metadata()
            repaired = project.load_cached_chapter(
                series_title="Demo Series", volume_index=1, volume_title="Volume 1", chapter_index=1,
                chapter_title="Chapter 1", url="https://example.test/ch1", min_chars=1,
            )

            self.assertEqual(report["sampled"], 1)
            self.assertEqual(report["scanned"], 1)
            self.assertEqual((report["chapters"], report["paragraphs"]), (1, 2))
            self.assertEqual(repaired.text, "First paragraph.\nSecond paragraph.")
