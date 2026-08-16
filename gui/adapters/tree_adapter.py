from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


class TreeAdapter:
    def __init__(self, tree: QTreeWidget):
        self.tree = tree

    def clear(self) -> None:
        self.tree.clear()

    def populate_from_payload(self, payload: dict, downloaded_urls: set[str] | None = None) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        downloaded_urls = downloaded_urls or set()

        series_title = payload.get("series_title") or "Unknown Series"

        root = QTreeWidgetItem([series_title, ""])
        root.setFlags(root.flags() | Qt.ItemIsUserCheckable)
        root.setCheckState(0, Qt.Unchecked)
        root.setData(0, Qt.UserRole, {"type": "series"})
        self.tree.addTopLevelItem(root)

        volumes = payload.get("volumes", []) or []
        for vi, vol in enumerate(volumes, start=1):
            vtitle = (vol.get("title") or f"Volume {vi}").strip()

            vitem = QTreeWidgetItem([vtitle, ""])
            vitem.setFlags(vitem.flags() | Qt.ItemIsUserCheckable)
            vitem.setCheckState(0, Qt.Unchecked)
            vitem.setData(0, Qt.UserRole, {"type": "volume", "volume_index": vi, "volume_title": vtitle})
            root.addChild(vitem)

            chapters = vol.get("chapters", []) or []
            for ci, ch in enumerate(chapters, start=1):
                ctitle = (ch.get("title") or f"Chapter {ci}").strip()
                curl = (ch.get("url") or "").strip()

                downloaded = curl in downloaded_urls
                citem = QTreeWidgetItem([ctitle, "Downloaded" if downloaded else "Not downloaded"])
                citem.setFlags(citem.flags() | Qt.ItemIsUserCheckable)
                citem.setCheckState(0, Qt.Unchecked)
                citem.setData(
                    0,
                    Qt.UserRole,
                    {
                        "type": "chapter",
                        "volume_index": vi,
                        "volume_title": vtitle,
                        "chapter_index": ci,
                        "chapter_title": ctitle,
                        "url": curl,
                    },
                )
                vitem.addChild(citem)

        root.setExpanded(True)
        self.tree.blockSignals(False)

    def apply_selection(self, selected_volume_indices: set[int], selected_chapter_urls: set[str]) -> None:
        root = self.root_item()
        if root is None:
            return

        self.tree.blockSignals(True)
        for i in range(root.childCount()):
            vitem = root.child(i)
            vdata = vitem.data(0, Qt.UserRole) or {}
            vi = int(vdata.get("volume_index") or 0)

            if vi in selected_volume_indices:
                vitem.setCheckState(0, Qt.Checked)
                for j in range(vitem.childCount()):
                    vitem.child(j).setCheckState(0, Qt.Checked)
                continue

            any_checked = False
            all_checked = vitem.childCount() > 0
            for j in range(vitem.childCount()):
                citem = vitem.child(j)
                cdata = citem.data(0, Qt.UserRole) or {}
                url = str(cdata.get("url") or "").strip()
                if url and url in selected_chapter_urls:
                    citem.setCheckState(0, Qt.Checked)
                    any_checked = True
                else:
                    citem.setCheckState(0, Qt.Unchecked)
                    all_checked = False

            if all_checked and vitem.childCount() > 0:
                vitem.setCheckState(0, Qt.Checked)
            elif any_checked:
                vitem.setCheckState(0, Qt.PartiallyChecked)
            else:
                vitem.setCheckState(0, Qt.Unchecked)

        self.tree.blockSignals(False)

    def propagate_item_state(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.UserRole) or {}
        if data.get("type") in ("series", "volume"):
            for i in range(item.childCount()):
                item.child(i).setCheckState(0, item.checkState(0))
        self.refresh_ancestors(item)

    def refresh_ancestors(self, item: QTreeWidgetItem) -> None:
        parent = item.parent()
        while parent is not None:
            checked = 0
            partial = 0
            total = parent.childCount()
            for i in range(total):
                state = parent.child(i).checkState(0)
                if state == Qt.Checked:
                    checked += 1
                elif state == Qt.PartiallyChecked:
                    partial += 1
            if checked == total and total > 0:
                parent.setCheckState(0, Qt.Checked)
            elif checked == 0 and partial == 0:
                parent.setCheckState(0, Qt.Unchecked)
            else:
                parent.setCheckState(0, Qt.PartiallyChecked)
            parent = parent.parent()

    def collect_selection_state(self) -> dict:
        selected_volume_indices: set[int] = set()
        selected_chapter_urls: set[str] = set()

        root = self.root_item()
        if root is None:
            return {"selected_volume_indices": [], "selected_chapter_urls": []}

        for i in range(root.childCount()):
            vitem = root.child(i)
            vdata = vitem.data(0, Qt.UserRole) or {}
            vi = int(vdata.get("volume_index") or 0)
            if vitem.checkState(0) == Qt.Checked:
                selected_volume_indices.add(vi)
                continue
            for j in range(vitem.childCount()):
                citem = vitem.child(j)
                if citem.checkState(0) != Qt.Checked:
                    continue
                cdata = citem.data(0, Qt.UserRole) or {}
                url = str(cdata.get("url") or "").strip()
                if url:
                    selected_chapter_urls.add(url)

        return {
            "selected_volume_indices": sorted(selected_volume_indices),
            "selected_chapter_urls": sorted(selected_chapter_urls),
        }

    def collect_export_payload(self) -> dict:
        chapters: list[dict] = []
        root = self.root_item()
        if root is None:
            return {"series_title": None, "chapters": [], "total_chapters": 0}

        def walk(node: QTreeWidgetItem) -> None:
            data = node.data(0, Qt.UserRole) or {}
            if data.get("type") == "chapter" and node.checkState(0) == Qt.Checked:
                chapters.append(data)
            for i in range(node.childCount()):
                walk(node.child(i))

        walk(root)
        return {
            "series_title": root.text(0),
            "chapters": chapters,
            "total_chapters": len(chapters),
        }

    def root_item(self) -> QTreeWidgetItem | None:
        if self.tree.topLevelItemCount() == 0:
            return None
        return self.tree.topLevelItem(0)
