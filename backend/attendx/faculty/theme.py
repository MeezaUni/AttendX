"""System appearance and explicitly painted, high-contrast checkbox indicators."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QCheckBox, QStyle, QStyleOptionButton, QStylePainter


def apply_theme(widget, scheme=None):
    scheme = QApplication.styleHints().colorScheme() if scheme is None else scheme
    dark = scheme == Qt.ColorScheme.Dark
    colors = (
        {
            "canvas": "#0d1422",
            "surface": "#182235",
            "text": "#e7edf8",
            "muted": "#a6b6cf",
            "line": "#91a3bf",
            "soft_line": "#3d4b63",
            "hover": "#25344f",
            "header": "#202d43",
            "accent": "#4169c9",
            "green": "#183c31",
            "red": "#49262f",
            "amber": "#493c20",
        }
        if dark
        else {
            "canvas": "#f5f7fb",
            "surface": "#ffffff",
            "text": "#17243b",
            "muted": "#596b86",
            "line": "#687b98",
            "soft_line": "#cbd5e1",
            "hover": "#eaf0fb",
            "header": "#edf1f8",
            "accent": "#233e91",
            "green": "#dcfce7",
            "red": "#fee2e2",
            "amber": "#fef3c7",
        }
    )
    palette = QPalette(widget.palette())
    for role, value in (
        (QPalette.ColorRole.Window, "canvas"),
        (QPalette.ColorRole.Base, "surface"),
        (QPalette.ColorRole.AlternateBase, "header"),
        (QPalette.ColorRole.WindowText, "text"),
        (QPalette.ColorRole.Text, "text"),
        (QPalette.ColorRole.ButtonText, "text"),
        (QPalette.ColorRole.Button, "surface"),
        (QPalette.ColorRole.PlaceholderText, "muted"),
        (QPalette.ColorRole.Mid, "line"),
        (QPalette.ColorRole.Highlight, "accent"),
    ):
        palette.setColor(role, QColor(colors[value]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
    widget.setPalette(palette)
    widget.setStyleSheet(f"""
        QWidget {{ color:{colors["text"]}; background:{colors["canvas"]}; font-size:13px; }}
        QLineEdit, QComboBox, QSpinBox, QTableWidget, QListWidget, QPlainTextEdit {{
            background:{colors["surface"]}; color:{colors["text"]}; border:1px solid {colors["soft_line"]};
            border-radius:5px; padding:6px; }}
        QComboBox QAbstractItemView {{ background:{colors["surface"]}; color:{colors["text"]};
            selection-background-color:{colors["accent"]}; selection-color:white; }}
        QPushButton {{ background:{colors["surface"]}; color:{colors["text"]}; border:1px solid {colors["soft_line"]};
            border-radius:7px; padding:9px 12px; }}
        QPushButton:hover {{ background:{colors["hover"]}; }}
        QPushButton#primary {{ background:{colors["accent"]}; color:white; font-weight:600; }}
        QPushButton:disabled {{ color:{colors["muted"]}; background:{colors["header"]}; }}
        QHeaderView::section {{ color:{colors["text"]}; background:{colors["header"]}; padding:8px; border:0; }}
        QTabBar::tab {{ padding:10px 15px; color:{colors["text"]}; background:{colors["header"]}; }}
        QTabBar::tab:selected {{ background:{colors["surface"]}; }}
        QLabel {{ background:transparent; }}
        QCheckBox::indicator {{ width:20px; height:20px; }}
    """)
    return colors


class ReadableCheckBox(QCheckBox):
    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_CheckBox, option)
        rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(1 if self.isEnabled() else 0.5)
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Mid), 2))
        painter.setBrush(
            self.palette().color(QPalette.ColorRole.Highlight if self.isChecked() else QPalette.ColorRole.Base)
        )
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 3, 3)
        if self.isChecked():
            painter.setPen(QPen(QColor("white"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(x + w * 0.23, y + h * 0.51),
                        QPointF(x + w * 0.43, y + h * 0.72),
                        QPointF(x + w * 0.79, y + h * 0.28),
                    ]
                )
            )
