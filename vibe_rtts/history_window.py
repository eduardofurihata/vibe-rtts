import subprocess

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit,
)
from PySide6.QtCore import Qt

from vibe_rtts.history import HistoryStore


class HistoryWindow(QWidget):
    def __init__(self, history_store: HistoryStore, parent=None):
        super().__init__(parent)
        self.store = history_store

        self.setWindowTitle("Vibe RTTS — History")
        self.setMinimumSize(500, 400)
        self.setWindowFlags(Qt.WindowType.Window)

        layout = QVBoxLayout(self)

        # Search bar
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search transcriptions...")
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)

        # List
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

        # Bottom bar
        bottom = QHBoxLayout()
        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.clicked.connect(self._on_clear)
        bottom.addWidget(self._clear_btn)
        bottom.addStretch()
        self._count_label = QLabel("0 items")
        bottom.addWidget(self._count_label)
        layout.addLayout(bottom)

        self._items = []  # Cache of all history items

    def refresh(self):
        self._items = self.store.get_all()
        self._render_items(self._items)

    def _render_items(self, items: list[dict]):
        self._list.clear()
        for item in items:
            ts = item["timestamp"][:16].replace("T", "  ")
            lang = f"[{item['language']}]" if item.get("language") else ""
            text_preview = item["text"][:100].replace("\n", " ")
            display = f"{ts}  {lang}  {text_preview}"

            widget_item = QListWidgetItem(display)
            widget_item.setData(Qt.ItemDataRole.UserRole, item)
            widget_item.setToolTip(item["text"])
            self._list.addItem(widget_item)

        self._count_label.setText(f"{len(items)} items")

    def _filter(self, text: str):
        if not text:
            self._render_items(self._items)
            return
        filtered = [
            item for item in self._items
            if text.lower() in item["text"].lower()
        ]
        self._render_items(filtered)

    def _on_item_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            subprocess.Popen(
                ["wl-copy", data["text"]],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self.setWindowTitle("Vibe RTTS — Copied!")
            # Reset title after 2 seconds
            from PySide6.QtCore import QTimer
            QTimer.singleShot(2000, lambda: self.setWindowTitle("Vibe RTTS — History"))

    def _on_clear(self):
        self.store.clear_all()
        self.refresh()
