from __future__ import annotations
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from export.base import BaseExporter
from export.bundle import VolumeExportBundle

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, header_text: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self._header_text = header_text

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_header_footer()
            super().showPage()
        super().save()

    def _draw_header_footer(self):
        w, h = self._pagesize
        self.setFont("Helvetica", 9)
        if self._header_text:
            self.drawString(0.75 * inch, h - 0.5 * inch, self._header_text)
        self.drawCentredString(w / 2.0, 0.5 * inch, f"{self._pageNumber}")

class PDFExporter(BaseExporter):
    def export(self, bundle: VolumeExportBundle, output_path: str) -> None:
        title = f"{bundle.metadata.title} - {bundle.volume.title}"

        doc = SimpleDocTemplate(
            output_path,
            leftMargin=0.85 * inch,
            rightMargin=0.85 * inch,
            topMargin=0.9 * inch,
            bottomMargin=0.85 * inch,
        )
        story = []
        styles = getSampleStyleSheet()

        story.append(Paragraph(title, styles["Heading1"]))
        story.append(Spacer(1, 0.5 * inch))

        for chapter in bundle.chapters:
            story.append(Paragraph(chapter.chapter_title, styles["Heading2"]))
            story.append(Spacer(1, 0.2 * inch))

            for line in chapter.text.split("\n"):
                line = line.strip()
                if line:
                    story.append(Paragraph(line, styles["BodyText"]))
                    story.append(Spacer(1, 0.12 * inch))

            story.append(PageBreak())

        doc.build(story, canvasmaker=lambda *a, **k: NumberedCanvas(*a, header_text=title, **k))
