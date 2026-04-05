import subprocess

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit,
)
from PySide6.QtCore import Qt, QTimer

from vibe_rtts.history import HistoryStore


class HistoryItemWidget(QWidget):
    """Custom widget for each history row: timestamp + text + Copy button."""

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self._text = item["text"]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        # Left side: timestamp + text
        left = QVBoxLayout()
        left.setSpacing(0)

        ts = item["timestamp"][:16].replace("T", "  ")
        lang = f" [{item['language']}]" if item.get("language") else ""
        header = QLabel(f"<span style='color: grey; font-size: 11px;'>{ts}{lang}</span>")
        left.addWidget(header)

        preview = item["text"][:150].replace("\n", " ")
        text_label = QLabel(preview)
        text_label.setWordWrap(True)
        text_label.setToolTip(item["text"])
        left.addWidget(text_label)

        layout.addLayout(left, stretch=1)

        # Right side: Copy button
        copy_btn = QPushButton("Copy")
        copy_btn.setFixedWidth(60)
        copy_btn.clicked.connect(self._on_copy)
        layout.addWidget(copy_btn)

    def _on_copy(self):
        subprocess.Popen(
            ["wl-copy", self._text],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        sender = self.sender()
        sender.setText("Copied!")
        QTimer.singleShot(1500, lambda: sender.setText("Copy"))


class HistoryWindow(QWidget):
    def __init__(self, history_store: HistoryStore, parent=None):
        super().__init__(parent)
        self.store = history_store

        self.setWindowTitle("Vibe RTTS — History")
        self.setMinimumSize(550, 450)
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

        self._items = []

    def refresh(self):
        self._items = self.store.get_all()
        self._render_items(self._items)

    def _render_items(self, items: list[dict]):
        self._list.clear()
        for item in items:
            widget = HistoryItemWidget(item)
            list_item = QListWidgetItem()
            list_item.setSizeHint(widget.sizeHint())
            self._list.addItem(list_item)
            self._list.setItemWidget(list_item, widget)

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

    def _on_clear(self):
        self.store.clear_all()
        self.refresh()
