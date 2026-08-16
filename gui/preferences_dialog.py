from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from utils.preferences import AppPreferences, PreferencesService, WidgetColorPreference


class PreferencesDialog(QDialog):
    preferences_saved = Signal(AppPreferences)

    def __init__(
        self,
        *,
        service: PreferencesService,
        preferences: AppPreferences,
        widget_labels: dict[str, str],
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.preferences = replace(preferences, widget_colors=dict(preferences.widget_colors))
        self.widget_labels = dict(widget_labels)
        self.color_rows: dict[str, dict[str, QLineEdit]] = {}

        self.setWindowTitle("Preferences")
        self.resize(720, 640)
        self.setModal(False)

        self._build_ui()
        self._load_preferences_into_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout()

        workspace_group = QGroupBox("Workspace")
        workspace_layout = QFormLayout()
        workspace_row = QHBoxLayout()
        self.workspace_root_input = QLineEdit()
        workspace_row.addWidget(self.workspace_root_input, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_workspace_root)
        workspace_row.addWidget(browse_btn)
        workspace_layout.addRow("Workspace Root:", workspace_row)
        workspace_group.setLayout(workspace_layout)
        root.addWidget(workspace_group)

        appearance_group = QGroupBox("Appearance")
        appearance_layout = QVBoxLayout()
        self.enable_colors_checkbox = QCheckBox("Enable custom widget colors")
        self.enable_colors_checkbox.toggled.connect(self._refresh_color_inputs_enabled)
        appearance_layout.addWidget(self.enable_colors_checkbox)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_body = QWidget()
        form = QFormLayout()
        for widget_id, label in self.widget_labels.items():
            row = QHBoxLayout()
            bg_input = QLineEdit()
            bg_input.setPlaceholderText("#RRGGBB")
            row.addWidget(QLabel("BG"))
            row.addWidget(bg_input)
            bg_btn = QPushButton("Pick")
            bg_btn.clicked.connect(lambda _=False, key=widget_id: self._pick_color(key, "background"))
            row.addWidget(bg_btn)

            fg_input = QLineEdit()
            fg_input.setPlaceholderText("#RRGGBB")
            row.addWidget(QLabel("Text"))
            row.addWidget(fg_input)
            fg_btn = QPushButton("Pick")
            fg_btn.clicked.connect(lambda _=False, key=widget_id: self._pick_color(key, "foreground"))
            row.addWidget(fg_btn)

            reset_btn = QPushButton("Reset")
            reset_btn.clicked.connect(lambda _=False, key=widget_id: self._reset_widget_colors(key))
            row.addWidget(reset_btn)

            form.addRow(label + ":", row)
            self.color_rows[widget_id] = {"background": bg_input, "foreground": fg_input}

        scroll_body.setLayout(form)
        scroll.setWidget(scroll_body)
        appearance_layout.addWidget(scroll)

        reset_all_btn = QPushButton("Reset All Colors")
        reset_all_btn.clicked.connect(self._reset_all_colors)
        appearance_layout.addWidget(reset_all_btn)

        appearance_group.setLayout(appearance_layout)
        root.addWidget(appearance_group, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.close)
        buttons.addWidget(cancel_btn)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)

        self.setLayout(root)

    def _load_preferences_into_ui(self) -> None:
        self.workspace_root_input.setText(self.preferences.workspace_root or "")
        self.enable_colors_checkbox.setChecked(self.preferences.widget_colors_enabled)
        for widget_id, editors in self.color_rows.items():
            pref = self.preferences.widget_colors.get(widget_id, WidgetColorPreference())
            editors["background"].setText(pref.background or "")
            editors["foreground"].setText(pref.foreground or "")
        self._refresh_color_inputs_enabled()

    def _refresh_color_inputs_enabled(self) -> None:
        enabled = self.enable_colors_checkbox.isChecked()
        for editors in self.color_rows.values():
            for editor in editors.values():
                editor.setEnabled(enabled)

    def _browse_workspace_root(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select Workspace Root")
        if directory:
            self.workspace_root_input.setText(directory)

    def _pick_color(self, widget_id: str, field_name: str) -> None:
        editors = self.color_rows[widget_id]
        initial = QColor(editors[field_name].text().strip() or "#ffffff")
        color = QColorDialog.getColor(initial, self, "Select Color")
        if color.isValid():
            editors[field_name].setText(color.name())

    def _reset_widget_colors(self, widget_id: str) -> None:
        editors = self.color_rows[widget_id]
        editors["background"].clear()
        editors["foreground"].clear()

    def _reset_all_colors(self) -> None:
        for widget_id in self.color_rows:
            self._reset_widget_colors(widget_id)

    def _save(self) -> None:
        try:
            widget_colors: dict[str, WidgetColorPreference] = {}
            for widget_id, editors in self.color_rows.items():
                background = self._validate_color(editors["background"].text().strip())
                foreground = self._validate_color(editors["foreground"].text().strip())
                if background or foreground:
                    widget_colors[widget_id] = WidgetColorPreference(background=background, foreground=foreground)

            workspace_root = self.workspace_root_input.text().strip() or None
            updated = AppPreferences(
                workspace_root=workspace_root,
                widget_colors_enabled=self.enable_colors_checkbox.isChecked(),
                widget_colors=widget_colors,
            )
            self.service.save(updated)
            self.preferences = updated
            self.preferences_saved.emit(updated)
            self.close()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Preferences", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"{type(e).__name__}: {e}")

    @staticmethod
    def _validate_color(value: str) -> str | None:
        if not value:
            return None
        color = QColor(value)
        if not color.isValid():
            raise ValueError(f"Invalid color value: {value}")
        return color.name()

