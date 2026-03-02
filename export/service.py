from __future__ import annotations
from pathlib import Path
from export.bundle import VolumeExportBundle
from export.epub_exporter import EPUBExporter
from export.pdf_exporter import PDFExporter

def _sanitize_filename(s: str) -> str:
    bad = '<>:"/\\|?*'
    out = "".join("_" if c in bad or ord(c) < 32 else c for c in s).strip()
    out = " ".join(out.split())
    out = out.strip(" .")
    return out or "Unnamed"

class ExportService:
    def export_volume(self, bundle: VolumeExportBundle, output_dir: str, fmt: str) -> str:
        out_dir = Path(output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        base = f"{bundle.metadata.title} - {bundle.volume.title}"
        filename = f"{_sanitize_filename(base)}.{fmt}"
        path = out_dir / filename

        if fmt == "epub":
            EPUBExporter().export(bundle, str(path))
        elif fmt == "pdf":
            PDFExporter().export(bundle, str(path))
        else:
            raise ValueError(f"Unsupported format: {fmt}")

        return str(path)

    def export_volumes(self, bundles: list[VolumeExportBundle], output_dir: str, fmt: str) -> list[str]:
        paths = []
        for b in bundles:
            paths.append(self.export_volume(b, output_dir, fmt))
        return paths
