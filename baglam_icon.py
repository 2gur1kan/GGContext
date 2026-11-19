"""ggContext simgesi: siyah zemin üstüne bordo G (dosyaya ihtiyaç duymadan koda gömülü)"""
import base64

ICON_PNG_B64 = (
    "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"
)


def LoadIcon():
    """gömülü PNG'den QIcon üretir; Qt yüklü değilse ya da çözülemezse None döner"""
    try:
        from PySide6.QtGui import QIcon, QPixmap
        pm = QPixmap()
        if not pm.loadFromData(base64.b64decode(ICON_PNG_B64)): return None
        return QIcon(pm)
    except Exception: return None
