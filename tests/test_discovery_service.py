import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.discovery_service import DiscoveryService


class DiscoveryServiceTests(unittest.TestCase):
    def test_normalize_payload_enforces_contract(self):
        payload = DiscoveryService.normalize_payload(
            {
                "series_title": "  Example Series  ",
                "volumes": [
                    {
                        "title": " ",
                        "chapters": [
                            {"title": "  ", "url": " https://example.test/ch-1 "},
                            {"url": ""},
                            "ignore-me",
                        ],
                    },
                    "ignore-me-too",
                ],
            },
            fallback_url="https://example.test/series",
        )

        self.assertEqual(payload["series_title"], "Example Series")
        self.assertEqual(payload["series_url"], "https://example.test/series")
        self.assertEqual(len(payload["volumes"]), 1)
        self.assertEqual(payload["volumes"][0]["title"], "Volume 1")
        self.assertEqual(payload["volumes"][0]["chapters"][0]["title"], "Chapter 1")
        self.assertEqual(payload["volumes"][0]["chapters"][0]["url"], "https://example.test/ch-1")
        self.assertEqual(payload["volumes"][0]["chapters"][1]["title"], "Chapter 2")

    def test_normalize_payload_rejects_non_dict(self):
        with self.assertRaises(TypeError):
            DiscoveryService.normalize_payload(["bad"])  # type: ignore[arg-type]
