from __future__ import annotations

from typing import List
from lxml import etree

from models.series import Series
from models.volume import Volume, ChapterRef


class WuxiaworldFileParser:
    """
    Strict parser for Wuxiaworld saved index HTML.
    Expects full DOM saved from browser.
    """

    def parse(self, doc) -> Series:
        # Series title
        title_nodes = doc.xpath("//title/text()")
        series_title = title_nodes[0].strip() if title_nodes else "Unknown Series"
        series = Series(title=series_title, index_url="file://local")

        # Each volume is inside MuiAccordion-root container
        accordions = doc.xpath("//*[contains(@class,'MuiAccordion-root')]")

        vol_index_counter = 1

        for acc in accordions:
            # Extract full visible header text (button inside accordion)
            header_text = "".join(acc.xpath(".//button//text()")).strip()
            if not header_text:
                continue

            volume = Volume(index=vol_index_counter, title=header_text)

            # Chapter anchors inside this accordion
            anchors = acc.xpath(".//a[@href]")
            chap_counter = 1

            for a in anchors:
                href = a.attrib.get("href")
                text = "".join(a.xpath(".//text()")).strip()
                if not href or not text:
                    continue

                # Filter chapter links only
                if "/novel/" not in href:
                    continue

                volume.chapters.append(
                    ChapterRef(
                        index=chap_counter,
                        title=text,
                        url="https://www.wuxiaworld.com" + href if href.startswith("/") else href,
                    )
                )
                chap_counter += 1

            if volume.chapters:
                series.volumes.append(volume)
                vol_index_counter += 1

        return series
