from abc import ABC, abstractmethod
from export.bundle import VolumeExportBundle

class BaseExporter(ABC):
    @abstractmethod
    def export(self, bundle: VolumeExportBundle, output_path: str) -> None:
        raise NotImplementedError
