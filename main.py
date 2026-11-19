"""ggContext'i başlatır:  python main.py"""
import os
import sys


def main() -> int:
    try:
        from PySide6.QtCore import QCoreApplication, Qt
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 kurulu değil. Şunu çalıştır:  pip install -r requirements.txt")
        return 1

    import baglam_core as core
    import baglam_theme

    store = core.Store()
    core.CleanupProfiles(store)      # silinen/temizlenen sekmelerin oturum klasörlerini sil
    store.EnsureDefaultSites()
    name = store.GetMeta("theme", "dark")
    if name not in baglam_theme.THEMES: name = "dark"

    # koyu temada, sitelerin kendi koyu temasını kullanması için tarayıcıya "koyu tercih" bildirilir
    # QtWebEngine başlamadan ÖNCE ayarlanmalıdır; tema değişince uygulamanın yeniden açılması gerekir
    if name == "dark":
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = core.AddChromiumFlag(
            os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""), "--force-dark-mode"
        )

    # QtWebEngine, QApplication oluşturulmadan ÖNCE içe aktarılmalı (baglam_ui bunu yapar)
    from baglam_ui import MainWindow

    try:
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    except AttributeError:
        pass
    if sys.platform == "win32":   # görev çubuğunda python.exe yerine kendi simgesiyle ayrı uygulama olarak görünsün
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ggContext.App")
        except Exception: pass
    app = QApplication(sys.argv)
    app.setApplicationName("ggContext")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    import baglam_icon
    icon = baglam_icon.LoadIcon()
    if icon is not None: app.setWindowIcon(icon)
    baglam_theme.ApplyTheme(app, name)

    import baglam_shortcut
    baglam_shortcut.EnsureStartMenuShortcut(store)   # Windows aramasında görünsün (yalnızca exe iken)

    win = MainWindow(store, name)
    win.show()
    return app.exec()


if __name__ == "__main__": sys.exit(main())
