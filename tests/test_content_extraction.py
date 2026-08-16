import unittest
import sys
from pathlib import Path

from lxml import html

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extract.content import extract_text


class ContentExtractionTests(unittest.TestCase):
    def test_extract_text_removes_wuxiaworld_badge_button(self):
        root = html.fromstring(
            """
            <div class="chapter-content">
              <p>First paragraph.</p>
              <button class="MuiButtonBase-root MuiTypography-root MuiTypography-inherit MuiLink-root MuiLink-underlineAlways ww-1k90dtk" tabindex="0" type="button">
                <span class="MuiBadge-root ww-1rzb3uu">
                  <span class="MuiBadge-badge h-16 text-[0.6rem] text-gray-100 MuiBadge-standard MuiBadge-anchorOriginTopRight MuiBadge-anchorOriginTopRightRectangular MuiBadge-overlapRectangular MuiBadge-colorSecondary bg-gray-400 dark:bg-gray-800 hover:bg-blue-300 ww-tzai6c">0</span>
                </span>
              </button>
              <p>Second paragraph.</p>
            </div>
            """
        )

        text = extract_text(root)

        self.assertEqual(text, "First paragraph.\nSecond paragraph.")


if __name__ == "__main__":
    unittest.main()
