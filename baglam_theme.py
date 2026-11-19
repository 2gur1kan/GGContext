"""ggContext - koyu / açık tema (bordo tonlarında)

Renkler tek yerde (belirteçler) tutulur; QSS bunlardan üretilir. Qt'ye yalnızca ApplyTheme dokunur
"""
from __future__ import annotations

import re

DARK = {
    "bg": "#140b0e",
    "surface": "#1d0f14",
    "surface2": "#29151c",
    "input_bg": "#190d11",
    "border": "#3f202a",
    "text": "#f3e8ea",
    "muted": "#b79ea5",
    "accent": "#b3304a",
    "accent_hover": "#cc4260",
    "accent_text": "#ffffff",
    "select": "#4d1c2b",
    "danger": "#ff7b7b",
}

LIGHT = {
    "bg": "#f8f1f2",
    "surface": "#ffffff",
    "surface2": "#f1e5e7",
    "input_bg": "#ffffff",
    "border": "#e2cfd3",
    "text": "#2b1519",
    "muted": "#7d5f66",
    "accent": "#8c1d35",
    "accent_hover": "#a62b47",
    "accent_text": "#ffffff",
    "select": "#f4dadf",
    "danger": "#c0392b",
}

THEMES = {"dark": DARK, "light": LIGHT}

QSS_TEMPLATE = """
QMainWindow, QDialog { background: @bg@; }
QWidget { color: @text@; }
QToolTip { background: @surface2@; color: @text@; border: 1px solid @border@; padding: 5px 8px; }

QFrame#sidebar { background: @surface@; border-right: 1px solid @border@; }
QFrame#panel { background: @bg@; border-left: 1px solid @border@; }
QFrame#toolbar { background: @surface@; border-bottom: 1px solid @border@; }
QLabel#brand { font-size: 13pt; font-weight: 700; padding: 4px 2px; }
QLabel#muted { color: @muted@; }
QLabel#section { color: @muted@; font-size: 8pt; font-weight: 700; padding: 10px 2px 2px 2px; }

QListWidget { background: transparent; border: none; outline: 0; }
QListWidget::item { padding: 8px 10px; border-radius: 8px; margin: 1px 2px; }
QListWidget::item:hover { background: @surface2@; }
QListWidget::item:selected { background: @select@; color: @text@; }
QListWidget#framed { background: @input_bg@; border: 1px solid @border@; border-radius: 10px; padding: 3px; }

QPushButton, QToolButton {
    background: @surface2@; border: 1px solid @border@; border-radius: 8px; padding: 6px 12px;
}
QPushButton:hover, QToolButton:hover { border-color: @accent@; }
QPushButton:pressed, QToolButton:pressed { background: @border@; }
QPushButton:disabled, QToolButton:disabled { color: @muted@; }
QPushButton:checked, QToolButton:checked { background: @select@; border-color: @accent@; }
QPushButton#primary { background: @accent@; color: @accent_text@; border: none; font-weight: 600; padding: 7px 14px; }
QPushButton#primary:hover { background: @accent_hover@; }
QPushButton#primary:disabled { background: @border@; color: @muted@; }
QPushButton#flat, QToolButton#nav { background: transparent; border: 1px solid transparent; }
QPushButton#flat:hover, QToolButton#nav:hover { background: @surface2@; border-color: @border@; }
QToolButton::menu-indicator { image: none; width: 0; }

QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background: @input_bg@; border: 1px solid @border@; border-radius: 8px; padding: 6px 8px;
    selection-background-color: @accent@; selection-color: @accent_text@;
}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: @accent@; }
QLineEdit#address { border-radius: 15px; padding: 6px 14px; }
QComboBox QAbstractItemView {
    background: @surface@; border: 1px solid @border@; outline: 0;
    selection-background-color: @select@; selection-color: @text@;
}

QTabWidget::pane { border: none; }
QTabBar::tab {
    background: transparent; color: @muted@; padding: 9px 16px; margin-right: 2px;
    border-top-left-radius: 8px; border-top-right-radius: 8px; border-bottom: 2px solid transparent;
}
QTabBar::tab:hover { color: @text@; background: @surface2@; }
QTabBar::tab:selected { color: @text@; background: @surface@; border-bottom: 2px solid @accent@; font-weight: 600; }

QProgressBar#loading { background: transparent; border: none; min-height: 3px; max-height: 3px; }
QProgressBar#loading::chunk { background: @accent@; }

QSplitter::handle:horizontal { width: 1px; background: @border@; }
QSplitter::handle:vertical { height: 1px; background: @border@; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: @border@; border-radius: 5px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: @muted@; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: @border@; border-radius: 5px; min-width: 32px; }
QScrollBar::handle:horizontal:hover { background: @muted@; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QMenu { background: @surface@; border: 1px solid @border@; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 7px 20px; border-radius: 6px; }
QMenu::item:selected { background: @select@; }
QMenu::separator { height: 1px; background: @border@; margin: 4px 8px; }

QStatusBar { background: @surface@; border-top: 1px solid @border@; color: @muted@; }
QCheckBox, QRadioButton { spacing: 8px; }
"""


def BuildQss(name: str) -> str:
    colors = THEMES[name]
    return re.sub(r"@(\w+)@", lambda gg: colors[gg.group(1)], QSS_TEMPLATE)


def _luminance(hexColor: str) -> float:
    h = hexColor.lstrip("#")
    r, g, b = (int(h[gg:gg + 2], 16) / 255 for gg in (0, 2, 4))

    def lin(c: float) -> float: return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def ContrastRatio(a: str, b: str) -> float:
    """WCAG kontrast oranı (okunabilirlik denetimi için)."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def ApplyTheme(app, name: str) -> None:
    """Paleti ve stil sayfasını uygular (Fusion stiliyle birlikte kullanılır)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPalette

    c = THEMES[name]
    try:  # Qt 6.8+: uygulamanın renk şeması (bazı Qt bileşenleri buna uyar)
        setter = getattr(app.styleHints(), "setColorScheme", None)
        if setter is not None: setter(Qt.ColorScheme.Dark if name == "dark" else Qt.ColorScheme.Light)
    except Exception:  # noqa: BLE001
        pass

    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: c["bg"],
        QPalette.ColorRole.WindowText: c["text"],
        QPalette.ColorRole.Base: c["input_bg"],
        QPalette.ColorRole.AlternateBase: c["surface"],
        QPalette.ColorRole.Text: c["text"],
        QPalette.ColorRole.Button: c["surface2"],
        QPalette.ColorRole.ButtonText: c["text"],
        QPalette.ColorRole.ToolTipBase: c["surface2"],
        QPalette.ColorRole.ToolTipText: c["text"],
        QPalette.ColorRole.Highlight: c["accent"],
        QPalette.ColorRole.HighlightedText: c["accent_text"],
        QPalette.ColorRole.PlaceholderText: c["muted"],
        QPalette.ColorRole.Link: c["accent_hover"],
    }
    for role, color in roles.items(): pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["muted"]))
    app.setPalette(pal)
    app.setStyleSheet(BuildQss(name))


def _colorref(hexColor: str) -> int:
    h = hexColor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r      # Windows COLORREF: 0x00BBGGRR


def ApplyTitlebar(window, name: str) -> bool:
    """Windows başlık çubuğunu temaya uydurur (DWM). Windows 11'de çubuk, kenarlık ve yazı rengi temanın bordosu
    olur; Windows 10'da yalnızca koyu/açık kip uygulanır. Başka sistemlerde ya da hata olursa sessizce atlanır."""
    import sys

    if sys.platform != "win32": return False
    try:
        import ctypes
        from ctypes import wintypes

        c = THEMES[name]
        hwnd = wintypes.HWND(int(window.winId()))
        dwm = ctypes.windll.dwmapi

        def put(attr: int, value: int) -> int:
            v = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

        dark = 1 if name == "dark" else 0
        if put(20, dark) != 0:          # DWMWA_USE_IMMERSIVE_DARK_MODE (eski Windows 10 sürümlerinde 19)
            put(19, dark)
        put(35, _colorref(c["surface"]))   # DWMWA_CAPTION_COLOR (Windows 11)
        put(36, _colorref(c["text"]))      # DWMWA_TEXT_COLOR
        put(34, _colorref(c["border"]))    # DWMWA_BORDER_COLOR
        return True
    except Exception:  # noqa: BLE001
        return False
