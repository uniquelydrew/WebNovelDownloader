from parsing.html_doc import HtmlDoc
from parsing.wuxiaworld_file_parser import WuxiaworldFileParser
from services.playwright_discovery import PlaywrightDiscoveryService


class DiscoveryService:

    def __init__(self):
        self.parser = WuxiaworldFileParser()
        self.browser = PlaywrightDiscoveryService()

    def load_series_from_url(self, url: str):
        html = self.browser.load(url)
        doc = HtmlDoc.from_html(html, url=url)
        return self.parser.parse(doc)
