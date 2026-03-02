from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urljoin as _urljoin
from lxml import html

@dataclass(slots=True)
class HtmlDoc:
    url: str
    root: html.HtmlElement

    @classmethod
    def from_html(cls, html_bytes_or_str: bytes | str, url: str) -> "HtmlDoc":
        if isinstance(html_bytes_or_str, bytes):
            txt = html_bytes_or_str.decode("utf-8", errors="ignore")
        else:
            txt = html_bytes_or_str
        root = html.fromstring(txt)
        return cls(url=url, root=root)

    def xpath(self, query: str):
        return self.root.xpath(query)

    def urljoin(self, href: str) -> str:
        return _urljoin(self.url, href)
