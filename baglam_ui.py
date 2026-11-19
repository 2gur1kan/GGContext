"""ggContext - PySide6 (Qt) arayüzü: gömülü web sekmeleri + bağlam paneli."""
from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QMimeData, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QSystemTrayIcon,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import baglam_core as core
import baglam_theme as theme

# QtWebEngine bulunamazsa uygulama yine açılır; yalnızca web sekmeleri çalışmaz
try:
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView

    WEBENGINE_OK = True
except Exception:  # noqa: BLE001
    WEBENGINE_OK = False

ROLE_ID = Qt.ItemDataRole.UserRole
ROLE_KIND = Qt.ItemDataRole.UserRole + 1


def _preview(text: str, n: int = 64) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[: n - 1] + "…"


def _btn(text, slot=None, primaryFlag=False, flatFlag=False, tip="", cls=QPushButton):
    b = cls(text)
    if primaryFlag: b.setObjectName("primary")
    elif flatFlag: b.setObjectName("flat")
    if tip: b.setToolTip(tip)
    if slot is not None: b.clicked.connect(slot)
    return b


def _label(text, name="", wrapFlag=False):
    lab = QLabel(text)
    if name: lab.setObjectName(name)
    lab.setWordWrap(wrapFlag)
    return lab


#################### web sekmesi

if WEBENGINE_OK:

    class _Page(QWebEnginePage):
        """Açılır pencereleri (ör. giriş pencereleri) aynı oturumla küçük bir pencerede açar."""

        def __init__(self, profile, parent, owner):
            super().__init__(profile, parent)
            self._owner = owner

        def createWindow(self, _type):
            dlg = QDialog(self._owner)
            dlg.setWindowTitle("Pencere")
            dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dlg.resize(520, 720)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(0, 0, 0, 0)
            view = QWebEngineView(dlg)
            page = _Page(self.profile(), view, dlg)
            view.setPage(page)
            lay.addWidget(view)
            page.windowCloseRequested.connect(dlg.close)
            page.titleChanged.connect(dlg.setWindowTitle)
            dlg.show()
            return page


    class _WebView(QWebEngineView):
        """Sağ tık menüsüne "Başka sekmeye sor" ve köprü işlemlerini ekler."""

        def __init__(self, parent, owner):
            super().__init__(parent)
            self._owner = owner

        def contextMenuEvent(self, event):
            menu = None
            try:
                menu = self.createStandardContextMenu()   # Qt'nin kendi menüsü (Kopyala, Yapıştır, ...)
            except Exception:  # noqa: BLE001
                menu = None
            if menu is None:
                menu = QMenu(self)
                WA = QWebEnginePage.WebAction
                menu.addAction("Kopyala", lambda: self.triggerPageAction(WA.Copy))
                menu.addAction("Yapıştır", lambda: self.triggerPageAction(WA.Paste))
                menu.addAction("Tümünü seç", lambda: self.triggerPageAction(WA.SelectAll))
            menu.addSeparator()
            self._owner.contextMenuRequested.emit(self._owner, menu, core.CleanSelection(self.selectedText()))
            menu.exec(event.globalPos())


class BrowserTab(QWidget):
    """Tek bir sitenin (ör. Claude) gömülü tarayıcısı. Her sekmenin kendi çerez/oturum klasörü vardır."""

    pasteRequested = Signal(object)
    saveRequested = Signal(object)
    editRequested = Signal(object)
    removeRequested = Signal(object)
    wipeRequested = Signal(object)
    summarizeRequested = Signal(object)
    delegateSummaryRequested = Signal(object)
    filesRequested = Signal(object)
    renameRequested = Signal(object)
    urlSaved = Signal(object, str)
    contextMenuRequested = Signal(object, object, str)
    tabTitleChanged = Signal(object, str)
    forceDarkChanged = Signal(object, bool)
    message = Signal(str)

    def __init__(self, site, parent=None, bg="#140b0e", forceDarkFlag=False, lastUrl=""):
        super().__init__(parent)
        site = dict(site)
        self.siteId = site["id"]
        self.name = site["name"]
        self.url = site["url"]
        self.model = site["model"]
        self.loadedFlag = False
        self.lastUrl = lastUrl or ""   # en son açık sayfa (açılışta sohbet kaldığı yerden gelir)
        self.view = None
        self.page = None
        self.profile = None
        self._bg = bg
        self._forceDarkFlag = bool(forceDarkFlag)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._buildToolbar())
        self.progress = QProgressBar()
        self.progress.setObjectName("loading")
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.hide()
        root.addWidget(self.progress)

        if WEBENGINE_OK: self._initWeb(root)
        else:
            note = _label(
                "Web bileşeni (QtWebEngine) bulunamadı.\n"
                "Şunu çalıştır:  pip install --upgrade PySide6\n"
                "Bağlam paneli web sekmeleri olmadan da çalışır.",
                "muted", wrapFlag=True,
            )
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(note, 1)
            for b in (self.backBtn, self.fwdBtn, self.reloadBtn, self.homeBtn, self.pasteBtn, self.summarizeBtn, self.filesBtn, self.lastBtn):
                b.setEnabled(False)

    #################### kurulum

    def _buildToolbar(self):
        bar = QFrame()
        bar.setObjectName("toolbar")
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)
        h = QHBoxLayout()
        h.setSpacing(6)
        outer.addLayout(h)

        def nav(text, tip, slot):
            b = QToolButton()
            b.setObjectName("nav")
            b.setText(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # odak sayfadaki mesaj kutusunda kalsın
            b.clicked.connect(slot)
            h.addWidget(b)
            return b

        self.backBtn = nav("←", "Geri", lambda: self.view and self.view.back())
        self.fwdBtn = nav("→", "İleri", lambda: self.view and self.view.forward())
        self.reloadBtn = nav("↻", "Yenile", lambda: self.view and self.view.reload())
        self.homeBtn = nav("⌂", "Sitenin ana adresine dön", self.GoHome)

        self.addr = QLineEdit()
        self.addr.setObjectName("address")
        self.addr.setPlaceholderText("Adres")
        self.addr.returnPressed.connect(self._go)
        h.addWidget(self.addr, 1)

        menuBtn = QToolButton()
        menuBtn.setObjectName("nav")
        menuBtn.setText("⋯")
        menuBtn.setToolTip("Sekme ayarları")
        menuBtn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(menuBtn)
        menu.addAction("Bu sohbet içinde bağlam çıkar", lambda: self.summarizeRequested.emit(self))
        menu.addAction("Seçili metni cevap olarak kaydet", lambda: self.saveRequested.emit(self))
        menu.addSeparator()
        menu.addAction("Yakınlaştır", lambda: self.Zoom(0.1))
        menu.addAction("Uzaklaştır", lambda: self.Zoom(-0.1))
        menu.addAction("Yakınlaştırmayı sıfırla", lambda: self.Zoom(0))
        menu.addSeparator()
        self.darkAct = menu.addAction("Sayfayı zorla koyulaştır (yedek yol)")
        self.darkAct.setCheckable(True)
        self.darkAct.setChecked(self._forceDarkFlag)
        self.darkAct.toggled.connect(self._onForceDark)
        if not (WEBENGINE_OK and hasattr(QWebEngineSettings.WebAttribute, "ForceDarkMode")):
            self.darkAct.setEnabled(False)
            self.darkAct.setText("Sayfayı zorla koyulaştır (Qt 6.7+ gerekir)")
        menu.addSeparator()
        menu.addAction("Adı değiştir…", lambda: self.renameRequested.emit(self))
        menu.addAction("Ad / adres düzenle…", lambda: self.editRequested.emit(self))
        menu.addAction("Oturumu temizle…", lambda: self.wipeRequested.emit(self))
        menu.addAction("Sekmeyi kaldır…", lambda: self.removeRequested.emit(self))
        menuBtn.setMenu(menu)
        h.addWidget(menuBtn)

        r2 = QHBoxLayout()
        r2.setSpacing(6)
        outer.addLayout(r2)

        self.summarizeBtn = QPushButton("Bağlamı çıkar")
        self.summarizeBtn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.summarizeBtn.setToolTip(
            "Bu sohbetin metnini okur ve sağ paneldeki Özet sekmesinde seçili olan sekmeye (ör. Gemini) "
            "bağlam çıkarma isteğiyle birlikte yapıştırır; seni o sekmeye götürür. Enter'a sen basarsın.\n"
            "Cevap gelince sitedeki Kopyala düğmesine bas; özet otomatik tanınır ve konuya aktarılır.\n"
            "Özeti bu sohbetin kendi yapay zekasına çıkarttırmak için ⋯ menüsündeki "
            "\"Bu sohbet içinde bağlam çıkar\"ı kullan."
        )
        self.summarizeBtn.clicked.connect(lambda: self.delegateSummaryRequested.emit(self))
        r2.addWidget(self.summarizeBtn)

        self.pasteBtn = QPushButton("Bağlamı yapıştır")
        self.pasteBtn.setObjectName("primary")
        self.pasteBtn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pasteBtn.setToolTip(
            "Seçili konunun bağlam paketini hazırlar ve bu sayfadaki mesaj kutusuna yapıştırır.\n"
            "Önce sohbetin mesaj kutusuna bir kez tıkla. Göndermek (Enter) sana kalmış."
        )
        self.pasteBtn.clicked.connect(lambda: self.pasteRequested.emit(self))
        r2.addWidget(self.pasteBtn)

        self.filesBtn = QPushButton("Dosyaları ekle…")
        self.filesBtn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.filesBtn.setToolTip(
            "Konunun dosyalarından seçtiklerini şu anda açık olan sohbete ekler (metin olarak ya da dosya/zip olarak).\n"
            "İstediğin an, çalışırken kullanabilirsin (Ctrl+Shift+F)."
        )
        self.filesBtn.clicked.connect(lambda: self.filesRequested.emit(self))
        r2.addWidget(self.filesBtn)

        self.lastBtn = QPushButton("Son cevabı seç")
        self.lastBtn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lastBtn.setToolTip(
            "Açık sohbetteki yapay zekanın son mesajını seçer (Ctrl+Shift+L). Sonra Ctrl+C ile kopyala ya da "
            "sağ tık > Başka sekmeye sor / Çevir kullan."
        )
        self.lastBtn.clicked.connect(self.SelectLastReply)
        r2.addWidget(self.lastBtn)
        r2.addStretch(1)
        return bar

    def _initWeb(self, root):
        storage = core.ProfileDir(self.siteId)
        (storage / "data").mkdir(parents=True, exist_ok=True)
        (storage / "cache").mkdir(parents=True, exist_ok=True)
        self.profile = QWebEngineProfile(f"site_{self.siteId}", self)
        self.profile.setPersistentStoragePath(str(storage / "data"))
        self.profile.setCachePath(str(storage / "cache"))
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.profile.setHttpAcceptLanguage("tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7")
        self.profile.downloadRequested.connect(self._onDownload)

        self.view = _WebView(self, self)
        self.page = _Page(self.profile, self.view, self)
        # sitelerdeki "Kopyala" düğmelerinin çalışması için
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        self.view.setPage(self.page)
        self.SetPageBackground(self._bg)
        self.SetForceDark(self._forceDarkFlag)
        self.view.urlChanged.connect(self._onUrl)
        self.page.titleChanged.connect(lambda gg: self.tabTitleChanged.emit(self, gg))
        self.view.loadStarted.connect(self._onLoadStarted)
        self.view.loadProgress.connect(self.progress.setValue)
        self.view.loadFinished.connect(lambda gg: self.progress.hide())
        root.addWidget(self.view, 1)

    #################### davranış

    def EnsureLoaded(self):
        """Sayfa, sekme ilk kez görüntülendiğinde yüklenir (açılışta 3 siteyi birden yüklememek için)."""
        if self.view is not None and not self.loadedFlag:
            self.loadedFlag = True
            self.view.load(QUrl(self.lastUrl or self.url))

    def ApplySite(self, site):
        site = dict(site)
        urlChangeFlag = site["url"] != self.url
        if urlChangeFlag: self.lastUrl = ""
        self.name, self.url, self.model = site["name"], site["url"], site["model"]
        if urlChangeFlag and self.view is not None:
            self.loadedFlag = True
            self.view.load(QUrl(self.url))

    def GoHome(self):
        if self.view is not None:
            self.loadedFlag = True
            self.view.load(QUrl(self.url))

    def _go(self):
        url = core.NormalizeUrl(self.addr.text())
        if not url:
            self.message.emit("Geçerli bir adres yaz (ör. claude.ai).")
            return
        if self.view is not None:
            self.loadedFlag = True
            self.view.load(QUrl(url))
            self.view.setFocus()

    def _onUrl(self, url):
        text = url.toString()
        if not self.addr.hasFocus(): self.addr.setText(text)
        if text.startswith(("http://", "https://")):
            self.lastUrl = text
            self.urlSaved.emit(self, text)

    def _onLoadStarted(self):
        self.progress.setValue(5)
        self.progress.show()

    def Zoom(self, deltaFlag):
        if self.view is None: return
        z = 1.0 if deltaFlag == 0 else self.view.zoomFactor() + deltaFlag
        self.view.setZoomFactor(max(0.3, min(3.0, z)))

    def SetPageBackground(self, color: str):
        """Sayfa yüklenirken görünen arka plan (koyu temada beyaz çakmayı önler)."""
        self._bg = color
        if self.page is not None: self.page.setBackgroundColor(QColor(color))

    def SetForceDark(self, on: bool):
        """Qt 6.7+: sayfayı otomatik koyulaştırır. Sitenin kendi koyu teması çalışmıyorsa yedek yoldur."""
        self._forceDarkFlag = bool(on)
        if not WEBENGINE_OK or self.page is None: return
        attr = getattr(QWebEngineSettings.WebAttribute, "ForceDarkMode", None)
        if attr is not None: self.page.settings().setAttribute(attr, bool(on))

    def _onForceDark(self, on):
        self.SetForceDark(on)
        self.forceDarkChanged.emit(self, bool(on))

    def SelectedText(self) -> str: return self.view.selectedText() if self.view is not None else ""

    def PasteIntoPage(self, delay=80):
        """Panodaki metni sayfada odaktaki alana yapıştırır (göndermez)."""
        if self.view is None: return
        self.view.setFocus()
        QTimer.singleShot(
            delay, lambda: self.view.triggerPageAction(QWebEnginePage.WebAction.Paste)
        )

    def SelectLastReply(self):
        """Açık sohbetteki yapay zekanın son mesajını sayfada seçer (sitenin yapısına göre; bulunamazsa bildirir)."""
        if self.view is None: return
        sels = core.LastReplySelectors(self.view.url().toString())
        if not sels:
            self.message.emit("Bu site için son cevap seçici tanımlı değil; cevabı elle seç.")
            return
        js = core.LastReplyJs(sels)

        def done(n):
            if n:
                self.message.emit(
                    f"Son cevap seçildi ({n} karakter). Ctrl+C ile kopyala ya da sağ tık > Başka sekmeye sor / Çevir.")
            else:
                self.message.emit(
                    "Son cevap bulunamadı (sohbet açık değil ya da sitenin sayfa yapısı değişmiş olabilir). "
                    "Cevabı elle seçebilirsin.")

        self.view.setFocus()
        try:
            self.page.runJavaScript(js, done)
        except TypeError:
            self.page.runJavaScript(js, 0, done)

    def ReadPageText(self, callback):
        """Sayfada görünen metni (açık sohbeti) okur; sonuç callback(metin) ile gelir. Hiçbir şey göndermez."""
        if self.page is None:
            callback("")
            return
        self.page.toPlainText(callback)

    def ClearSessionNow(self):
        """Çerezleri ve önbelleği hemen siler (tam silme bir sonraki açılışta tamamlanır)."""
        if self.profile is not None:
            self.profile.cookieStore().deleteAllCookies()
            self.profile.clearHttpCache()

    def _onDownload(self, req):
        folder = Path.home() / "Downloads"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            folder = Path.home()
        name = Path(req.downloadFileName() or "indirilen_dosya").name
        dest = folder / name
        n = 2
        while dest.exists():
            dest = folder / f"{Path(name).stem}_{n}{Path(name).suffix}"
            n += 1
        req.setDownloadDirectory(str(folder))
        req.setDownloadFileName(dest.name)
        req.accept()
        self.message.emit(f"İndiriliyor: {dest.name}")

        def done():
            if req.isFinished(): self.message.emit(f"İndirildi: {dest}")

        req.isFinishedChanged.connect(done)

    def Shutdown(self):
        """Önce görünüm ve sayfa, sonra profil silinir (Qt bu sırayı bekler)."""
        if self.view is not None: self.view.deleteLater()
        if self.profile is not None: self.profile.deleteLater()
        self.deleteLater()


#################### sekme ekle/düzenle

class SiteDialog(QDialog):
    def __init__(self, parent=None, site=None, takenNames=()):
        super().__init__(parent)
        self.setWindowTitle("Ad / adres düzenle" if site else "Hesap / sekme ekle")
        self.setMinimumWidth(460)
        self._taken = {gg.casefold() for gg in takenNames}
        self._values = None

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 14)
        v.setSpacing(12)
        form = QFormLayout()
        form.setSpacing(10)
        self.preset = QComboBox()
        for name, _url, _model in core.PRESET_SITES: self.preset.addItem(name)
        self.preset.addItem("Özel…")
        self.nameEdit = QLineEdit()
        self.urlEdit = QLineEdit()
        self.urlEdit.setPlaceholderText("https://…")
        self.modelCombo = QComboBox()
        self.modelCombo.setEditable(True)
        self.modelCombo.addItems(list(core.DEFAULT_MODELS.keys()))
        if site is None: form.addRow("Hazır:", self.preset)
        form.addRow("Sekme adı:", self.nameEdit)
        form.addRow("Adres:", self.urlEdit)
        form.addRow("Model türü:", self.modelCombo)
        v.addLayout(form)
        v.addWidget(_label(
            "Giriş bilgilerini uygulama saklamaz: sitenin kendi giriş ekranından girersin, oturum bu sekmeye özel "
            "yerel bir klasörde (tarayıcı gibi) tutulur. Bazı siteler, özellikle Google ile girişte, gömülü "
            "tarayıcıları engelleyebilir; böyle olursa e-posta/kod ile girişi dene.",
            "muted", wrapFlag=True,
        ))
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        v.addWidget(box)

        if site is not None:
            site = dict(site)
            self.nameEdit.setText(site["name"])
            self.urlEdit.setText(site["url"])
            self.modelCombo.setCurrentText(site["model"])
        else:
            self.preset.currentIndexChanged.connect(self._onPreset)
            self._onPreset(0)

    def _onPreset(self, index):
        if index < len(core.PRESET_SITES):
            name, url, model = core.PRESET_SITES[index]
            base, n = name, 2
            while name.casefold() in self._taken:
                name = f"{base} {n}"
                n += 1
            self.nameEdit.setText(name)
            self.urlEdit.setText(url)
            self.modelCombo.setCurrentText(model)
        else:
            self.nameEdit.clear()
            self.urlEdit.clear()
            self.modelCombo.setCurrentText("Diğer")

    def accept(self):
        name = self.nameEdit.text().strip()
        url = core.NormalizeUrl(self.urlEdit.text())
        if not name:
            QMessageBox.warning(self, "Eksik bilgi", "Sekme için bir ad yaz.")
            return
        if not url:
            QMessageBox.warning(self, "Geçersiz adres", "Geçerli bir web adresi yaz (ör. claude.ai).")
            return
        self._values = {"name": name, "url": url, "model": self.modelCombo.currentText().strip() or "Diğer"}
        super().accept()

    def values(self): return self._values


class TranslateBox(QDialog):
    """Seçili metni Google Çeviri'de açan küçük, yüzen kutu (kaynak dili Google algılar)."""

    def __init__(self, parent, bg="#140b0e"):
        super().__init__(parent)
        self.setWindowTitle("Google Çeviri")
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.resize(470, 560)
        self._text = ""
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        row = QHBoxLayout()
        self.note = _label("", "muted", wrapFlag=True)
        row.addWidget(self.note, 1)
        row.addWidget(_btn("→ Türkçe", lambda: self.ShowText(self._text, "tr")))
        row.addWidget(_btn("→ İngilizce", lambda: self.ShowText(self._text, "en")))
        v.addLayout(row)
        self.profile = QWebEngineProfile(self)          # adsız profil: çerez/geçmiş diske yazılmaz
        self.profile.setHttpAcceptLanguage("tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7")
        self.view = QWebEngineView(self)
        self.page = QWebEnginePage(self.profile, self.view)
        self.page.setBackgroundColor(QColor(bg))
        self.view.setPage(self.page)
        v.addWidget(self.view, 1)

    def ShowText(self, text, target):
        self._text = text
        url, cut = core.TranslateUrl(text, target)
        self.note.setText(
            f"Kaynak dil otomatik algılanır. Hedef: {'Türkçe' if target == 'tr' else 'İngilizce'}."
            + (f" Metin {core.TRANSLATE_MAX_CHARS} karaktere kısaltıldı." if cut else "")
        )
        self.view.load(QUrl(url))
        self.show()
        self.raise_()


class TemplatesDialog(QDialog):
    """"Başka sekmeye sor" istem şablonları. Her şablon '# Ad' satırıyla başlar; {metin} seçili metnin yeridir."""

    def __init__(self, parent, templates):
        super().__init__(parent)
        self.setWindowTitle("İstem şablonları")
        self.resize(620, 560)
        v = QVBoxLayout(self)
        v.addWidget(_label(
            "Sağ tık > Başka sekmeye sor menüsündeki istemler. Her şablon “# Ad” satırıyla başlar, altına istem yazılır; "
            "{metin} seçtiğin metnin geleceği yerdir (yazmazsan sona eklenir).", "muted", wrapFlag=True))
        self.edit = QPlainTextEdit()
        self.edit.setPlainText(core.FormatRelayTemplates(templates))
        v.addWidget(self.edit, 1)
        row = QHBoxLayout()
        row.addWidget(_btn("Varsayılanlara dön", lambda: self.edit.setPlainText(
            core.FormatRelayTemplates(core.DEFAULT_RELAY_TEMPLATES))))
        row.addStretch(1)
        v.addLayout(row)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        v.addWidget(box)

    def templates(self): return core.ParseRelayTemplates(self.edit.toPlainText())


class _Tabs(QTabWidget):
    """Sürüklenerek sıralanabilen, sağ tıkla menü açan sekme çubuğu."""

    tabsReordered = Signal()
    tabContextRequested = Signal(int, object)
    contentDropped = Signal(int, object, str)

    def __init__(self):
        super().__init__()
        bar = self.tabBar()
        bar.setMovable(True)
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(self._onContext)
        bar.tabMoved.connect(lambda *_: self.tabsReordered.emit())
        bar.setAcceptDrops(True)            # dosya / metin sekmenin üzerine bırakılabilsin
        bar.installEventFilter(self)

    def _onContext(self, pos):
        i = self.tabBar().tabAt(pos)
        if i >= 0: self.tabContextRequested.emit(i, self.tabBar().mapToGlobal(pos))

    def eventFilter(self, obj, ev):
        bar = self.tabBar()
        if obj is bar:
            t = ev.type()
            if t in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                md = ev.mimeData()
                if md.hasUrls() or md.hasText():
                    i = bar.tabAt(ev.position().toPoint())
                    if i >= 0 and i != self.currentIndex():
                        self.setCurrentIndex(i)           # üzerinde gezinirken sekme açılsın
                    ev.acceptProposedAction()
                    return True
            elif t == QEvent.Type.Drop:
                i = bar.tabAt(ev.position().toPoint())
                md = ev.mimeData()
                paths = [gg.toLocalFile() for gg in md.urls() if gg.isLocalFile()] if md.hasUrls() else []
                text = md.text() if (md.hasText() and not paths) else ""
                ev.acceptProposedAction()
                if i >= 0 and (paths or text.strip()): self.contentDropped.emit(i, paths, text)
                return True
        return super().eventFilter(obj, ev)

    def SiteIds(self): return [getattr(self.widget(gg), "siteId", None) for gg in range(self.count())]


class FilesDialog(QDialog):
    """Sohbete eklenecek dosyaların seçimi: metin olarak yapıştır ya da dosya (gerekirse 30 MB'lık zip) olarak ekle."""

    def __init__(self, parent, items, selectedPaths, zipDefaultFlag=True, mode="text", maskFlag=True):
        super().__init__(parent)
        self.setWindowTitle("Sohbete eklenecek dosyalar")
        self.resize(580, 600)
        self.items = list(items)
        self._mask = maskFlag
        v = QVBoxLayout(self)
        v.addWidget(_label(
            "İşaretlediklerin açık sohbetin mesaj kutusuna eklenir. Göndermek (Enter) sana kalmış.", "muted", wrapFlag=True))
        self.list = QListWidget()
        self.list.setObjectName("framed")
        picked = set(selectedPaths) if selectedPaths else {str(gg.path) for gg in self.items[:5]}
        for i, it in enumerate(self.items):
            tail = "   [yalnızca dosya olarak]" if it.kind == "upload" else ""
            li = QListWidgetItem(f"{it.display}   ·   {core.FormatSize(it.size)}{tail}")
            li.setData(ROLE_ID, i)
            li.setFlags(li.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            li.setCheckState(Qt.CheckState.Checked if str(it.path) in picked else Qt.CheckState.Unchecked)
            self.list.addItem(li)
        self.list.itemChanged.connect(self._updateInfo)
        v.addWidget(self.list, 1)

        row = QHBoxLayout()
        row.addWidget(_btn("Tümü", lambda: self._setAll(True)))
        row.addWidget(_btn("Hiçbiri", lambda: self._setAll(False)))
        row.addWidget(_btn("Son değişen 5", self._newest5))
        row.addStretch(1)
        v.addLayout(row)

        self.rbText = QRadioButton("Metin olarak yapıştır (içerik mesaj kutusuna gelir; parolalar maskelenebilir)")
        self.rbAttach = QRadioButton("Dosya olarak ekle (sohbete yüklenir; PDF/görsel/Office için bu gerekir)")
        (self.rbAttach if mode == "attach" else self.rbText).setChecked(True)
        self.rbText.toggled.connect(self._updateInfo)
        v.addWidget(self.rbText)
        v.addWidget(self.rbAttach)
        self.zipCb = QCheckBox("Birden fazla dosyayı 30 MB'lık zip parçalarına sar")
        self.zipCb.setChecked(bool(zipDefaultFlag))
        v.addWidget(self.zipCb)
        self.info = _label("", "muted", wrapFlag=True)
        v.addWidget(self.info)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        v.addWidget(box)
        self._updateInfo()

    def _setAll(self, on):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def _newest5(self):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Checked if i < 5 else Qt.CheckState.Unchecked)

    def _chosen(self):
        return [
            self.items[self.list.item(gg).data(ROLE_ID)]
            for gg in range(self.list.count())
            if self.list.item(gg).checkState() == Qt.CheckState.Checked
        ]

    def mode(self): return "attach" if self.rbAttach.isChecked() else "text"

    def _updateInfo(self, *_):
        chosen = self._chosen()
        attach = self.mode() == "attach"
        self.zipCb.setEnabled(attach)
        total = sum(gg.size for gg in chosen)
        lines = [f"{len(chosen)} dosya seçili · toplam {core.FormatSize(total)}"]
        if attach:
            if len(chosen) > 1 and self.zipCb.isChecked():
                lines.append("Zip parçaları sıkıştırılarak hazırlanır; her biri en fazla 30 MB olur.")
            lines.append("Dikkat: dosya olarak eklenenlerde parola/anahtar maskelemesi yapılamaz.")
        else:
            texts = [gg for gg in chosen if gg.kind == "text"]
            skipped = len(chosen) - len(texts)
            lines.append(f"Yaklaşık {int(sum(gg.size for gg in texts) / 3.5)} token metin eklenir.")
            if skipped: lines.append(f"{skipped} dosya metin değil (PDF/görsel/Office); bu kipte atlanır.")
        self.info.setText("\n".join(lines))

    def accept(self):
        if not self._chosen():
            self.info.setText("En az bir dosya işaretle.")
            return
        super().accept()

    def values(self): return {"items": self._chosen(), "mode": self.mode(), "zip": self.zipCb.isChecked()}


#################### ana pencere

class MainWindow(QMainWindow):
    def __init__(self, store: core.Store, themeName: str = "dark"):
        super().__init__()
        self.store = store
        self.themeName = themeName
        self.topicId: int | None = None
        self._loadingFlag = False
        self._ownClip = ""          # kendi kopyaladığımız paketi "cevap" sanmamak için
        self._lastPack = None
        self._awaitingSummaryFlag = False   # "Bağlamı çıkar"dan sonra özet cevabı bekleniyor
        self._translateBox = None
        self._quitFlag = False
        self._tray = None
        self._chatRows = []
        self._webThemeAtStart = themeName   # sekmelerin teması açılışta belirlenir
        self.setWindowTitle("ggContext")
        self.resize(1360, 820)
        self.setAcceptDrops(True)

        self._saveTimer = QTimer(self, singleShot=True, interval=600)
        self._saveTimer.timeout.connect(self.SaveFields)
        self._packTimer = QTimer(self, singleShot=True, interval=350)
        self._packTimer.timeout.connect(self.RefreshPack)

        self._buildUi()
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, activated=self.CopyPack)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=self.AddFromClipboard)
        QShortcut(QKeySequence("Ctrl+Shift+B"), self, activated=lambda: self.sideBtn.setChecked(not self.sideBtn.isChecked()))
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, activated=self.AddFilesToCurrentChat)
        QShortcut(QKeySequence("Ctrl+1"), self, activated=lambda: self.SwitchTab(-1))
        QShortcut(QKeySequence("Ctrl+2"), self, activated=lambda: self.SwitchTab(1))
        QShortcut(QKeySequence("Ctrl+Shift+L"), self, activated=self.SelectLastReplyCurrent)
        QShortcut(QKeySequence("Ctrl+Shift+T"), self, activated=self.TranslateCurrentSelection)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=lambda: self.panelBtn.setChecked(not self.panelBtn.isChecked()))
        QApplication.clipboard().dataChanged.connect(self.OnClipboardChanged)

        geo = self.store.GetMeta("geometry")
        if geo: self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
        self.ReloadTopics()
        self.LoadSites()
        self._buildTray()

    #################### iskelet

    def _buildUi(self):
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.setCentralWidget(self.splitter)
        self.sidebar = self._buildSidebar()
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self._buildCenter())
        self.panel = self._buildPanel()
        self.splitter.addWidget(self.panel)
        self.splitter.setCollapsible(0, True)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([250, 760, 470])
        visible = self.store.GetMeta("panel_visible", "1") == "1"
        self.panelBtn.setChecked(visible)
        self.panel.setVisible(visible)
        sideVis = self.store.GetMeta("sidebar_visible", "1") == "1"
        self.sideBtn = _btn("◧", None, flatFlag=True, tip="Soldaki konu panelini göster/gizle (Ctrl+Shift+B)")
        self.sideBtn.setCheckable(True)
        self.sideBtn.setChecked(sideVis)
        self.sideBtn.toggled.connect(self.ToggleSidebar)
        self.sidebar.setVisible(sideVis)
        self.panelBtn2 = _btn("▥", lambda: self.panelBtn.setChecked(not self.panelBtn.isChecked()), flatFlag=True,
                               tip="Sağdaki bağlam panelini göster/gizle (Ctrl+B)")
        self.statusBar().addPermanentWidget(self.sideBtn)
        self.statusBar().addPermanentWidget(self.panelBtn2)
        self.statusBar().showMessage(
            "Hazır. Sekmede bir cevap kopyalayınca otomatik kaydedilir · Ctrl+B: paneli aç/kapat · "
            "Ctrl+Shift+C: bağlam paketini kopyala"
        )

    def _buildSidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setMinimumWidth(150)
        side.setMaximumWidth(340)
        v = QVBoxLayout(side)
        v.setContentsMargins(12, 14, 12, 12)
        v.setSpacing(6)
        v.addWidget(_label("ggContext", "brand"))
        v.addWidget(_label("KONULAR", "section"))
        self.topicList = QListWidget()
        self.topicList.currentItemChanged.connect(self.OnTopicChanged)
        v.addWidget(self.topicList, 1)

        row = QHBoxLayout()
        row.addWidget(_btn("＋  Yeni konu", self.NewTopic, primaryFlag=True), 1)
        more = QToolButton()
        more.setText("⋯")
        more.setToolTip("Konu işlemleri")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction("Adını değiştir…", self.RenameTopic)
        menu.addAction("Konuyu sil…", self.DeleteTopic)
        more.setMenu(menu)
        row.addWidget(more)
        v.addLayout(row)

        v.addWidget(_label("SOHBET SEKMELERİ", "section"))
        v.addWidget(_btn("＋  Hesap / sekme ekle", self.AddSite, tip="Claude, ChatGPT, Gemini veya başka bir site"))
        v.addWidget(_btn("✎  İstem şablonları", self.EditTemplates,
                         tip="Sağ tıktaki \"Başka sekmeye sor\" menüsünün istemleri"))
        v.addWidget(_label("GÖRÜNÜM", "section"))
        self.panelBtn = _btn("▥  Bağlam paneli", None, tip="Ctrl+B")
        self.panelBtn.setCheckable(True)
        self.panelBtn.toggled.connect(self.TogglePanel)
        v.addWidget(self.panelBtn)
        self.themeBtn = _btn("", self.ToggleTheme)
        v.addWidget(self.themeBtn)
        self._updateThemeButton()
        return side

    def _buildCenter(self):
        self.stack = QStackedWidget()
        empty = QWidget()
        ev = QVBoxLayout(empty)
        ev.addStretch(1)
        title = _label("Henüz bir sohbet sekmesi yok", "brand")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc = _label(
            "Claude, ChatGPT veya Gemini sekmesi ekle. Her sekme kendi giriş oturumunu ayrı tutar.",
            "muted", wrapFlag=True,
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(title)
        ev.addWidget(desc)
        brow = QHBoxLayout()
        brow.addStretch(1)
        brow.addWidget(_btn("＋  Hesap / sekme ekle", self.AddSite, primaryFlag=True))
        brow.addStretch(1)
        ev.addLayout(brow)
        ev.addStretch(2)

        self.webTabs = _Tabs()
        self.webTabs.setObjectName("webTabs")
        self.webTabs.setDocumentMode(True)
        self.webTabs.tabsReordered.connect(self._onTabsReordered)
        self.webTabs.tabContextRequested.connect(self.OnTabContext)
        self.webTabs.tabBarDoubleClicked.connect(self._renameAt)
        self.webTabs.contentDropped.connect(self._onTabDrop)
        self.webTabs.currentChanged.connect(self.OnWebTabChanged)
        self.stack.addWidget(empty)
        self.stack.addWidget(self.webTabs)
        return self.stack

    def _buildPanel(self):
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMinimumWidth(360)
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        self.ctxTabs = QTabWidget()
        self.ctxTabs.setDocumentMode(True)
        self.ctxTabs.addTab(self._tabSummary(), "Özet")
        self.ctxTabs.addTab(self._tabEntries(), "Cevaplar")
        self.ctxTabs.addTab(self._tabFiles(), "Dosyalar")
        self.ctxTabs.addTab(self._tabChats(), "Sohbetler")
        self.ctxTabs.addTab(self._tabPack(), "Paket")
        self.ctxTabs.currentChanged.connect(lambda gg: self.SchedulePackRefresh())
        v.addWidget(self.ctxTabs)
        return panel

    def _page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(8)
        return w, v

    def _tabSummary(self):
        w, v = self._page()
        v.addWidget(_label("Bağlamı çıkaracak sekme (sekmedeki “Bağlamı çıkar” düğmesi sohbet metnini buraya gönderir)", "muted", wrapFlag=True))
        self.extractorCombo = QComboBox()
        self.extractorCombo.currentIndexChanged.connect(self.OnExtractorChanged)
        v.addWidget(self.extractorCombo)
        self.confirmCb = QCheckBox("Sohbet metnini başka sekmeye aktarmadan önce sor")
        self.confirmCb.setChecked(self.store.GetMeta("confirm_delegate", "1") == "1")
        self.confirmCb.toggled.connect(lambda gg: self.store.SetMeta("confirm_delegate", "1" if gg else "0"))
        v.addWidget(self.confirmCb)
        v.addWidget(_label("Hedef (tek cümle)", "muted"))
        self.goalEdit = QLineEdit()
        self.goalEdit.textChanged.connect(self.OnFieldsChanged)
        v.addWidget(self.goalEdit)
        v.addWidget(_label("Özet: başka bir yapay zekanın konuya hâkim olması için gereken en kısa bilgi", "muted", wrapFlag=True))
        self.summaryEdit = QPlainTextEdit()
        self.summaryEdit.textChanged.connect(self.OnFieldsChanged)
        v.addWidget(self.summaryEdit, 2)

        v.addWidget(_btn(
            "Özet isteğini kopyala", self.CopySummaryRequest,
            tip="Herhangi bir yapay zekaya yapıştır; cevabını aşağıdaki düğmeyle içe aktar.",
        ))
        v.addWidget(_btn("Yapay zekanın özetini panodan içe aktar", self.ImportSummary))

        v.addWidget(_label("Kararlar ve açık işler", "muted"))
        self.itemsList = QListWidget()
        self.itemsList.setObjectName("framed")
        self.itemsList.itemChanged.connect(self.OnItemChanged)
        v.addWidget(self.itemsList, 3)
        add = QHBoxLayout()
        self.itemKind = QComboBox()
        self.itemKind.addItems(["Karar", "Açık iş"])
        self.itemText = QLineEdit()
        self.itemText.setPlaceholderText("Yeni madde, Enter ile ekle…")
        self.itemText.returnPressed.connect(self.AddItem)
        add.addWidget(self.itemKind)
        add.addWidget(self.itemText, 1)
        add.addWidget(_btn("Ekle", self.AddItem))
        v.addLayout(add)
        v.addWidget(_btn("Seçili maddeyi sil", self.DeleteItem, flatFlag=True))
        return w

    def _tabEntries(self):
        w, v = self._page()
        row = QHBoxLayout()
        row.addWidget(_label("Manuel eklerken model:", "muted"))
        self.srcModel = QComboBox()
        self.srcModel.setEditable(True)
        self.srcModel.addItems(list(core.DEFAULT_MODELS.keys()))
        row.addWidget(self.srcModel, 1)
        v.addLayout(row)

        self.watchCb = QCheckBox("Sekmelerde kopyalanan cevapları otomatik kaydet")
        self.watchCb.setChecked(True)
        self.watchCb.setToolTip(
            "Bir sohbet sekmesinde (ör. sitedeki Kopyala düğmesiyle) uzun bir metin kopyalayınca, "
            "o sekmenin modelinden gelen cevap olarak konuya kaydedilir."
        )
        v.addWidget(self.watchCb)
        self.watchExtCb = QCheckBox("Başka uygulamalardan kopyalananı da kaydet")
        self.watchExtCb.setToolTip("Kapalı kalması önerilir: uygulama dışında kopyaladığın her uzun metin kaydedilir.")
        v.addWidget(self.watchExtCb)
        mrow = QHBoxLayout()
        mrow.addWidget(_label("En az:", "muted"))
        self.minChars = QSpinBox()
        self.minChars.setRange(10, 5000)
        self.minChars.setValue(80)
        self.minChars.setSuffix(" karakter")
        mrow.addWidget(self.minChars)
        mrow.addStretch(1)
        v.addLayout(mrow)

        row = QHBoxLayout()
        row.addWidget(_btn("Panodan ekle", self.AddFromClipboard))
        row.addWidget(_btn("Not ekle…", self.AddNote))
        row.addWidget(_btn("📌", self.TogglePin, tip="Sabitle / kaldır"))
        row.addWidget(_btn("Sil", self.DeleteEntry))
        v.addLayout(row)

        split = QSplitter(Qt.Orientation.Vertical)
        self.entryList = QListWidget()
        self.entryList.setObjectName("framed")
        self.entryList.currentItemChanged.connect(self.OnEntrySelected)
        self.entryView = QPlainTextEdit()
        self.entryView.setReadOnly(True)
        split.addWidget(self.entryList)
        split.addWidget(self.entryView)
        split.setSizes([260, 260])
        v.addWidget(split, 1)
        v.addWidget(_label("Sabitlenen cevaplar, son-N dışında kalsa bile pakete girer (en fazla 3).", "muted", wrapFlag=True))
        return w

    def _tabFiles(self):
        w, v = self._page()
        v.addWidget(_label("Bu konunun dosya ve klasörleri. Pencereye sürükleyip bırakabilirsin.", "muted", wrapFlag=True))
        self.srcList = QListWidget()
        self.srcList.setObjectName("framed")
        self.srcList.itemChanged.connect(self.OnSourceChanged)
        v.addWidget(self.srcList, 1)
        row = QHBoxLayout()
        row.addWidget(_btn("Dosya ekle…", self.AddFiles))
        row.addWidget(_btn("Klasör ekle…", self.AddFolder))
        row.addWidget(_btn("Kaldır", self.RemoveSource))
        v.addLayout(row)
        v.addWidget(_btn(
            "Seçtiğim dosyaları açık sohbete ekle…", self.AddFilesToCurrentChat, primaryFlag=True,
            tip="İstediğin an (Ctrl+Shift+F): seçtiklerini şu an açık olan sohbete metin ya da dosya/zip olarak ekler.",
        ))
        self.zipCb = QCheckBox("Birden fazla dosya olunca 30 MB'lık zip parçalarına sar")
        self.zipCb.setChecked(True)
        v.addWidget(self.zipCb)
        v.addWidget(_btn("Yüklenecekler klasörünü hazırla ve aç", self.OpenUploads))
        self.filesInfo = QPlainTextEdit()
        self.filesInfo.setReadOnly(True)
        v.addWidget(self.filesInfo, 1)
        v.addWidget(_label(
            "Metin/kod dosyaları pakete gömülür (en son değişenler öncelikli). PDF, Word, Excel, görsel gibi "
            "dosyalar 'Yüklenecekler' klasörüne kopyalanır; sohbete sürükleyip bırakırsın. "
            ".env, .pem, .key gibi hassas dosyalar her zaman atlanır.",
            "muted", wrapFlag=True,
        ))
        return w

    def _tabChats(self):
        w, v = self._page()
        v.addWidget(_label(
            "Bu konuda en son açtığın 10 sohbet (Claude, ChatGPT, Gemini…). Tıklayınca o sekmeye geçer ve sohbeti açar. "
            "Liste, sekmelerde gezdikçe bu bilgisayarda kendiliğinden tutulur; hiçbir yapay zekaya gönderilmez.",
            "muted", wrapFlag=True))
        self.chatList = QListWidget()
        self.chatList.setObjectName("framed")
        self.chatList.itemClicked.connect(self.OpenChat)
        v.addWidget(self.chatList, 1)
        row = QHBoxLayout()
        row.addWidget(_btn("Seçili sohbeti aç", lambda: self.OpenChat(self.chatList.currentItem())))
        row.addWidget(_btn("Listeden kaldır", self.RemoveChatEntry, flatFlag=True))
        v.addLayout(row)
        return w

    def _tabPack(self):
        w, v = self._page()
        form = QFormLayout()
        form.setSpacing(8)
        self.targetModel = QComboBox()
        self.targetModel.setEditable(True)
        self.targetModel.addItems(list(core.DEFAULT_MODELS.keys()))
        self.targetModel.currentTextChanged.connect(self.OnTargetChanged)
        form.addRow("Hedef model:", self.targetModel)
        self.budgetSpin = QSpinBox()
        self.budgetSpin.setRange(300, 500000)
        self.budgetSpin.setSingleStep(500)
        self.budgetSpin.setValue(core.DEFAULT_MODELS["Claude"])
        self.budgetSpin.setSuffix(" token")
        self.budgetSpin.valueChanged.connect(self.SchedulePackRefresh)
        form.addRow("Token bütçesi:", self.budgetSpin)
        self.lastnSpin = QSpinBox()
        self.lastnSpin.setRange(0, 30)
        self.lastnSpin.setValue(4)
        self.lastnSpin.valueChanged.connect(self.SchedulePackRefresh)
        form.addRow("Son kaç konuşma:", self.lastnSpin)
        v.addLayout(form)

        self.deltaCb = QCheckBox("Fark modu (aynı sohbete devam ediyorum)")
        self.deltaCb.setToolTip(
            "Bu modele en son gönderdiğinden beri değişenleri gönderir. Yalnızca o modelle AYNI sohbete "
            "yapıştırırsan kullan; yeni sohbette kapalı tut."
        )
        self.filesCb = QCheckBox("Dosyaları dahil et")
        self.filesCb.setChecked(True)
        self.maskCb = QCheckBox("Anahtar/parolaları maskele")
        self.maskCb.setChecked(True)
        for cb in (self.deltaCb, self.filesCb, self.maskCb):
            cb.toggled.connect(self.SchedulePackRefresh)
            v.addWidget(cb)

        v.addWidget(_label("İstek (isteğe bağlı): paketin sonuna eklenir; tek yapıştırmada hem bağlam hem soru gider", "muted", wrapFlag=True))
        self.requestEdit = QPlainTextEdit()
        self.requestEdit.setMaximumHeight(72)
        self.requestEdit.textChanged.connect(self.SchedulePackRefresh)
        v.addWidget(self.requestEdit)

        self.statsLabel = _label("", "muted", wrapFlag=True)
        v.addWidget(self.statsLabel)
        self.packView = QPlainTextEdit()
        self.packView.setReadOnly(True)
        v.addWidget(self.packView, 1)

        row = QHBoxLayout()
        row.addWidget(_btn("Yenile", self.RefreshPack))
        self.btnCopy = _btn("Panoya kopyala", self.CopyPack, primaryFlag=True, tip="Ctrl+Shift+C")
        row.addWidget(self.btnCopy, 1)
        v.addLayout(row)
        return w

    #################### tema / panel

    def _updateThemeButton(self):
        self.themeBtn.setText("☀  Açık temaya geç" if self.themeName == "dark" else "☾  Koyu temaya geç")

    def ToggleTheme(self):
        self.themeName = "light" if self.themeName == "dark" else "dark"
        theme.ApplyTheme(QApplication.instance(), self.themeName)
        self.store.SetMeta("theme", self.themeName)
        theme.ApplyTitlebar(self, self.themeName)
        self._updateThemeButton()
        bg = theme.THEMES[self.themeName]["bg"]
        for i in range(self.webTabs.count()):
            w = self.webTabs.widget(i)
            if isinstance(w, BrowserTab): w.SetPageBackground(bg)
        if self.themeName != self._webThemeAtStart:
            self.statusBar().showMessage(
                "Tema değişti. Sekmelerin içindeki sitelerin teması için uygulamayı kapatıp yeniden aç.", 15000
            )

    #################### görev çubuğu / bildirim alanı simgesi

    def _buildTray(self):
        """bildirim alanında (saatin yanı) simge: tıklayınca pencereyi gösterir/gizler, menüsünden çıkılır"""
        if not QSystemTrayIcon.isSystemTrayAvailable(): return
        self._tray = QSystemTrayIcon(self.windowIcon(), self)
        self._tray.setToolTip("ggContext")
        menu = QMenu(self)
        menu.addAction("Göster / gizle", lambda: self.ToggleVisible())
        self.trayCloseAct = menu.addAction("Kapatınca tepsiye küçül (arka planda açık kalsın)")
        self.trayCloseAct.setCheckable(True)
        self.trayCloseAct.setChecked(self.store.GetMeta("close_to_tray", "0") == "1")
        self.trayCloseAct.toggled.connect(lambda on: self.store.SetMeta("close_to_tray", "1" if on else "0"))
        menu.addAction("Windows aramasına ekle / yenile", lambda: self.AddToStartMenu())
        menu.addSeparator()
        menu.addAction("Çık", lambda: self.QuitApp())
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._onTray)
        self._tray.show()

    def _onTray(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger: self.ToggleVisible()

    def AddToStartMenu(self):
        import baglam_shortcut
        if not baglam_shortcut.CanCreate():
            self.statusBar().showMessage("Başlat menüsü kısayolu yalnızca derlenmiş uygulamada (ggContext.exe) oluşturulur.", 8000)
            return
        baglam_shortcut.EnsureStartMenuShortcut(self.store, force=True)
        self.statusBar().showMessage("Kısayol oluşturuluyor; birkaç saniye sonra Başlat'a ggContext yazarak bulabilirsin.", 8000)

    def ToggleVisible(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
            return
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def QuitApp(self):
        self._quitFlag = True
        self.close()

    def showEvent(self, event):
        super().showEvent(event)
        theme.ApplyTitlebar(self, self.themeName)   # pencere tanıtıcısı gösterilince hazır olur

    def ToggleSidebar(self, checked: bool):
        self.sidebar.setVisible(checked)
        self.store.SetMeta("sidebar_visible", "1" if checked else "0")

    def TogglePanel(self, checked: bool):
        self.panel.setVisible(checked)
        self.store.SetMeta("panel_visible", "1" if checked else "0")

    #################### web sekmeleri

    def LoadSites(self):
        for site in self.store.ListSites(): self._appendTab(site)
        self._syncStack()
        self._refreshExtractors()

    def _appendTab(self, site, selectFlag=False):
        tab = BrowserTab(
            site,
            bg=theme.THEMES[self.themeName]["bg"],
            forceDarkFlag=self.store.GetMeta(f"forcedark_{site['id']}") == "1",
            lastUrl=self.store.GetMeta(f"lasturl_{site['id']}", ""),
        )
        tab.urlSaved.connect(self._onUrlSaved)
        tab.pasteRequested.connect(self.PasteContext)
        tab.summarizeRequested.connect(self.RequestSummary)
        tab.delegateSummaryRequested.connect(self.DelegateSummary)
        tab.filesRequested.connect(self.AddFilesToChat)
        tab.contextMenuRequested.connect(self.BuildRelayMenu)
        tab.tabTitleChanged.connect(self._onTabTitle)
        tab.renameRequested.connect(self.RenameSite)
        tab.forceDarkChanged.connect(self.OnForceDarkChanged)
        tab.saveRequested.connect(self.SaveSelection)
        tab.editRequested.connect(self.EditSite)
        tab.removeRequested.connect(self.RemoveSite)
        tab.wipeRequested.connect(self.WipeSite)
        tab.message.connect(lambda gg: self.statusBar().showMessage(gg, 8000))
        idx = self.webTabs.addTab(tab, tab.name)
        if selectFlag: self.webTabs.setCurrentIndex(idx)
        return tab

    def _syncStack(self):
        self.stack.setCurrentIndex(1 if self.webTabs.count() else 0)
        self.OnWebTabChanged(self.webTabs.currentIndex())

    def OnWebTabChanged(self, index):
        if index < 0: return
        tab = self.webTabs.widget(index)
        if isinstance(tab, BrowserTab): tab.EnsureLoaded()

    def _tabNames(self, exclude=None):
        return [
            self.webTabs.widget(gg).name
            for gg in range(self.webTabs.count())
            if self.webTabs.widget(gg) is not exclude
        ]

    def AddSite(self):
        dlg = SiteDialog(self, takenNames=self._tabNames())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            v = dlg.values()
            sid = self.store.AddSite(v["name"], v["url"], v["model"])
            self._appendTab(self.store.GetSite(sid), selectFlag=True)
            self._syncStack()
            self._saveTabOrder()
            self._refreshExtractors()

    def EditSite(self, tab):
        dlg = SiteDialog(self, site=self.store.GetSite(tab.siteId), takenNames=self._tabNames(exclude=tab))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            v = dlg.values()
            self.store.UpdateSite(tab.siteId, v["name"], v["url"], v["model"])
            tab.ApplySite(self.store.GetSite(tab.siteId))
            self.webTabs.setTabText(self.webTabs.indexOf(tab), tab.name)
            self._refreshExtractors()

    def RenameSite(self, tab):
        """Sekmenin adını hızlıca değiştirir (sağ tık ya da çift tık)."""
        name, ok = QInputDialog.getText(self, "Sekmeyi yeniden adlandır", "Yeni ad:", text=tab.name)
        name = (name or "").strip()
        if not ok or not name or name == tab.name: return
        if name.casefold() in {gg.casefold() for gg in self._tabNames(exclude=tab)}:
            self.statusBar().showMessage("Bu ada sahip başka bir sekme var; farklı bir ad seç.", 6000)
            return
        self.store.UpdateSite(tab.siteId, name, tab.url, tab.model)
        tab.ApplySite(self.store.GetSite(tab.siteId))
        self.webTabs.setTabText(self.webTabs.indexOf(tab), tab.name)
        self._refreshExtractors()

    def _renameAt(self, index):
        tab = self.webTabs.widget(index)
        if isinstance(tab, BrowserTab): self.RenameSite(tab)

    def OnTabContext(self, index, pos):
        tab = self.webTabs.widget(index)
        if not isinstance(tab, BrowserTab): return
        menu = QMenu(self)
        menu.addAction("Adı değiştir…", lambda: self.RenameSite(tab))
        menu.addAction("Ad / adres düzenle…", lambda: self.EditSite(tab))
        menu.addSeparator()
        menu.addAction("Sekmeyi kaldır…", lambda: self.RemoveSite(tab))
        menu.exec(pos)

    def _saveTabOrder(self): self.store.SaveSiteOrder([gg for gg in self.webTabs.SiteIds() if isinstance(gg, int)])

    def _onTabsReordered(self, *_):
        self._saveTabOrder()
        self._refreshExtractors()

    def _refreshExtractors(self):
        """Sağ paneldeki 'Bağlamı çıkaracak sekme' listesini sekmelerle eşler (kayıtlı seçim korunur)."""
        saved = self.store.GetMeta("extractor_site")
        tabs = [self.webTabs.widget(gg) for gg in range(self.webTabs.count())]
        tabs = [gg for gg in tabs if isinstance(gg, BrowserTab)]
        self.extractorCombo.blockSignals(True)
        self.extractorCombo.clear()
        pick = 0
        for i, t in enumerate(tabs):
            self.extractorCombo.addItem(f"{t.name} ({t.model})", t.siteId)
            if saved is not None and str(t.siteId) == saved: pick = i
            elif saved is None and t.model.casefold() == "gemini" and pick == 0: pick = i
        if tabs: self.extractorCombo.setCurrentIndex(pick)
        self.extractorCombo.blockSignals(False)

    def OnExtractorChanged(self, _index):
        sid = self.extractorCombo.currentData()
        if sid is not None: self.store.SetMeta("extractor_site", sid)

    def _extractorTab(self):
        sid = self.extractorCombo.currentData()
        for i in range(self.webTabs.count()):
            t = self.webTabs.widget(i)
            if isinstance(t, BrowserTab) and t.siteId == sid: return t
        return None

    def RemoveSite(self, tab):
        ans = QMessageBox.question(
            self, "Sekmeyi kaldır",
            f"“{tab.name}” sekmesi kaldırılsın mı?\nBu sekmenin giriş oturumu da silinir "
            "(uygulama bir sonraki açılışta temizler). Konular ve kayıtlı cevaplar etkilenmez.",
        )
        if ans != QMessageBox.StandardButton.Yes: return
        self.store.DeleteSite(tab.siteId)
        self.webTabs.removeTab(self.webTabs.indexOf(tab))
        tab.Shutdown()
        self._syncStack()
        self._saveTabOrder()
        self._refreshExtractors()

    def WipeSite(self, tab):
        ans = QMessageBox.question(
            self, "Oturumu temizle",
            f"“{tab.name}” sekmesinin çerezleri ve önbelleği silinsin mi?\n"
            "Sitede yeniden giriş yapman gerekir. Tam temizlik uygulamayı yeniden açınca tamamlanır.",
        )
        if ans == QMessageBox.StandardButton.Yes:
            tab.ClearSessionNow()
            self.store.MarkProfileWipe(tab.siteId)
            self.statusBar().showMessage(f"{tab.name}: oturum temizlendi.", 8000)

    def _webFocusTab(self):
        fw = QApplication.focusWidget()
        if fw is None: return None
        for i in range(self.webTabs.count()):
            t = self.webTabs.widget(i)
            if t.view is not None and (fw is t.view or t.view.isAncestorOf(fw)): return t
        return None

    def PasteContext(self, tab):
        """Konunun bağlam paketini hazırlar ve sekmedeki mesaj kutusuna yapıştırır (göndermez)."""
        if self.topicId is None:
            self.statusBar().showMessage("Önce soldan bir konu seç.", 6000)
            return
        self.webTabs.setCurrentWidget(tab)
        self.targetModel.setCurrentText(tab.model)
        self.CopyPack()
        if not self._lastPack: return
        tab.PasteIntoPage()
        res, _opts = self._lastPack
        t = self.store.GetTopic(self.topicId)
        hint = "" if ((t["goal"] or "").strip() or (t["summary"] or "").strip()) else (
            " İpucu: konunun özeti boş; önce kaynak sohbetin sekmesinde 'Bağlamı çıkar'ı kullan."
        )
        self.statusBar().showMessage(
            f"Bağlam {tab.name} sekmesine yapıştırıldı (~{res.tokens} token). "
            "Mesaj kutusu boşsa önce ona tıklayıp tekrar dene; göndermek sana kalmış." + hint, 12000,
        )

    def SaveSelection(self, tab):
        if self.topicId is None:
            self.statusBar().showMessage("Önce soldan bir konu seç.", 6000)
            return
        text = core.CleanSelection(tab.SelectedText())
        if not text:
            self.statusBar().showMessage("Önce sayfada kaydetmek istediğin metni seç.", 6000)
            return
        self._addEntry(text, tab.model)

    def RequestSummary(self, tab):
        """Bu sekmedeki sohbetin genel bağlam özetini ister. İstemi mesaj kutusuna yapıştırır, göndermez

        Sohbetteki yapay zeka konuşmanın tamamını zaten bildiği için özeti kendisi çıkarır; cevap kopyalanınca
        uygulama özeti tanır ve içe aktarmayı önerir
        """
        if self.topicId is None:
            self.statusBar().showMessage("Önce soldan bir konu seç.", 6000)
            return
        self.FlushSave()
        text = core.BuildInlineSummaryPrompt(self.store, self.topicId)
        self._setClipboard(text)
        self._awaitingSummaryFlag = True
        self.webTabs.setCurrentWidget(tab)
        tab.PasteIntoPage()
        self.statusBar().showMessage(
            f"Özet isteği {tab.name} sekmesine yapıştırıldı. Enter'a bas; cevap gelince sitedeki Kopyala "
            "düğmesine bas, özet otomatik tanınıp içe aktarılmayı önerecek.", 15000,
        )

    def _offerSummaryImport(self, text: str, model: str):
        parsed = core.ParseSummaryResponse(text)
        msg = (
            f"{model} cevabında bir bağlam özeti algılandı.\n\n"
            f"Hedef: {'var' if parsed['goal'] else 'yok'} · Özet: {'var' if parsed['summary'] else 'yok'} · "
            f"Karar: {len(parsed['decisions'])} · Açık iş: {len(parsed['open'])}\n\n"
            "Evet: konuya içe aktar (hedef/özet güncellenir, maddeler eklenir; var olanlar silinmez)\n"
            "Hayır: normal bir cevap olarak kaydet\n"
            "İptal: hiçbir şey yapma"
        )
        ans = QMessageBox.question(
            self, "Özet algılandı", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
        )
        self._awaitingSummaryFlag = False
        if ans == QMessageBox.StandardButton.Yes:
            self.FlushSave()
            core.ApplySummary(self.store, self.topicId, parsed)
            self.LoadTopic()
            self.statusBar().showMessage(
                "Özet konuya aktarıldı. Artık başka bir sekmede 'Bağlamı yapıştır'ı kullanabilirsin.", 10000
            )
        elif ans == QMessageBox.StandardButton.No: self._addEntry(text, model)

    def DelegateSummary(self, src):
        """“Bağlamı çıkar”: kaynak sekmedeki açık sohbetin metnini okur ve sağ paneldeki Özet sekmesinde
        seçili sekmenin mesaj kutusuna istemle birlikte yapıştırır; seni o sekmeye götürür. Göndermeyi sen yaparsın.
        Seçili sekme kaynağın kendisiyse özet bu sohbet içinde istenir."""
        if self.topicId is None:
            self.statusBar().showMessage("Önce soldan bir konu seç.", 6000)
            return
        dst = self._extractorTab()
        if dst is None:
            self.statusBar().showMessage("Bağlamı çıkaracak sekmeyi sağ paneldeki Özet sekmesinden seç.", 8000)
            return
        if dst is src:
            self.RequestSummary(src)
            return
        self.FlushSave()
        src.ReadPageText(lambda gg: self._afterReadPage(src, dst, gg))

    def _afterReadPage(self, src, dst, raw):
        text = core.CleanPageText(raw)
        if len(text) < 200:
            self.statusBar().showMessage(
                f"{src.name} sayfasında yeterli sohbet metni bulunamadı. Sohbetin o sekmede açık olduğundan emin ol.",
                10000,
            )
            return
        prompt = core.BuildTranscriptSummaryPrompt(self.store, self.topicId, text)
        size = f"{len(text):,}".replace(",", ".")
        msg = (
            f"“{src.name}” sayfasındaki yaklaşık {size} karakterlik metin (~{core.EstimateTokens(prompt)} token), "
            f"“{dst.name}” sekmesinin mesaj kutusuna yapıştırılacak. Gönderirsen metin o hizmetin eline geçer.\n\n"
            "Dikkat: sayfada görünen her şey alınır; kenar çubuğundaki diğer sohbetlerin başlıkları da dahil "
            "olabilir. Göndermeden önce mesaj kutusunda gözden geçirebilirsin.\n\nDevam edilsin mi?"
        )
        if self.confirmCb.isChecked() and (
            QMessageBox.question(self, "Sohbet metni aktarılsın mı?", msg) != QMessageBox.StandardButton.Yes
        ):
            return
        self._setClipboard(prompt)
        self._awaitingSummaryFlag = True
        self.webTabs.setCurrentWidget(dst)
        dst.PasteIntoPage(delay=700)   # sekme yeni açılıyorsa görünüp yüklenmesi için kısa bekleme
        self.statusBar().showMessage(
            f"İstem {dst.name} sekmesine yapıştırılıyor. Yapışmadıysa mesaj kutusuna tıklayıp Ctrl+V yap "
            "(istem panoda hazır). Enter'a bas; cevap gelince Kopyala'ya bas, özet otomatik tanınacak.", 20000,
        )

    def BuildRelayMenu(self, tab, menu, sel):
        """Sayfadaki sağ tık menüsüne köprü işlemlerini ekler."""
        others = [
            self.webTabs.widget(gg) for gg in range(self.webTabs.count())
            if isinstance(self.webTabs.widget(gg), BrowserTab) and self.webTabs.widget(gg) is not tab
        ]
        if sel:
            sub = menu.addMenu("Başka sekmeye sor")
            if not others: sub.addAction("Başka sekme yok").setEnabled(False)
            templates = core.GetRelayTemplates(self.store)
            for dst in others:
                tm = sub.addMenu(f"{dst.name}")
                for name, body in templates: tm.addAction(name, lambda *_, d=dst, b=body: self.Relay(tab, d, b, sel))
            sub.addSeparator()
            sub.addAction("İstem şablonlarını düzenle…", lambda *_: self.EditTemplates())
            auto = core.GuessTargetLang(sel)
            tr = menu.addMenu("Çevir (Google Çeviri)")
            tr.addAction(f"Otomatik → {'İngilizce' if auto == 'en' else 'Türkçe'}",
                         lambda *_, a=auto: self.TranslateText(sel, a))
            tr.addAction("→ Türkçe", lambda *_: self.TranslateText(sel, "tr"))
            tr.addAction("→ İngilizce", lambda *_: self.TranslateText(sel, "en"))
            menu.addAction("Seçili metni cevap olarak kaydet", lambda *_: self.SaveSelection(tab))
        bridge = menu.addMenu("ggContext")
        bridge.addAction("Bağlamı yapıştır", lambda *_: self.PasteContext(tab))
        bridge.addAction("Dosyaları ekle…", lambda *_: self.AddFilesToChat(tab))
        bridge.addAction("Bağlamı çıkar", lambda *_: self.DelegateSummary(tab))
        bridge.addAction("Son cevabı seç", lambda *_: tab.SelectLastReply())

    def Relay(self, src, dst, body, text):
        """Seçili metni şablonla birlikte başka sekmenin mesaj kutusuna yapıştırır (göndermez)."""
        if self.maskCb.isChecked(): text = core.MaskSecrets(text)
        prompt = core.ApplyRelayTemplate(body, text)
        self._setClipboard(prompt)
        self.webTabs.setCurrentWidget(dst)
        dst.PasteIntoPage(delay=500)
        self.statusBar().showMessage(
            f"{src.name if src is not None else 'Bırakılan'} metin {dst.name} sekmesine yapıştırılıyor (~{core.EstimateTokens(prompt)} token). "
            "Yapışmadıysa mesaj kutusuna tıklayıp Ctrl+V yap; Enter'a sen bas. Cevabı seçip sağ tıkla "
            "yine \"Başka sekmeye sor\"la geri gönderebilirsin.", 15000,
        )

    def EditTemplates(self):
        dlg = TemplatesDialog(self, core.GetRelayTemplates(self.store))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            core.SaveRelayTemplates(self.store, dlg.templates())
            self.statusBar().showMessage("İstem şablonları kaydedildi.", 6000)

    #################### hızlı geçiş, son cevap, çeviri

    def SwitchTab(self, step):
        n = self.webTabs.count()
        if n: self.webTabs.setCurrentIndex((self.webTabs.currentIndex() + step) % n)

    def SelectLastReplyCurrent(self):
        tab = self.webTabs.currentWidget()
        if isinstance(tab, BrowserTab): tab.SelectLastReply()

    def TranslateCurrentSelection(self):
        tab = self.webTabs.currentWidget()
        text = core.CleanSelection(tab.SelectedText()) if isinstance(tab, BrowserTab) else ""
        if not text:
            self.statusBar().showMessage("Önce çevirmek istediğin metni seç.", 6000)
            return
        self.TranslateText(text, core.GuessTargetLang(text))

    def TranslateText(self, text, target):
        """Seçili metni Google Çeviri kutusunda açar. Metin Google'a gönderilir; parolalar önce maskelenir."""
        if not WEBENGINE_OK:
            self.statusBar().showMessage("Çeviri kutusu için QtWebEngine gerekir.", 6000)
            return
        if self.maskCb.isChecked(): text = core.MaskSecrets(text)
        if self._translateBox is None: self._translateBox = TranslateBox(self, bg=theme.THEMES[self.themeName]["bg"])
        self._translateBox.ShowText(text, target)

    #################### son konuşmalar

    def _onUrlSaved(self, tab, url):
        self.store.SetMeta(f"lasturl_{tab.siteId}", url)
        if self.topicId is not None and core.RecordChat(
            self.store, self.topicId, tab.siteId, url, tab.view.title() if tab.view is not None else ""
        ):
            self.RefreshChats()

    def _onTabTitle(self, tab, title):
        if self.topicId is not None and tab.lastUrl and core.IsChatUrl(tab.lastUrl):
            core.RecordChat(self.store, self.topicId, tab.siteId, tab.lastUrl, title)
            self.RefreshChats()

    def _tabBySite(self, siteId):
        for i in range(self.webTabs.count()):
            t = self.webTabs.widget(i)
            if isinstance(t, BrowserTab) and t.siteId == siteId: return t
        return None

    def RefreshChats(self):
        self.chatList.clear()
        self._chatRows = core.ListChats(self.store, self.topicId, 10) if self.topicId is not None else []
        for i, c in enumerate(self._chatRows):
            t = self._tabBySite(c["site"])
            where = t.name if t is not None else "(sekme kaldırılmış)"
            when = time.strftime("%d.%m %H:%M", time.localtime(c.get("ts", 0)))
            it = QListWidgetItem(f"{where} · {c.get('title') or c['url']}   ({when})")
            it.setData(ROLE_ID, i)
            self.chatList.addItem(it)

    def OpenChat(self, item):
        if item is None: return
        c = self._chatRows[item.data(ROLE_ID)]
        tab = self._tabBySite(c["site"])
        if tab is None or tab.view is None:
            self.statusBar().showMessage("Bu sohbetin sekmesi artık yok.", 6000)
            return
        self.webTabs.setCurrentWidget(tab)
        tab.loadedFlag = True
        tab.view.load(QUrl(c["url"]))

    def RemoveChatEntry(self):
        it = self.chatList.currentItem()
        if it is not None and self.topicId is not None:
            c = self._chatRows[it.data(ROLE_ID)]
            core.RemoveChat(self.store, self.topicId, c["site"], c["url"])
            self.RefreshChats()

    #################### sekmenin üzerine bırakma

    def _onTabDrop(self, index, paths, text):
        tab = self.webTabs.widget(index)
        if not isinstance(tab, BrowserTab): return
        QTimer.singleShot(0, lambda: self._handleDrop(tab, paths, text))   # sürükleme bitince iletişim kutusu aç

    def _handleDrop(self, tab, paths, text):
        self.webTabs.setCurrentWidget(tab)
        if paths:
            items, sensitive = core.ItemsFromPaths(paths)
            if not items:
                self.statusBar().showMessage(
                    "Bırakılanlarda kullanılabilir dosya yok" + (f" ({sensitive} hassas dosya atlandı)." if sensitive else "."), 8000)
                return
            dlg = FilesDialog(
                self, items, [str(gg.path) for gg in items], zipDefaultFlag=self.zipCb.isChecked(),
                mode=self.store.GetMeta("files_mode", "text"), maskFlag=self.maskCb.isChecked(),
            )
            if dlg.exec() != QDialog.DialogCode.Accepted: return
            v = dlg.values()
            self.store.SetMeta("files_mode", v["mode"])
            self.zipCb.setChecked(v["zip"])
            self._sendFiles(tab, v["items"], v["mode"], v["zip"])
            return
        text = core.CleanSelection(text)
        if not text: return
        menu = QMenu(self)
        for name, body in core.GetRelayTemplates(self.store):
            menu.addAction(f"{tab.name}'a gönder: {name}", lambda *_, b=body: self.Relay(None, tab, b, text))
        menu.exec(QCursor.pos())

    def OnForceDarkChanged(self, tab, on): self.store.SetMeta(f"forcedark_{tab.siteId}", "1" if on else "0")

    #################### konular

    def ReloadTopics(self, selectId: int | None = None):
        topics = self.store.ListTopics()
        if not topics:
            self.store.CreateTopic("Genel")
            topics = self.store.ListTopics()
        self.topicList.blockSignals(True)
        self.topicList.clear()
        for t in topics:
            it = QListWidgetItem(t["name"])
            it.setData(ROLE_ID, t["id"])
            self.topicList.addItem(it)
        self.topicList.blockSignals(False)
        target = selectId if selectId is not None else self.topicId
        row = 0
        for i in range(self.topicList.count()):
            if self.topicList.item(i).data(ROLE_ID) == target:
                row = i
                break
        self.topicList.setCurrentRow(row)
        # blockSignals kullandığımız için seçimi elle işle
        self.OnTopicChanged(self.topicList.currentItem(), None)

    def OnTopicChanged(self, current, _previous):
        newId = current.data(ROLE_ID) if current else None
        self.FlushSave()
        if newId is not None and newId == self.topicId: return  # aynı konu: yeniden yüklemeye gerek yok
        self.topicId = newId
        self.LoadTopic()

    def NewTopic(self):
        name, ok = QInputDialog.getText(self, "Yeni konu", "Konu adı:")
        if ok and name.strip():
            self.FlushSave()
            self.ReloadTopics(self.store.CreateTopic(name))

    def RenameTopic(self):
        if self.topicId is None: return
        cur = self.store.GetTopic(self.topicId)["name"]
        name, ok = QInputDialog.getText(self, "Adını değiştir", "Yeni ad:", text=cur)
        if ok and name.strip():
            self.FlushSave()
            self.store.UpdateTopic(self.topicId, name=name.strip())
            self.ReloadTopics(self.topicId)

    def DeleteTopic(self):
        if self.topicId is None: return
        name = self.store.GetTopic(self.topicId)["name"]
        ans = QMessageBox.question(
            self, "Konuyu sil", f"“{name}” konusu ve tüm kayıtları silinsin mi? Bu geri alınamaz."
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._saveTimer.stop()
            self.store.DeleteTopic(self.topicId)
            self.topicId = None
            self.ReloadTopics()

    def LoadTopic(self):
        has = self.topicId is not None
        self._loadingFlag = True
        if has:
            t = self.store.GetTopic(self.topicId)
            self.goalEdit.setText(t["goal"])
            self.summaryEdit.setPlainText(t["summary"])
        else:
            self.goalEdit.clear()
            self.summaryEdit.clear()
        self._loadingFlag = False
        self.ctxTabs.setEnabled(has)
        self.RefreshItems()
        self.RefreshEntries()
        self.RefreshSources()
        self.RefreshChats()
        self.SchedulePackRefresh()

    #################### hedef / özet

    def OnFieldsChanged(self):
        if not self._loadingFlag: self._saveTimer.start()

    def FlushSave(self):
        if self._saveTimer.isActive():
            self._saveTimer.stop()
            self.SaveFields()

    def SaveFields(self):
        if self._loadingFlag or self.topicId is None: return
        self.store.UpdateTopic(
            self.topicId, goal=self.goalEdit.text(), summary=self.summaryEdit.toPlainText()
        )
        self.SchedulePackRefresh()

    def CopySummaryRequest(self):
        if self.topicId is None: return
        self.FlushSave()
        text = core.BuildSummaryRequest(self.store, self.topicId)
        self._setClipboard(text)
        self.statusBar().showMessage(
            f"Özet isteği kopyalandı (~{core.EstimateTokens(text)} token). Bir sekmeye yapıştır, "
            "cevabını kopyala ve 'içe aktar'a bas.", 10000,
        )

    def ImportSummary(self):
        if self.topicId is None: return
        parsed = core.ParseSummaryResponse(QApplication.clipboard().text())
        if not (parsed["goal"] or parsed["summary"] or parsed["decisions"] or parsed["open"]):
            QMessageBox.information(
                self, "İçe aktar",
                "Panoda tanınan bir özet bulunamadı.\nYapay zekanın cevabında HEDEF:, ÖZET:, KARARLAR: ve "
                "AÇIK İŞLER: başlıkları olmalı.",
            )
            return
        msg = (
            f"Hedef: {'güncellenecek' if parsed['goal'] else 'değişmeyecek'}\n"
            f"Özet: {'güncellenecek' if parsed['summary'] else 'değişmeyecek'}\n"
            f"Karar: {len(parsed['decisions'])} madde · Açık iş: {len(parsed['open'])} madde "
            "(var olanlar silinmez, yeniler eklenir)\n\nİçe aktarılsın mı?"
        )
        if QMessageBox.question(self, "Özeti içe aktar", msg) != QMessageBox.StandardButton.Yes: return
        self.FlushSave()
        core.ApplySummary(self.store, self.topicId, parsed)
        self.LoadTopic()
        self.statusBar().showMessage("Özet içe aktarıldı.", 6000)

    #################### kararlar / açık işler

    def RefreshItems(self):
        self.itemsList.blockSignals(True)
        self.itemsList.clear()
        if self.topicId is not None:
            for i in self.store.ListItems(self.topicId):
                label = ("KARAR" if i["kind"] == "decision" else "AÇIK") + " · " + i["text"]
                it = QListWidgetItem(label)
                it.setData(ROLE_ID, i["id"])
                it.setData(ROLE_KIND, i["kind"])
                if i["kind"] == "open":
                    it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    it.setCheckState(Qt.CheckState.Checked if i["done"] else Qt.CheckState.Unchecked)
                self.itemsList.addItem(it)
        self.itemsList.blockSignals(False)

    def OnItemChanged(self, item):
        if item.data(ROLE_KIND) == "open":
            self.store.SetItemDone(item.data(ROLE_ID), item.checkState() == Qt.CheckState.Checked)
            self.SchedulePackRefresh()

    def AddItem(self):
        if self.topicId is None or not self.itemText.text().strip(): return
        kind = "decision" if self.itemKind.currentIndex() == 0 else "open"
        self.store.AddItem(self.topicId, kind, self.itemText.text())
        self.itemText.clear()
        self.RefreshItems()
        self.SchedulePackRefresh()

    def DeleteItem(self):
        it = self.itemsList.currentItem()
        if it is not None:
            self.store.DeleteItem(it.data(ROLE_ID))
            self.RefreshItems()
            self.SchedulePackRefresh()

    #################### cevaplar

    def RefreshEntries(self):
        self.entryList.blockSignals(True)
        self.entryList.clear()
        if self.topicId is not None:
            for e in reversed(self.store.ListEntries(self.topicId)):  # yeniler üstte
                stamp = time.strftime("%d.%m %H:%M", time.localtime(e["created_at"]))
                label = e["model"] or ("Not" if e["kind"] == "note" else "?")
                pin = "📌 " if e["pinned"] else ""
                it = QListWidgetItem(f"{pin}{label} · {stamp} · {_preview(e['content'])}")
                it.setData(ROLE_ID, e["id"])
                self.entryList.addItem(it)
        self.entryList.blockSignals(False)
        self.entryView.clear()

    def OnEntrySelected(self, current, _previous):
        if current is None:
            self.entryView.clear()
            return
        e = self.store.GetEntry(current.data(ROLE_ID))
        self.entryView.setPlainText(e["content"] if e else "")

    def _addEntry(self, text: str, model: str, kind: str = "answer", quietFlag: bool = False) -> bool:
        eid = self.store.AddEntry(self.topicId, model, text, kind=kind, skipDuplicateFlag=True)
        if eid is None:
            if not quietFlag: self.statusBar().showMessage("Boş ya da zaten kayıtlı olan metin eklenmedi.", 5000)
            return False
        self.RefreshEntries()
        self.SchedulePackRefresh()
        self.statusBar().showMessage(f"{model} cevabı kaydedildi (~{core.EstimateTokens(text)} token).", 6000)
        return True

    def AddFromClipboard(self):
        if self.topicId is None: return
        text = QApplication.clipboard().text().strip()
        if not text:
            self.statusBar().showMessage("Panoda metin yok.", 5000)
            return
        web = self._webFocusTab()
        model = web.model if web else (self.srcModel.currentText().strip() or "Diğer")
        self._addEntry(text, model)

    def AddNote(self):
        if self.topicId is None: return
        text, ok = QInputDialog.getMultiLineText(self, "Not ekle", "Notun:")
        if ok and text.strip(): self._addEntry(text, "Not", kind="note")

    def TogglePin(self):
        it = self.entryList.currentItem()
        if it is None: return
        e = self.store.GetEntry(it.data(ROLE_ID))
        self.store.SetPinned(e["id"], not e["pinned"])
        self.RefreshEntries()
        self.SchedulePackRefresh()

    def DeleteEntry(self):
        it = self.entryList.currentItem()
        if it is None: return
        if QMessageBox.question(self, "Sil", "Bu kayıt silinsin mi?") == QMessageBox.StandardButton.Yes:
            self.store.DeleteEntry(it.data(ROLE_ID))
            self.RefreshEntries()
            self.SchedulePackRefresh()

    def OnClipboardChanged(self):
        if self.topicId is None: return
        text = QApplication.clipboard().text().strip()
        if not text or text == self._ownClip or text.startswith(core.PACK_MARKER): return
        web = self._webFocusTab()
        # "Bağlamı çıkar"dan sonra gelen özet cevabı, sayfa odağı algılanamasa bile tanınır
        if self._awaitingSummaryFlag and core.LooksLikeSummary(text):
            cur = web or self.webTabs.currentWidget()
            model = cur.model if isinstance(cur, BrowserTab) else "Diğer"
            QTimer.singleShot(0, lambda: self._offerSummaryImport(text, model))
            return
        if web is not None:                      # bir sohbet sekmesinde kopyalandı
            if not self.watchCb.isChecked(): return
            model = web.model
        elif self.isActiveWindow():              # uygulamanın kendi alanlarında kopyalandı
            return
        else:                                    # başka bir uygulamada kopyalandı
            if not self.watchExtCb.isChecked(): return
            model = self.srcModel.currentText().strip() or "Diğer"
        if core.LooksLikeSummary(text):        # özet gibi görünen metin: içe aktarmayı öner
            QTimer.singleShot(0, lambda: self._offerSummaryImport(text, model))
            return
        if len(text) < self.minChars.value(): return
        self._addEntry(text, model, quietFlag=True)

    #################### dosyalar

    def RefreshSources(self):
        self.srcList.blockSignals(True)
        self.srcList.clear()
        lines = []
        if self.topicId is not None:
            for s in self.store.ListSources(self.topicId):
                it = QListWidgetItem(s["path"])
                it.setData(ROLE_ID, s["id"])
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if s["enabled"] else Qt.CheckState.Unchecked)
                self.srcList.addItem(it)
            col = core.CollectFiles(self.store, self.topicId, maxFiles=0)
            lines.append(f"Metin dosyası (pakete girebilir): {len(col.text)}")
            lines.append(f"Yüklenecek dosya (PDF/görsel/Office): {len(col.uploads)}")
            lines.append(f"Hassas olduğu için atlanan: {col.sensitive}")
            for m in col.missing: lines.append(f"! Bulunamadı: {m}")
            lines.append("")
            lines.append("En son değişen metin dosyaları:")
            for _p, disp in col.text[:15]: lines.append(f"  {disp}")
            if col.uploads:
                lines.append("")
                lines.append("Yüklenecekler:")
                for p in col.uploads[:15]: lines.append(f"  {p.name}")
        self.srcList.blockSignals(False)
        self.filesInfo.setPlainText("\n".join(lines))

    def _addPaths(self, paths):
        if self.topicId is None: return
        for p in paths:
            if p: self.store.AddSource(self.topicId, p)
        self.RefreshSources()
        self.SchedulePackRefresh()

    def AddFiles(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Dosya seç")
        self._addPaths(paths)

    def AddFolder(self):
        path = QFileDialog.getExistingDirectory(self, "Klasör seç")
        if path: self._addPaths([path])

    def RemoveSource(self):
        it = self.srcList.currentItem()
        if it is not None:
            self.store.RemoveSource(it.data(ROLE_ID))
            self.RefreshSources()
            self.SchedulePackRefresh()

    def OnSourceChanged(self, item):
        self.store.SetSourceEnabled(item.data(ROLE_ID), item.checkState() == Qt.CheckState.Checked)
        self.RefreshSources()
        self.SchedulePackRefresh()

    def OpenUploads(self):
        if self.topicId is None: return
        folder, copied = core.StageUploads(self.store, self.topicId, zipPartsFlag=self.zipCb.isChecked())
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        self.statusBar().showMessage(f"{len(copied)} dosya hazırlandı: {folder}", 10000)

    def _savedFileSelection(self):
        try:
            data = json.loads(self.store.GetMeta(f"filesel_{self.topicId}", "[]") or "[]")
        except ValueError:
            return []
        return [str(gg) for gg in data] if isinstance(data, list) else []

    def AddFilesToCurrentChat(self):
        tab = self.webTabs.currentWidget()
        if not isinstance(tab, BrowserTab):
            self.statusBar().showMessage("Önce bir sohbet sekmesi aç.", 6000)
            return
        self.AddFilesToChat(tab)

    def AddFilesToChat(self, tab):
        """Seçtiğin dosyaları, istediğin an, açık sohbetin mesaj kutusuna ekler (göndermez)."""
        if self.topicId is None:
            self.statusBar().showMessage("Önce soldan bir konu seç.", 6000)
            return
        items = core.ListSelectableFiles(self.store, self.topicId)
        if not items:
            self.panelBtn.setChecked(True)
            self.ctxTabs.setCurrentIndex(2)
            self.statusBar().showMessage(
                "Bu konuda dosya yok. Dosyalar sekmesinden dosya/klasör ekle ya da pencereye sürükleyip bırak.", 8000)
            return
        dlg = FilesDialog(
            self, items, self._savedFileSelection(), zipDefaultFlag=self.zipCb.isChecked(),
            mode=self.store.GetMeta("files_mode", "text"), maskFlag=self.maskCb.isChecked(),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        v = dlg.values()
        chosen = v["items"]
        self.store.SetMeta(f"filesel_{self.topicId}", json.dumps([str(gg.path) for gg in chosen]))
        self.store.SetMeta("files_mode", v["mode"])
        self.zipCb.setChecked(v["zip"])
        self._sendFiles(tab, chosen, v["mode"], v["zip"])

    def _sendFiles(self, tab, chosen, mode, zip_):
        self.webTabs.setCurrentWidget(tab)
        if mode == "text":
            text, included, skipped = core.BuildFilesText(chosen, maskFlag=self.maskCb.isChecked())
            if not included:
                self.statusBar().showMessage(
                    "Seçilenlerde metin dosyası yok. 'Dosya olarak ekle' kipini dene.", 8000)
                return
            self._setClipboard(text)
            tab.PasteIntoPage(delay=250)
            extra = f" {len(skipped)} dosya atlandı (metin değil/sığmadı)." if skipped else ""
            self.statusBar().showMessage(
                f"{len(included)} dosyanın içeriği {tab.name} sekmesine yapıştırılıyor (~{core.EstimateTokens(text)} token)."
                f"{extra} Yapışmadıysa mesaj kutusuna tıklayıp Ctrl+V yap; göndermek sana kalmış.", 15000)
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            att = core.PrepareAttachments(chosen, self.store.GetTopic(self.topicId)["name"], zipPartsFlag=zip_)
        finally:
            QApplication.restoreOverrideCursor()
        if not att.paths:
            self.statusBar().showMessage("Seçilen dosyalar bulunamadı.", 8000)
            return
        self._setClipboardFiles(att.paths)
        tab.PasteIntoPage(delay=300)
        where = f" Hazırlanan klasör: {att.folder}" if att.folder else ""
        notes = (" Uyarı: " + " ".join(att.notes)) if att.notes else ""
        self.statusBar().showMessage(
            f"{len(att.paths)} {'zip parçası' if att.zippedFlag else 'dosya'} {tab.name} sekmesine ekleniyor. "
            "Eklenmediyse mesaj kutusuna tıklayıp Ctrl+V yap ya da dosyaları klasörden sürükle."
            f"{where}{notes}", 20000)

    def _setClipboardFiles(self, paths):
        """Dosyaları panoya 'dosya' olarak koyar (Explorer'da kopyalamak gibi)."""
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(str(gg)) for gg in paths])
        self._ownClip = ""
        QApplication.clipboard().setMimeData(md)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()

    def dropEvent(self, event):
        self._addPaths([gg.toLocalFile() for gg in event.mimeData().urls()])
        event.acceptProposedAction()

    #################### bağlam paketi

    def OnTargetChanged(self, text: str):
        if text in core.DEFAULT_MODELS:
            self.budgetSpin.setValue(core.DEFAULT_MODELS[text])  # değişim yenilemeyi tetikler
        else: self.SchedulePackRefresh()

    def SchedulePackRefresh(self, *_): self._packTimer.start()

    def _options(self) -> core.PackOptions:
        return core.PackOptions(
            targetModel=self.targetModel.currentText().strip() or "Diğer",
            budgetTokens=self.budgetSpin.value(),
            lastN=self.lastnSpin.value(),
            deltaFlag=self.deltaCb.isChecked(),
            includeFilesFlag=self.filesCb.isChecked(),
            maskFlag=self.maskCb.isChecked(),
        )

    def RefreshPack(self):
        if self.topicId is None:
            self.packView.clear()
            self.statsLabel.setText("")
            self._lastPack = None
            return
        opts = self._options()
        try:
            res = core.BuildPack(self.store, self.topicId, opts, request=self.requestEdit.toPlainText())
        except Exception as exc:  # noqa: BLE001  arayüz çökmesin
            self._lastPack = None
            self.statsLabel.setText(f"Paket hazırlanamadı: {exc}")
            return
        self._lastPack = (res, opts)
        self.packView.setPlainText(res.text)

        pct = int(100 * res.tokens / res.budget) if res.budget else 0
        lines = [f"<b>≈ {res.tokens} / {res.budget} token</b> (%{pct}) · mod: {res.mode}"]
        if res.deltaFallbackFlag: lines.append("Bu model için önceki aktarım yok; tam paket hazırlandı.")
        parts = " · ".join(f"{k}: {v}" for k, v in res.parts.items() if v)
        lines.append(parts)
        lines.append(
            f"Konuşma: {res.entriesIncluded}/{res.entriesTotal} · Dosya: {len(res.filesIncluded)} dahil"
            f" ({len(res.filesTrimmed)} kısaltıldı), {len(res.filesOmitted)} bütçeye sığmadı,"
            f" {len(res.filesUnchanged)} değişmedi"
        )
        if res.uploads: lines.append(f"Ayrıca yüklenecek: {len(res.uploads)} dosya (Dosyalar sekmesi)")
        if res.sensitiveSkipped: lines.append(f"Hassas {res.sensitiveSkipped} dosya atlandı")
        if res.filesCut: lines.append(f"{res.filesCut} dosya en-çok-dosya sınırı nedeniyle değerlendirilmedi")
        if res.overBudgetFlag: lines.append("Sabit bölümler bütçeyi aşıyor; bütçeyi artır ya da özeti kısalt.")
        self.statsLabel.setText("<br>".join(lines))

    def _setClipboard(self, text: str):
        self._ownClip = text.strip()
        QApplication.clipboard().setText(text)

    def CopyPack(self):
        if self.topicId is None: return
        self.FlushSave()
        self._packTimer.stop()
        self.RefreshPack()
        if not self._lastPack: return
        res, opts = self._lastPack
        self._setClipboard(res.text)
        self.store.RecordHandoff(self.topicId, opts.targetModel, res.lastEntryId, res.fileHashes)
        self.statusBar().showMessage(
            f"Kopyalandı (~{res.tokens} token). {opts.targetModel} sohbetine Ctrl+V ile yapıştır.", 10000
        )

    def closeEvent(self, event):
        closeToTray = self._tray is not None and self.trayCloseAct.isChecked() and not self._quitFlag
        if closeToTray:   # pencere gizlenir, uygulama (ve açık sohbetler) arka planda çalışmayı sürdürür
            event.ignore()
            self.hide()
            self._tray.showMessage("ggContext", "Arka planda çalışıyor. Simgeye tıklayarak geri açabilirsin.")
            return
        self.FlushSave()
        try:
            self.store.SetMeta("geometry", bytes(self.saveGeometry().toBase64()).decode())
        except Exception:  # noqa: BLE001
            pass
        for i in range(self.webTabs.count()):
            w = self.webTabs.widget(i)
            if isinstance(w, BrowserTab): w.Shutdown()
        super().closeEvent(event)
