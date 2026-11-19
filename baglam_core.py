"""ggContext - çekirdek mantık

Yalnızca Python standart kütüphanesini kullanır; arayüzden bağımsızdır ve test edilebilir

Ne yapar?
  * Konuları, yapay zekalardan gelen cevapları, kararları ve dosya yollarını SQLite'ta saklar
  * Bunlardan, token bütçesine göre kısaltılmış "bağlam paketi" üretir (katmanlı: hedef/özet ->
    kararlar -> son konuşmalar -> dosyalar)
  * "Fark modu": aynı modele daha önce gönderilenleri tekrar göndermez

Hiçbir siteye bağlanmaz, hiçbir şey göndermez. Yalnızca yerel dosyalar ve veritabanıyla çalışır
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import time
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "ggContext"
OLD_APP_NAMES = ("BaglamKoprusu",)   # eski sürümlerin veri klasörü, ilk açılışta taşınır
PACK_MARKER = "# BAĞLAM AKTARIMI"

# varsayılan token bütçeleri (arayüzden değiştirilebilir; gerçek model limitleri değildir)
DEFAULT_MODELS = {"Claude": 8000, "ChatGPT": 8000, "Gemini": 12000, "Diğer": 6000}

# gömülü web sekmeleri için hazır adresler: (sekme adı, adres, model türü)
PRESET_SITES = [
    ("Claude", "https://claude.ai", "Claude"),
    ("ChatGPT", "https://chatgpt.com", "ChatGPT"),
    ("Gemini", "https://gemini.google.com", "Gemini"),
]

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".rst", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".csv", ".tsv", ".html", ".htm", ".css", ".scss", ".xml",
    ".sql", ".sh", ".bat", ".ps1", ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".java", ".kt",
    ".go", ".rs", ".rb", ".php", ".swift", ".lua", ".r", ".tex", ".log", ".qml", ".ui",
    ".gradle", ".vue", ".svelte",
}
TEXT_NAMES = {"dockerfile", "makefile", "readme", "license"}
UPLOAD_EXTS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".png", ".jpg", ".jpeg", ".gif",
    ".webp", ".bmp", ".zip", ".mp3", ".wav", ".mp4",
}
IGNORE_DIRS = {
    "node_modules", "__pycache__", "venv", "env", "dist", "build", "target", "site-packages",
}
SENSITIVE_NAMES = {
    "id_rsa", "id_ed25519", "id_ecdsa", "credentials", "credentials.json", "secrets.json",
    ".npmrc", ".pypirc", ".netrc",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".kdbx", ".jks"}

MAX_FILE_BYTES = 300_000
_TOKEN_DIV = 3.5  # Türkçe + kod için temkinli tahmin: ~3.5 karakter = 1 token


#################### yardımcılar

def DataDir() -> Path:
    override = os.environ.get("BK_DATA_DIR")
    if override: p = Path(override)
    elif sys.platform.startswith("win"): p = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
    else: p = Path.home() / ".ggcontext"
    if not override: p = _migrateOldDataDir(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _migrateOldDataDir(newDir: Path) -> Path:
    """eski adla (Bağlam Köprüsü) kaydedilmiş veriler varsa yeni klasöre taşır; taşınamazsa eskisini kullanır"""
    if newDir.exists(): return newDir
    olds = [newDir.parent / n for n in OLD_APP_NAMES] + [newDir.parent / ".baglamkoprusu"]
    old = next((gg for gg in olds if gg.exists()), None)
    if old is None: return newDir
    try: shutil.move(str(old), str(newDir))
    except OSError: return old   # klasör başka bir süreçte açık olabilir
    return newDir


def EstimateTokens(text: str) -> int:
    """Kabaca token tahmini (gerçek tokenizer değildir)."""
    if not text: return 0
    return math.ceil(len(text) / _TOKEN_DIV)


def TruncateToTokens(text: str, maxTokens: int) -> str:
    """Metni en fazla maxTokens (tahmini) olacak şekilde, baş ve sonu koruyarak kısaltır."""
    if maxTokens <= 0: return ""
    if EstimateTokens(text) <= maxTokens: return text
    maxChars = int(maxTokens * _TOKEN_DIV)
    marker = "\n[... kısaltıldı ...]\n"
    keep = maxChars - len(marker)
    if keep <= 0: return text[:maxChars]
    head = int(keep * 0.65)
    tail = keep - head
    return text[:head] + marker + (text[-tail:] if tail > 0 else "")


_SECRET_RE = re.compile(
    r"(?i)([A-Za-z0-9_\-]*(?:api[_-]?key|secret|passw(?:or)?d|parola|şifre|token|authorization)"
    r"[A-Za-z0-9_\-]*)(\s*[:=]\s*)(['\"]?)([^\s'\"]{6,})(\3)"
)
_KEY_RE = re.compile(
    r"\b(sk-[A-Za-z0-9_\-]{16,}|AIza[0-9A-Za-z_\-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|xox[baprs]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16})\b"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{12,}")


def MaskSecrets(text: str) -> str:
    """Anahtar/parola benzeri değerleri maskeler (en iyi çaba; kusursuz değildir)."""

    def repl(m: re.Match) -> str:
        value = m.group(4)
        if re.fullmatch(r"\d+", value) or any(gg in value for gg in "(){}[]<>") \
                or value.startswith(("self.", "os.", "env", "process.")) \
                or value.lower() in ("bearer", "basic"):
            return m.group(0)
        return f"{m.group(1)}{m.group(2)}{m.group(3)}[GİZLENDİ]{m.group(5)}"

    text = _BEARER_RE.sub("Bearer [GİZLENDİ]", text)  # önce: "Authorization: Bearer <anahtar>"
    text = _SECRET_RE.sub(repl, text)
    return _KEY_RE.sub("[GİZLENDİ]", text)


def IsSensitive(path: Path) -> bool:
    n = path.name.lower()
    return n.startswith(".env") or n in SENSITIVE_NAMES or path.suffix.lower() in SENSITIVE_SUFFIXES


def Classify(path: Path) -> str:
    if IsSensitive(path): return "sensitive"
    ext = path.suffix.lower()
    if ext in TEXT_EXTS or path.name.lower() in TEXT_NAMES: return "text"
    if ext in UPLOAD_EXTS: return "upload"
    return "skip"


def _decode(raw: bytes, truncatedFlag: bool) -> str:
    for cut in range(0, 4 if truncatedFlag else 1):
        try:
            return raw[: len(raw) - cut].decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
    for enc in ("cp1254", "latin-1"):  # eski Türkçe Windows dosyaları için cp1254
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def ReadTextFile(path: Path, maxBytes: int = MAX_FILE_BYTES) -> str | None:
    """Metin dosyasını okur; ikili ya da okunamazsa None döner."""
    try:
        with open(path, "rb") as f:
            raw = f.read(maxBytes + 1)
    except OSError:
        return None
    truncatedFlag = len(raw) > maxBytes
    raw = raw[:maxBytes]
    if b"\x00" in raw[:4096]: return None
    text = _decode(raw, truncatedFlag)
    if truncatedFlag: text += f"\n[... dosya büyük: yalnızca ilk {maxBytes // 1000} KB okundu ...]"
    return text


_READ_CACHE: dict = {}


def ReadTextCached(path: Path) -> str | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key in _READ_CACHE: return _READ_CACHE[key]
    text = ReadTextFile(path)
    if len(_READ_CACHE) > 100: _READ_CACHE.clear()
    _READ_CACHE[key] = text
    return text


def FileDigest(text: str) -> str: return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


def _key(path: Path) -> str: return os.path.normcase(os.path.abspath(str(path)))


def _mtime(path: Path) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


#################### dosya tarama

@dataclass
class ScanResult:
    text: list = field(default_factory=list)
    uploads: list = field(default_factory=list)
    sensitive: list = field(default_factory=list)
    truncatedFlag: bool = False


def ScanSource(path, limit: int = 5000) -> ScanResult:
    """Bir dosya ya da klasörü tarar; metin / yüklenecek / hassas olarak ayırır."""
    p = Path(path)
    res = ScanResult()
    if p.is_file():
        kind = Classify(p)
        if kind == "sensitive": res.sensitive.append(p)
        elif kind == "upload": res.uploads.append(p)
        else:  # açıkça eklenen bilinmeyen uzantı: metin olarak denenir (ikiliyse okunurken elenir)
            res.text.append(p)
        return res
    if not p.is_dir(): return res
    seen = 0
    for dirpath, dirnames, filenames in os.walk(p):
        dirnames[:] = sorted(gg for gg in dirnames if gg not in IGNORE_DIRS and not gg.startswith("."))
        for fn in sorted(filenames):
            seen += 1
            if seen > limit:
                res.truncatedFlag = True
                return res
            f = Path(dirpath) / fn
            kind = Classify(f)
            if kind == "text": res.text.append(f)
            elif kind == "upload": res.uploads.append(f)
            elif kind == "sensitive": res.sensitive.append(f)
    return res


@dataclass
class Collected:
    text: list = field(default_factory=list)      # (Path, gösterim adı)
    uploads: list = field(default_factory=list)   # path
    uploadDisp: list = field(default_factory=list)  # uploads ile aynı sırada gösterim adları
    sensitive: int = 0
    missing: list = field(default_factory=list)
    cut: int = 0


def CollectFiles(store: "Store", topicId: int, maxFiles: int = 30) -> Collected:
    out = Collected()
    seen: set = set()
    cand: list = []
    for src in store.ListSources(topicId):
        if not src["enabled"]: continue
        p = Path(src["path"])
        if not p.exists():
            out.missing.append(str(p))
            continue
        scan = ScanSource(p)
        out.sensitive += len(scan.sensitive)
        for f in scan.text:
            k = _key(f)
            if k in seen: continue
            seen.add(k)
            disp = f"{p.name}/{f.relative_to(p).as_posix()}" if p.is_dir() else f.name
            cand.append((f, disp))
        for f in scan.uploads:
            k = _key(f)
            if k in seen: continue
            seen.add(k)
            out.uploads.append(f)
            out.uploadDisp.append(f"{p.name}/{f.relative_to(p).as_posix()}" if p.is_dir() else f.name)
    cand.sort(key=lambda gg: _mtime(gg[0]), reverse=True)  # en son değişen en önde
    if maxFiles and len(cand) > maxFiles:
        out.cut = len(cand) - maxFiles
        cand = cand[:maxFiles]
    out.text = cand
    return out


#################### veritabanı

class Store:
    def __init__(self, dbPath=None):
        self.path = Path(dbPath) if dbPath else DataDir() / "baglam.db"
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._initSchema()

    def close(self): self.conn.close()

    def _initSchema(self):
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS topics(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    goal TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS entries(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL DEFAULT 'answer',
                    model TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS items(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    text TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sources(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                    path TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(topic_id, path));
                CREATE TABLE IF NOT EXISTS handoffs(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                    model TEXT NOT NULL,
                    last_entry_id INTEGER NOT NULL DEFAULT 0,
                    file_hashes TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sites(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT 'Diğer',
                    created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS meta(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL);
                """
            )

    #################### konular

    def CreateTopic(self, name: str) -> int:
        now = time.time()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO topics(name, created_at, updated_at) VALUES(?,?,?)",
                (name.strip() or "Adsız konu", now, now),
            )
        return cur.lastrowid

    def ListTopics(self): return self.conn.execute("SELECT * FROM topics ORDER BY updated_at DESC, id DESC").fetchall()

    def GetTopic(self, topicId: int): return self.conn.execute("SELECT * FROM topics WHERE id=?", (topicId,)).fetchone()

    def UpdateTopic(self, topicId: int, name=None, goal=None, summary=None):
        sets, vals = [], []
        for col, val in (("name", name), ("goal", goal), ("summary", summary)):
            if val is not None:
                sets.append(f"{col}=?")
                vals.append(val)
        if not sets: return
        sets.append("updated_at=?")
        vals.append(time.time())
        vals.append(topicId)
        with self.conn:
            self.conn.execute(f"UPDATE topics SET {', '.join(sets)} WHERE id=?", vals)

    def DeleteTopic(self, topicId: int):
        with self.conn:
            self.conn.execute("DELETE FROM topics WHERE id=?", (topicId,))

    def _touch(self, topicId: int):
        self.conn.execute("UPDATE topics SET updated_at=? WHERE id=?", (time.time(), topicId))

    #################### cevaplar / notlar

    def AddEntry(self, topicId, model, content, kind="answer", skipDuplicateFlag=False):
        content = content.strip()
        if not content: return None
        if skipDuplicateFlag:
            last = self.conn.execute(
                "SELECT content FROM entries WHERE topic_id=? ORDER BY id DESC LIMIT 1", (topicId,)
            ).fetchone()
            if last and last["content"].strip() == content: return None
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO entries(topic_id, kind, model, content, created_at) VALUES(?,?,?,?,?)",
                (topicId, kind, model.strip(), content, time.time()),
            )
            self._touch(topicId)
        return cur.lastrowid

    def ListEntries(self, topicId):
        return self.conn.execute(
            "SELECT * FROM entries WHERE topic_id=? ORDER BY id ASC", (topicId,)
        ).fetchall()

    def GetEntry(self, entryId): return self.conn.execute("SELECT * FROM entries WHERE id=?", (entryId,)).fetchone()

    def DeleteEntry(self, entryId):
        with self.conn:
            self.conn.execute("DELETE FROM entries WHERE id=?", (entryId,))

    def SetPinned(self, entryId, pinnedFlag: bool):
        with self.conn:
            self.conn.execute("UPDATE entries SET pinned=? WHERE id=?", (1 if pinnedFlag else 0, entryId))

    #################### kararlar / açık işler

    def AddItem(self, topicId, kind, text):
        text = text.strip()
        if not text or kind not in ("decision", "open"): return None
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO items(topic_id, kind, text, created_at) VALUES(?,?,?,?)",
                (topicId, kind, text, time.time()),
            )
            self._touch(topicId)
        return cur.lastrowid

    def ListItems(self, topicId):
        return self.conn.execute(
            "SELECT * FROM items WHERE topic_id=? ORDER BY id ASC", (topicId,)
        ).fetchall()

    def SetItemDone(self, itemId, done: bool):
        with self.conn:
            self.conn.execute("UPDATE items SET done=? WHERE id=?", (1 if done else 0, itemId))

    def DeleteItem(self, itemId):
        with self.conn:
            self.conn.execute("DELETE FROM items WHERE id=?", (itemId,))

    #################### dosya kaynakları

    def AddSource(self, topicId, path):
        path = os.path.abspath(os.path.expanduser(str(path)))
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO sources(topic_id, path) VALUES(?,?)", (topicId, path)
            )

    def ListSources(self, topicId):
        return self.conn.execute(
            "SELECT * FROM sources WHERE topic_id=? ORDER BY id ASC", (topicId,)
        ).fetchall()

    def SetSourceEnabled(self, sourceId, enabledFlag: bool):
        with self.conn:
            self.conn.execute("UPDATE sources SET enabled=? WHERE id=?", (1 if enabledFlag else 0, sourceId))

    def RemoveSource(self, sourceId):
        with self.conn:
            self.conn.execute("DELETE FROM sources WHERE id=?", (sourceId,))

    #################### aktarım kayıtları (fark modu için)

    def LastHandoff(self, topicId, model):
        return self.conn.execute(
            "SELECT * FROM handoffs WHERE topic_id=? AND lower(model)=lower(?) ORDER BY id DESC LIMIT 1",
            (topicId, model),
        ).fetchone()

    def RecordHandoff(self, topicId, model, lastEntryId, fileHashes):
        with self.conn:
            self.conn.execute(
                "INSERT INTO handoffs(topic_id, model, last_entry_id, file_hashes, created_at)"
                " VALUES(?,?,?,?,?)",
                (topicId, model, int(lastEntryId), json.dumps(fileHashes), time.time()),
            )


    #################### ayarlar (küçük anahtar/değer deposu)

    def GetMeta(self, key, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def SetMeta(self, key, value):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (key, str(value)))

    #################### gömülü web sekmeleri (her sekmenin kendi giriş oturumu vardır)

    def ListSites(self):
        """Sekmeler, kullanıcının sürükleyerek belirlediği sırayla (yeni eklenenler sonda) döner."""
        rows = self.conn.execute("SELECT * FROM sites ORDER BY id ASC").fetchall()
        try:
            order = [int(gg) for gg in json.loads(self.GetMeta("site_order", "[]"))]
        except (ValueError, TypeError):
            order = []
        pos = {sid: i for i, sid in enumerate(order)}
        return sorted(rows, key=lambda gg: (pos.get(gg["id"], len(order)), gg["id"]))

    def SaveSiteOrder(self, ids): self.SetMeta("site_order", json.dumps([int(gg) for gg in ids]))

    def GetSite(self, siteId): return self.conn.execute("SELECT * FROM sites WHERE id=?", (siteId,)).fetchone()

    def AddSite(self, name, url, model="Diğer"):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO sites(name, url, model, created_at) VALUES(?,?,?,?)",
                (name.strip() or "Sekme", url, model.strip() or "Diğer", time.time()),
            )
        return cur.lastrowid

    def UpdateSite(self, siteId, name, url, model):
        with self.conn:
            self.conn.execute(
                "UPDATE sites SET name=?, url=?, model=? WHERE id=?",
                (name.strip() or "Sekme", url, model.strip() or "Diğer", siteId),
            )

    def DeleteSite(self, siteId):
        with self.conn:
            self.conn.execute("DELETE FROM sites WHERE id=?", (siteId,))

    def EnsureDefaultSites(self):
        """İlk açılışta Claude/ChatGPT/Gemini sekmelerini ekler; kullanıcı sildiyse bir daha eklemez."""
        if self.GetMeta("sites_seeded") == "1": return
        if not self.ListSites():
            for name, url, model in PRESET_SITES: self.AddSite(name, url, model)
        self.SetMeta("sites_seeded", "1")

    def MarkProfileWipe(self, siteId):
        """Bir sekmenin oturum verisi, uygulama bir sonraki açılışta silinecek."""
        self.SetMeta(f"wipe_site_{int(siteId)}", "1")

    def PopWipeMarks(self) -> set:
        pattern = "wipe\\_site\\_%"
        rows = self.conn.execute(
            "SELECT key FROM meta WHERE key LIKE ? ESCAPE '\\'", (pattern,)
        ).fetchall()
        with self.conn:
            self.conn.execute("DELETE FROM meta WHERE key LIKE ? ESCAPE '\\'", (pattern,))
        return {gg["key"][len("wipe_"):] for gg in rows}


#################### sekme yardımcıları

def NormalizeUrl(text: str) -> str:
    """Kullanıcının yazdığı adresi düzeltir. Yalnızca http/https kabul edilir; geçersizse '' döner."""
    t = (text or "").strip()
    if not t or re.search(r"\s", t): return ""
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*://", t): t = "https://" + t
    m = re.match(r"^https?://([^/?#]+)", t, re.I)
    if not m: return ""
    host = m.group(1)
    if not re.fullmatch(r"[\w\-.]+(:\d{1,5})?", host): return ""
    bare = host.split(":")[0].lower()
    if "." not in bare and bare != "localhost": return ""
    return t


def ProfileDir(siteId) -> Path:
    """Bir sekmenin giriş oturumunun (çerezler, önbellek) tutulduğu yerel klasör."""
    return DataDir() / "profiles" / f"site_{int(siteId)}"


def CleanupProfiles(store: "Store") -> list:
    """silinmiş sekmelerin ve 'oturumu temizle' denenlerin klasörlerini siler

    Yalnızca uygulamanın kendi 'profiles' klasöründeki 'site_<sayı>' klasörlerine dokunur
    Uygulama açılırken, hiçbir sekme henüz oturumu açmadan çağrılmalıdır
    """
    root = DataDir() / "profiles"
    wipe = store.PopWipeMarks()
    if not root.is_dir(): return []
    keep = {f"site_{gg['id']}" for gg in store.ListSites()}
    removed = []
    for d in root.iterdir():
        if not d.is_dir() or not re.fullmatch(r"site_\d+", d.name): continue
        if d.name not in keep or d.name in wipe:
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.name)
    return removed


def CleanSelection(text: str) -> str:
    """Web sayfasında seçilen metindeki Qt/Chromium paragraf ve boşluk işaretlerini düzeltir."""
    t = (text or "").replace(" ", "\n").replace(" ", "\n").replace(" ", " ")
    return t.strip()


#################### paket üretimi

@dataclass
class PackOptions:
    targetModel: str = "Diğer"
    budgetTokens: int = 8000
    lastN: int = 4
    deltaFlag: bool = False
    includeFilesFlag: bool = True
    maxFiles: int = 30
    maskFlag: bool = True


@dataclass
class PackResult:
    text: str = ""
    tokens: int = 0
    budget: int = 0
    mode: str = "tam"                 # "tam" ya da "fark"
    deltaFallbackFlag: bool = False      # fark istendi ama önceki aktarım yok -> tam paket
    overBudgetFlag: bool = False
    parts: dict = field(default_factory=dict)
    entriesIncluded: int = 0
    entriesTotal: int = 0
    filesIncluded: list = field(default_factory=list)
    filesTrimmed: list = field(default_factory=list)
    filesOmitted: list = field(default_factory=list)
    filesUnchanged: list = field(default_factory=list)
    filesCut: int = 0
    uploads: list = field(default_factory=list)
    sensitiveSkipped: int = 0
    missingSources: list = field(default_factory=list)
    lastEntryId: int = 0
    fileHashes: dict = field(default_factory=dict)


def _allocate(sizes: list, budget: int) -> list:
    """Adil paylaşım: küçükler ihtiyacı kadar alır, artan bütçe büyüklere bölünür."""
    budget = max(0, budget)
    n = len(sizes)
    alloc = [0] * n
    remaining = budget
    for pos, i in enumerate(sorted(range(n), key=lambda gg: sizes[gg])):
        share = remaining // (n - pos)
        a = min(sizes[i], share)
        alloc[i] = a
        remaining -= a
    return alloc


def _fitLines(lines: list, maxTokens: int) -> list:
    out, used = [], 0
    for line in reversed(lines):  # en yeniler öncelikli
        t = EstimateTokens(line) + 1
        if used + t > maxTokens: break
        out.append(line)
        used += t
    out.reverse()
    return out


def _entryHeader(e) -> str:
    label = e["model"] or ("Not" if e["kind"] == "note" else "?")
    stamp = time.strftime("%d.%m %H:%M", time.localtime(e["created_at"]))
    return f"### {label} · {stamp}"


def _renderEntries(entries: list, budget: int, maskf) -> list:
    """entries eski->yeni sıralı. Bütçeye sığacak şekilde kısaltılmış blokları döndürür."""
    sel = list(entries)
    if not sel or budget < 40: return []
    while len(sel) > 1 and budget // len(sel) < 80:
        sel.pop(0)  # en eskiyi bırak
    heads = [_entryHeader(gg) for gg in sel]
    bodies = [maskf(gg["content"].strip()) for gg in sel]
    sizes = [EstimateTokens(h) + EstimateTokens(b) for h, b in zip(heads, bodies)]
    alloc = _allocate(sizes, budget)
    blocks = []
    for h, b, a in zip(heads, bodies, alloc):
        ca = a - EstimateTokens(h)
        if ca < min(20, EstimateTokens(b)): continue
        blocks.append(h + "\n" + TruncateToTokens(b, ca))
    return blocks


def _names(names: list, cap: int = 10) -> str:
    shown = ", ".join(names[:cap])
    return shown + (f" (+{len(names) - cap} daha)" if len(names) > cap else "")


def BuildPack(store: Store, topicId: int, opts: PackOptions | None = None, request: str = "") -> PackResult:
    opts = opts or PackOptions()
    topic = store.GetTopic(topicId)
    if topic is None: raise ValueError("Konu bulunamadı")
    tok = EstimateTokens
    budget = max(200, int(opts.budgetTokens))
    maskf = MaskSecrets if opts.maskFlag else (lambda gg: gg)

    handoff = store.LastHandoff(topicId, opts.targetModel) if opts.deltaFlag else None
    deltaFlag = handoff is not None
    res = PackResult(budget=budget, mode="fark" if deltaFlag else "tam", deltaFallbackFlag=opts.deltaFlag and not deltaFlag)
    request = request.strip()

    #################### başlık

    if deltaFlag:
        when = time.strftime("%d.%m.%Y %H:%M", time.localtime(handoff["created_at"]))
        header = (
            f"{PACK_MARKER} (DEVAM) — {topic['name']}\n"
            f"Bu sohbete {when} tarihinde bağlam aktarmıştım. Aşağıda yalnızca o tarihten beri "
            "DEĞİŞENLER var; önceki bağlamla birleştirip çalış, tekrar özetleme."
        )
    else:
        header = (
            f"{PACK_MARKER} — {topic['name']}\n"
            "Bu, başka bir yapay zekayla yürüttüğüm çalışmanın bağlamı. Oku ve konuya hâkim ol; "
            "tekrar özetleme. Kararlarla çelişme, açık işleri aklında tut."
        )
    header += (
        "\nAşağıdaki 'İstek' bölümüne göre devam et."
        if request
        else "\nOkuyunca yalnızca 'Hazırım' de; isteğimi sonraki mesajda yazacağım."
    )

    #################### sabit bölümler: hedef, özet, kararlar, açık işler

    fixedParts = [header]
    goal = (topic["goal"] or "").strip()
    if goal: fixedParts.append("## Hedef\n" + TruncateToTokens(maskf(goal), 200))
    summary = (topic["summary"] or "").strip()
    if summary: fixedParts.append("## Özet\n" + TruncateToTokens(maskf(summary), int(budget * 0.35)))
    items = store.ListItems(topicId)
    decisions = ["- " + maskf(gg["text"]) for gg in items if gg["kind"] == "decision"]
    openItems = ["- " + maskf(gg["text"]) for gg in items if gg["kind"] == "open" and not gg["done"]]
    decLines = _fitLines(decisions, int(budget * 0.25))
    openLines = _fitLines(openItems, int(budget * 0.15))
    if decLines: fixedParts.append("## Alınan kararlar\n" + "\n".join(decLines))
    if openLines: fixedParts.append("## Açık işler\n" + "\n".join(openLines))
    fixedText = "\n\n".join(fixedParts)

    #################### dosyaları topla (bütçe paylaşımı için önce bilinmeli)

    collected = CollectFiles(store, topicId, opts.maxFiles) if opts.includeFilesFlag else Collected()
    res.uploads = [gg.name for gg in collected.uploads]
    res.sensitiveSkipped = collected.sensitive
    res.missingSources = collected.missing
    res.filesCut = collected.cut
    uploadNote = ""
    if res.uploads: uploadNote = "Not: Şu dosyaları sohbete ayrıca yükleyeceğim: " + _names(res.uploads, 8)

    requestText = ("## İstek\n" + request) if request else ""
    reserve = 80  # bölüm başlıkları, notlar, ayraçlar
    remaining = budget - tok(fixedText) - tok(requestText) - tok(uploadNote) - reserve
    remaining = max(0, remaining)

    priorHashes: dict = {}
    if deltaFlag:
        try:
            priorHashes = json.loads(handoff["file_hashes"] or "{}")
        except ValueError:
            priorHashes = {}

    candidates: list = []  # (anahtar, ad, metin, özet)
    unchanged: list = []
    for path, disp in collected.text:
        text = ReadTextCached(path)
        if text is None or not text.strip(): continue
        text = maskf(text)
        h = FileDigest(text)
        k = _key(path)
        if deltaFlag and priorHashes.get(k) == h:
            unchanged.append(disp)
            continue
        candidates.append((k, disp, text, h))
    res.filesUnchanged = unchanged

    #################### konuşmalar

    allEntries = list(store.ListEntries(topicId))
    res.entriesTotal = len(allEntries)
    res.lastEntryId = max((gg["id"] for gg in allEntries), default=0)
    if deltaFlag: selected = [gg for gg in allEntries if gg["id"] > handoff["last_entry_id"]][-12:]
    else:
        recent = allEntries[-opts.lastN:] if opts.lastN > 0 else []
        ids = {gg["id"] for gg in recent}
        pinnedFlag = [gg for gg in allEntries if gg["pinned"] and gg["id"] not in ids][-3:]
        selected = sorted(pinnedFlag + recent, key=lambda gg: gg["id"])
    entriesBudget = int(remaining * 0.55) if candidates else remaining
    blocks = _renderEntries(selected, entriesBudget, maskf)
    res.entriesIncluded = len(blocks)
    entriesText = ("## Son konuşmalar\n" + "\n\n".join(blocks)) if blocks else ""
    entriesUsed = tok(entriesText)

    #################### dosyalar

    filesBudget = max(0, remaining - entriesUsed)
    fileBlocks: list = []
    fullHashes: dict = {}
    chosenN = 0
    alloc: list = []
    if candidates and filesBudget > 0:
        def overhead(disp: str) -> int: return tok(f"#### {disp}\n```\n```") + 1

        m = len(candidates)
        while m >= 1:
            chosen = candidates[:m]
            avail = filesBudget - sum(overhead(gg[1]) for gg in chosen)
            sizes = [tok(gg[2]) for gg in chosen]
            if avail > 0:
                alloc = _allocate(sizes, avail)
                if all(a >= min(s, 60) for a, s in zip(alloc, sizes)):
                    chosenN = m
                    break
            m -= 1
    for (k, disp, text, h), a in zip(candidates[:chosenN], alloc):
        body = TruncateToTokens(text, a)
        if tok(text) > a: res.filesTrimmed.append(disp)
        else: fullHashes[k] = h
        res.filesIncluded.append(disp)
        fence = "~~~~" if "```" in body else "```"
        fileBlocks.append(f"#### {disp}\n{fence}\n{body}\n{fence}")
    res.filesOmitted = [gg[1] for gg in candidates[chosenN:]]

    filesParts = []
    if fileBlocks: filesParts.append("\n\n".join(fileBlocks))
    if unchanged: filesParts.append("Değişmeyen dosyalar (önceden gönderildi): " + _names(unchanged))
    if res.filesOmitted: filesParts.append("Bütçe nedeniyle eklenmeyen dosyalar: " + _names(res.filesOmitted))
    filesText = ("## Dosyalar\n" + "\n\n".join(filesParts)) if filesParts else ""

    #################### birleştir

    sections = [gg for gg in (fixedText, entriesText, filesText, uploadNote, requestText) if gg]
    res.text = "\n\n".join(sections)
    res.tokens = tok(res.text)
    res.overBudgetFlag = res.tokens > budget
    res.parts = {
        "başlık/hedef/özet/kararlar": tok(fixedText),
        "konuşmalar": entriesUsed,
        "dosyalar": tok(filesText),
        "istek": tok(requestText),
    }

    # sonraki fark paketi için: yalnızca TAM gönderilen dosyalar "gönderildi" sayılır
    sent = dict(priorHashes) if deltaFlag else {}
    for k, *_ in candidates: sent.pop(k, None)
    sent.update(fullHashes)
    res.fileHashes = sent
    return res


#################### sohbete eklenecek dosyalar

ZIP_MAX_BYTES = 30 * 1024 * 1024   # sitelerin dosya başına sınırı genelde buna yakındır


@dataclass
class FileItem:
    path: Path
    display: str
    size: int
    kind: str      # "text": metne gömülebilir | "upload": yalnızca dosya olarak eklenebilir (PDF, görsel, Office...)
    mtime: float


def _size(path) -> int:
    try:
        return os.stat(path).st_size
    except OSError:
        return 0


def FormatSize(n: int) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB": return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return f"{n:.0f} B"


def _slug(name: str, fallback: str = "konu") -> str: return re.sub(r"[^\w\-]+", "_", name or "").strip("_") or fallback


def ListSelectableFiles(store: Store, topicId: int) -> list:
    """Konunun açık (işaretli) kaynaklarındaki tüm dosyalar, en son değişen en üstte. Hassas dosyalar yoktur."""
    col = CollectFiles(store, topicId, maxFiles=0)
    items = [FileItem(p, disp, _size(p), "text", _mtime(p)) for p, disp in col.text]
    items += [FileItem(p, disp, _size(p), "upload", _mtime(p)) for p, disp in zip(col.uploads, col.uploadDisp)]
    items.sort(key=lambda gg: gg.mtime, reverse=True)
    return items


def BuildFilesText(items: list, maskFlag: bool = True, maxTotalChars: int = 400_000):
    """Seçilen metin dosyalarını, sohbete yapıştırılacak tek metne çevirir. (metin, eklenenler, atlananlar)"""
    maskf = MaskSecrets if maskFlag else (lambda gg: gg)
    blocks, included, skipped, total = [], [], [], 0
    for it in items:
        if it.kind != "text":
            skipped.append(it.display)
            continue
        text = ReadTextCached(it.path)
        if text is None or not text.strip():
            skipped.append(it.display)
            continue
        body = maskf(text)
        fence = "~~~~" if "```" in body else "```"
        block = f"#### {it.display}\n{fence}\n{body}\n{fence}"
        if total + len(block) > maxTotalChars:
            skipped.append(it.display + " (boyut sınırı)")
            continue
        blocks.append(block)
        included.append(it.display)
        total += len(block)
    text = ("Aşağıdaki dosyaların güncel içerikleri:\n\n" + "\n\n".join(blocks)) if blocks else ""
    return text, included, skipped


def _compressedSize(path) -> int:
    """Dosyanın zip içinde (deflate) kaplayacağı yaklaşık boyut; hiçbir şey yazmadan ölçülür."""
    co = zlib.compressobj(6, zlib.DEFLATED, -15)
    total = 0
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk: break
                total += len(co.compress(chunk))
    except OSError:
        return 0
    return total + len(co.flush())


def PlanZipParts(items: list, maxBytes: int = ZIP_MAX_BYTES) -> list:
    """items: [(Path, arcname)]. Sırayı bozmadan, her zip maxBytes'ı aşmayacak şekilde parçalara böler.
    Tek başına sınırı aşan dosya kendi parçasına konur ve oversize işaretlenir."""
    limit = int(maxBytes * 0.99) - 22
    parts, cur, curSize = [], [], 0

    def flush():
        nonlocal cur, curSize
        if cur: parts.append({"files": cur, "size_estimate": curSize, "oversize": False})
        cur, curSize = [], 0

    for path, arc in items:
        est = _compressedSize(path) + 76 + 2 * len(arc.encode("utf-8"))
        if est > limit:
            flush()
            parts.append({"files": [(path, arc)], "size_estimate": est, "oversize": True})
            continue
        if cur and curSize + est > limit: flush()
        cur.append((path, arc))
        curSize += est
    flush()
    return parts


def BuildZipParts(items: list, outDir, baseName: str, maxBytes: int = ZIP_MAX_BYTES) -> list:
    """Dosyaları outDir içinde <baseName>_01.zip, _02.zip... olarak yazar. Her biri için
    {"path", "size", "files", "oversize"} döner."""
    outDir = Path(outDir)
    outDir.mkdir(parents=True, exist_ok=True)
    plan = PlanZipParts(items, maxBytes)
    built = []
    for n, part in enumerate(plan, 1):
        name = f"{baseName}.zip" if len(plan) == 1 else f"{baseName}_{n:02d}.zip"
        dest = outDir / name
        written = 0
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for path, arc in part["files"]:
                try:
                    zf.write(path, arc)
                    written += 1
                except OSError:
                    continue
        size = dest.stat().st_size
        built.append({"path": dest, "size": size, "files": written, "oversize": part["oversize"] or size > maxBytes})
    return built


def _uniqueArcnames(pairs: list) -> list:
    """[(Path, gösterim adı)] -> [(Path, zip içi ad)]; aynı ad iki kez olmaz."""
    used, out = set(), []
    for path, disp in pairs:
        arc = disp.replace("\\", "/").lstrip("/") or path.name
        base, n = arc, 2
        while arc.lower() in used:
            stem, dot, ext = base.rpartition(".")
            arc = f"{stem}_{n}.{ext}" if dot and stem else f"{base}_{n}"
            n += 1
        used.add(arc.lower())
        out.append((path, arc))
    return out


@dataclass
class Attachments:
    paths: list
    folder: Path | None = None
    zippedFlag: bool = False
    parts: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def PrepareAttachments(items: list, topicName: str, zipPartsFlag: bool = True,
                        maxBytes: int = ZIP_MAX_BYTES) -> Attachments:
    """Sohbete dosya olarak eklenecek yolları hazırlar. Tek dosya ya da zip kapalıysa özgün dosyalar kullanılır;
    birden fazla dosya varsa maxBytes'lık zip parçaları uygulamanın 'yuklenecekler' klasöründe üretilir."""
    files = [gg for gg in items if Path(gg.path).exists()]
    if len(files) <= 1 or not zipPartsFlag: return Attachments(paths=[Path(gg.path) for gg in files])
    folder = DataDir() / "yuklenecekler" / f"{_slug(topicName)}_secim"
    if folder.exists(): shutil.rmtree(folder)  # yalnızca uygulamanın kendi hazırlık klasörü
    arcs = _uniqueArcnames([(Path(gg.path), gg.display) for gg in files])
    built = BuildZipParts(arcs, folder, f"{_slug(topicName)}_dosyalar", maxBytes)
    notes = [
        f"{gg['path'].name} ({FormatSize(gg['size'])}) {FormatSize(maxBytes)} sınırını aşıyor; site kabul etmeyebilir."
        for gg in built if gg["oversize"]
    ]
    return Attachments(paths=[gg["path"] for gg in built], folder=folder, zippedFlag=True, parts=built, notes=notes)


def StageUploads(store: Store, topicId: int, zipPartsFlag: bool = False, maxBytes: int = ZIP_MAX_BYTES):
    """PDF/görsel gibi sohbete yüklenmesi gereken dosyaları tek klasöre koyar (zipPartsFlag açıksa ve birden
    fazla dosya varsa maxBytes'lık zip parçaları olarak)."""
    topic = store.GetTopic(topicId)
    slug = _slug(topic["name"], f"konu_{topicId}")
    folder = DataDir() / "yuklenecekler" / slug
    if folder.exists(): shutil.rmtree(folder)  # yalnızca uygulamanın kendi hazırlık klasörü
    folder.mkdir(parents=True)
    col = CollectFiles(store, topicId, maxFiles=0)
    if zipPartsFlag and len(col.uploads) > 1:
        arcs = _uniqueArcnames(list(zip(col.uploads, col.uploadDisp)))
        built = BuildZipParts(arcs, folder, f"{slug}_dosyalar", maxBytes)
        return folder, [gg["path"] for gg in built]
    copied = []
    for f in col.uploads:
        dest = folder / f.name
        n = 2
        while dest.exists():
            dest = folder / f"{f.stem}_{n}{f.suffix}"
            n += 1
        try:
            shutil.copy2(f, dest)
            copied.append(dest)
        except OSError:
            continue
    return folder, copied


#################### özet isteği / içe aktarma

SUMMARY_FORMAT = (
    "HEDEF: <tek cümle>\n"
    "ÖZET: <en fazla 200 kelime; yalnızca devam etmek için gereken bilgi ve düzenlenen dosyalar>\n"
    "KARARLAR:\n- <kesinleşmiş kararlar>\n"
    "AÇIK İŞLER:\n- <yapılacaklar / cevap bekleyen sorular>"
)


def BuildSummaryRequest(store: Store, topicId: int, maxEntries: int = 10, budget: int = 6000) -> str:
    """Herhangi bir yapay zekaya yapıştırılacak 'bağlamı özetle' istemi üretir."""
    topic = store.GetTopic(topicId)
    parts = [
        "Aşağıda bir çalışmanın mevcut özeti, kararları ve son konuşmaları var. Bunları okuyup "
        "GÜNCEL bağlam özetini TAM OLARAK şu formatta üret (başka açıklama ekleme):\n\n"
        + SUMMARY_FORMAT
        + "\n\nKurallar: gereksiz ayrıntıyı at, bilgi uydurma, önemli sayı/isim/dosya adlarını koru.",
        "---",
        f"## Konu: {topic['name']}",
    ]
    if (topic["goal"] or "").strip(): parts.append("Mevcut hedef: " + topic["goal"].strip())
    if (topic["summary"] or "").strip():
        parts.append("Mevcut özet:\n" + TruncateToTokens(topic["summary"].strip(), budget // 3))
    items = store.ListItems(topicId)
    dec = [f"- {gg['text']}" for gg in items if gg["kind"] == "decision"]
    opn = [f"- {gg['text']}" for gg in items if gg["kind"] == "open" and not gg["done"]]
    if dec: parts.append("Mevcut kararlar:\n" + "\n".join(_fitLines(dec, budget // 6)))
    if opn: parts.append("Mevcut açık işler:\n" + "\n".join(_fitLines(opn, budget // 6)))
    used = sum(EstimateTokens(gg) for gg in parts)
    blocks = _renderEntries(list(store.ListEntries(topicId))[-maxEntries:], max(0, budget - used), MaskSecrets)
    if blocks: parts.append("## Son konuşmalar\n" + "\n\n".join(blocks))
    return "\n\n".join(parts)


_TR_MAP = str.maketrans("İıÖöÇçŞşĞğÜü", "IiOoCcSsGgUu")
_HEAD_RE = re.compile(r"^(HEDEF|OZET|KARARLAR|ACIK ISLER)\b[\s*_]*:?[\s*_]*")
_SECTION_KEYS = {"HEDEF": "goal", "OZET": "summary", "KARARLAR": "decisions", "ACIK ISLER": "open"}
_BULLET_RE = re.compile(r"^\s*(?:[-*•–]|\d+[.)])\s+(.*)$")


def ParseSummaryResponse(text: str) -> dict:
    """Yapay zekanın SUMMARY_FORMAT'a uygun cevabını ayrıştırır."""
    out = {"goal": [], "summary": [], "decisions": [], "open": []}
    current = None
    for line in (text or "").splitlines():
        if re.match(r"^\s*```\w*\s*$", line):   # kod bloğu çitleri
            continue
        core = re.sub(r"^[#>\s*_]+", "", line)
        folded = core.translate(_TR_MAP).upper()
        m = _HEAD_RE.match(folded)
        if m:
            current = _SECTION_KEYS[m.group(1)]
            rest = core[m.end():].strip(" *_") if len(folded) == len(core) else ""
            if rest:
                if current in ("goal", "summary"): out[current].append(rest)
                else:
                    b = _BULLET_RE.match(rest)
                    if b: out[current].append(b.group(1).strip())
            continue
        if current is None or not line.strip(): continue
        if current in ("goal", "summary"): out[current].append(line.strip())
        else:
            b = _BULLET_RE.match(line)
            if b: out[current].append(b.group(1).strip())
            elif out[current]: out[current][-1] += " " + line.strip()  # önceki maddenin devamı
    return {
        "goal": " ".join(out["goal"]).strip(),
        "summary": "\n".join(out["summary"]).strip(),
        "decisions": [gg for gg in out["decisions"] if gg],
        "open": [gg for gg in out["open"] if gg],
    }


def ApplySummary(store: Store, topicId: int, parsed: dict) -> dict:
    """Ayrıştırılmış özeti konuya uygular. Hedef/özet güncellenir; maddeler eklenir (silinmez)."""
    goal = (parsed.get("goal") or "").strip()
    summary = (parsed.get("summary") or "").strip()
    if goal or summary: store.UpdateTopic(topicId, goal=goal or None, summary=summary or None)
    existing = {(gg["kind"], gg["text"].casefold()) for gg in store.ListItems(topicId)}
    added = {"decisions": 0, "open": 0}
    for key, kind in (("decisions", "decision"), ("open", "open")):
        for text in parsed.get(key, []):
            if (kind, text.casefold()) in existing: continue
            store.AddItem(topicId, kind, text)
            existing.add((kind, text.casefold()))
            added[key] += 1
    return {"goal": bool(goal), "summary": bool(summary), **added}


def LooksLikeSummary(text: str) -> bool:
    """Metin, SUMMARY_FORMAT'a uygun bir özet cevabına benziyor mu? (en az 3 başlık, biri ÖZET)"""
    if not text or "<tek cümle>" in text:      # bizim kendi istemimiz
        return False
    heads = set()
    for line in text.splitlines():
        folded = re.sub(r"^[#>\s*_]+", "", line).translate(_TR_MAP).upper()
        m = re.match(r"^(HEDEF|OZET|KARARLAR|ACIK ISLER)[\s*_]*:", folded)
        if m: heads.add(m.group(1))
    return len(heads) >= 3 and "OZET" in heads


_SUMMARY_RULES = (
    "Kurallar:\n"
    "- Yalnızca devam etmek için gereken bilgiyi yaz; bilgi uydurma; önemli sayı, isim ve dosya adlarını koru.\n"
    "- ÖZET'e, bu sohbette oluşturduğumuz ya da düzenlediğimiz dosyaların adlarını ve her birinde ne "
    "değiştiğini de ekle (dosya içeriğini yazma).\n"
    "- KARARLAR'a kesinleşmiş kararları, AÇIK İŞLER'e bekleyen işleri yaz."
)

TRANSCRIPT_MAX_CHARS = 80_000  # bir sayfadan alınıp başka sekmeye yapıştırılacak metnin üst sınırı (~23 bin token)


def _existingContextBlock(store: Store, topicId: int, budget: int,
                            mergeWith: str = "bu sohbetle", latestIn: str = "bu sohbetteki en son durumu") -> str:
    """Konuda daha önce kayıtlı bağlam varsa, yeni özetle BİRLEŞTİRİLMESİNİ isteyen bölüm; yoksa ''."""
    topic = store.GetTopic(topicId)
    existing = []
    if (topic["goal"] or "").strip(): existing.append("Mevcut hedef: " + topic["goal"].strip())
    if (topic["summary"] or "").strip():
        existing.append("Mevcut özet:\n" + TruncateToTokens(topic["summary"].strip(), budget // 2))
    items = store.ListItems(topicId)
    dec = ["- " + gg["text"] for gg in items if gg["kind"] == "decision"]
    opn = ["- " + gg["text"] for gg in items if gg["kind"] == "open" and not gg["done"]]
    if dec: existing.append("Mevcut kararlar:\n" + "\n".join(_fitLines(dec, budget // 6)))
    if opn: existing.append("Mevcut açık işler:\n" + "\n".join(_fitLines(opn, budget // 6)))
    if not existing: return ""
    return (
        f"Bu konu için başka sohbetlerden kayıtlı bağlam da var. Bunu {mergeWith} BİRLEŞTİRİP güncel tek bir "
        f"özet yaz; çelişki olursa {latestIn} esas al.\n\n" + "\n".join(existing)
    )


def BuildInlineSummaryPrompt(store: Store, topicId: int, budget: int = 1800) -> str:
    """Sohbetin İÇİNE yapıştırılacak istem: o sohbetteki yapay zeka, konuşmanın tamamını zaten bildiği için
    genel bağlam özetini kendisi çıkarır. Konuda daha önce kayıtlı bağlam varsa, birleştirmesi istenir."""
    parts = [
        "Bu sohbetin TAMAMINA dayanarak, başka bir yapay zekaya devredilebilecek GENEL BAĞLAM ÖZETİ hazırla.\n"
        "Cevabını TAM OLARAK şu formatta ver, başka açıklama ekleme:\n\n" + SUMMARY_FORMAT,
        _SUMMARY_RULES,
    ]
    block = _existingContextBlock(store, topicId, budget)
    if block: parts.append(block)
    return "\n\n".join(parts)


def BuildTranscriptSummaryPrompt(store: Store, topicId: int, transcript: str, budget: int = 1800) -> str:
    """BAŞKA bir sekmedeki yapay zekaya yapıştırılacak istem: sohbetin metni istemin içinde gönderilir,
    çünkü o yapay zeka konuşmayı bilmez."""
    parts = [
        "Aşağıda bir yapay zeka sohbetinin metni var. Bu metne dayanarak, başka bir yapay zekaya "
        "devredilebilecek GENEL BAĞLAM ÖZETİ hazırla.\n"
        "Cevabını TAM OLARAK şu formatta ver, başka açıklama ekleme:\n\n" + SUMMARY_FORMAT,
        _SUMMARY_RULES + "\n"
        "- Metin bir web sayfasından alındığı için menü, kenar çubuğu, düğme adı ve başka sohbetlerin başlıkları "
        "gibi alakasız yazılar içerebilir; bunları yok say, yalnızca asıl konuşmayı özetle.\n"
        "- Konuşan taraflar kullanıcı ve yapay zekadır; kararları ve son durumu esas al.",
    ]
    block = _existingContextBlock(
        store, topicId, budget,
        mergeWith="aşağıdaki sohbet metniyle", latestIn="aşağıdaki sohbet metnindeki en son durumu",
    )
    if block: parts.append(block)
    parts.append("=== SOHBET METNİ BAŞLANGIÇ ===\n" + transcript + "\n=== SOHBET METNİ BİTİŞ ===")
    parts.append("Şimdi yukarıdaki sohbet metnini, istenen biçimde (HEDEF / ÖZET / KARARLAR / AÇIK İŞLER) özetle.")
    return "\n\n".join(parts)


def CleanPageText(text: str, maxChars: int = TRANSCRIPT_MAX_CHARS) -> str:
    """Sayfadan okunan metni toparlar: satır sonları, fazla boş satırlar; çok uzunsa ortası kısaltılır
    (baş %15, son %85 korunur: güncel durum sonda olur)."""
    t = (text or "").replace("\r\n", "\n").replace(" ", "\n").replace(" ", "\n").replace(" ", " ")
    out, blank = [], 0
    for ln in t.split("\n"):
        ln = ln.rstrip()
        if ln.strip() == "":
            blank += 1
            if blank == 1: out.append("")
        else:
            blank = 0
            out.append(ln)
    t = "\n".join(out).strip()
    if len(t) > maxChars:
        head = int(maxChars * 0.15)
        tail = maxChars - head
        t = t[:head] + "\n[... sohbetin ortası kısaltıldı ...]\n" + t[-tail:]
    return t


def AddChromiumFlag(current: str, flag: str) -> str:
    """QTWEBENGINE_CHROMIUM_FLAGS değerine, yoksa, bir bayrak ekler (var olanları korur)."""
    parts = (current or "").split()
    if flag not in parts: parts.append(flag)
    return " ".join(parts)


#################### sekmeler arası "başka sekmeye sor"

RELAY_MAX_CHARS = 60_000
DEFAULT_RELAY_TEMPLATES = [
    ("Olduğu gibi sor", "{metin}"),
    ("Web'de araştır",
     "Aşağıdaki konuyu web'de araştır. Güncel ve güvenilir kaynaklara dayan, kaynak bağlantılarını ver, "
     "emin olmadığın yerleri açıkça belirt. Cevabı Türkçe ve düzenli yaz.\n\n{metin}"),
    ("Eleştir, hataları bul",
     "Aşağıdaki metni eleştirel gözle incele: mantık hatalarını, eksikleri ve yanlış olabilecek iddiaları "
     "maddeler halinde yaz, her biri için düzeltme öner.\n\n{metin}"),
    ("Özetle", "Aşağıdaki metni en fazla 10 maddede, önemli ayrıntıları kaybetmeden özetle.\n\n{metin}"),
    ("Türkçeye çevir", "Aşağıdaki metni anlamı ve tonu koruyarak doğal bir Türkçeyle çevir.\n\n{metin}"),
]


def ParseRelayTemplates(text: str) -> list:
    """'# Ad' satırıyla başlayan bloklardan şablon listesi üretir. {metin} yoksa istemin sonuna eklenir."""
    out, name, body = [], None, []

    def flush():
        if name is not None:
            b = "\n".join(body).strip()
            if name and b: out.append((name, b if "{metin}" in b else b + "\n\n{metin}"))

    for line in (text or "").splitlines():
        if line.startswith("# "):
            flush()
            name, body = line[2:].strip(), []
        elif name is not None: body.append(line)
    flush()
    return out


def FormatRelayTemplates(templates: list) -> str: return "\n\n".join(f"# {n}\n{b}" for n, b in templates) + "\n"


def GetRelayTemplates(store: Store) -> list:
    saved = ParseRelayTemplates(store.GetMeta("relay_templates", "") or "")
    return saved or list(DEFAULT_RELAY_TEMPLATES)


def SaveRelayTemplates(store: Store, templates: list) -> None:
    store.SetMeta("relay_templates", FormatRelayTemplates(templates) if templates else "")


def ApplyRelayTemplate(body: str, text: str) -> str:
    """{metin} yerine seçili metni koyar (str.format kullanılmaz; metindeki süslü parantezler bozulmaz)."""
    return body.replace("{metin}", text[:RELAY_MAX_CHARS].strip())


#################### sürükle-bırak ile gelen yollar

def ItemsFromPaths(paths) -> tuple:
    """Sürüklenen dosya/klasörlerden FileItem listesi üretir. (öğeler, hassas olduğu için atlananların sayısı)"""
    items, sensitive, seen = [], 0, set()
    for raw in paths:
        p = Path(raw)
        scan = ScanSource(p)
        sensitive += len(scan.sensitive)
        for f, kind in [(gg, "text") for gg in scan.text] + [(gg, "upload") for gg in scan.uploads]:
            k = _key(f)
            if k in seen: continue
            seen.add(k)
            disp = f"{p.name}/{f.relative_to(p).as_posix()}" if p.is_dir() else f.name
            items.append(FileItem(f, disp, _size(f), kind, _mtime(f)))
    items.sort(key=lambda gg: gg.mtime, reverse=True)
    return items, sensitive


#################### son konuşmalar (konu zaman çizelgesi)

CHAT_HISTORY_MAX = 50


def IsChatUrl(url: str) -> bool:
    """bir sohbetin adresi gibi mi? (claude.ai/chat/<id>, chatgpt.com/c/<id>, gemini.google.com/app/<id> ...)"""
    from urllib.parse import urlparse
    try:
        u = urlparse(url)
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not u.netloc: return False
    return len([gg for gg in u.path.split("/") if gg]) >= 2


def RecordChat(store: Store, topicId: int, siteId: int, url: str, title: str = "", now: float | None = None) -> bool:
    """Sohbeti konunun geçmişine yazar (aynı adres tekrar gelirse en üste alınır, başlık güncellenir)."""
    if topicId is None or not IsChatUrl(url): return False
    key = f"chats_{topicId}"
    try:
        data = json.loads(store.GetMeta(key, "[]") or "[]")
    except ValueError:
        data = []
    old = next((gg for gg in data if gg.get("site") == siteId and gg.get("url") == url), None)
    title = (title or "").strip() or (old.get("title", "") if old else "")
    data = [gg for gg in data if not (gg.get("site") == siteId and gg.get("url") == url)]
    data.insert(0, {"site": int(siteId), "url": url, "title": title, "ts": time.time() if now is None else now})
    store.SetMeta(key, json.dumps(data[:CHAT_HISTORY_MAX], ensure_ascii=False))
    return True


def ListChats(store: Store, topicId: int, limit: int = 10) -> list:
    try:
        data = json.loads(store.GetMeta(f"chats_{topicId}", "[]") or "[]")
    except ValueError:
        return []
    return [gg for gg in data if isinstance(gg, dict) and gg.get("url")][:limit]


def RemoveChat(store: Store, topicId: int, siteId: int, url: str) -> None:
    data = [gg for gg in ListChats(store, topicId, CHAT_HISTORY_MAX) if not (gg.get("site") == siteId and gg.get("url") == url)]
    store.SetMeta(f"chats_{topicId}", json.dumps(data, ensure_ascii=False))


#################### Google Çeviri kutusu

TRANSLATE_MAX_CHARS = 1800     # adres satırına sığması için


def GuessTargetLang(text: str) -> str:
    """Metin Türkçe harfler/sözcükler içeriyorsa İngilizceye, değilse Türkçeye çevirmeyi önerir."""
    t = text.lower()
    trChars = sum(t.count(gg) for gg in "çğışöü")
    trWords = sum(1 for gg in (" ve ", " bir ", " bu ", " için ", " ile ", " değil ") if gg in f" {t} ")
    return "en" if trChars >= 2 or trWords >= 2 else "tr"


def TranslateUrl(text: str, target: str) -> tuple:
    """Kaynak dili Google'ın kendisi algılar (sl=auto). (adres, kısaltıldı mı)"""
    from urllib.parse import quote
    text = " ".join(text.split())
    cut = len(text) > TRANSLATE_MAX_CHARS
    text = text[:TRANSLATE_MAX_CHARS]
    return f"https://translate.google.com/?sl=auto&tl={target}&text={quote(text)}&op=translate", cut


#################### açık sohbetteki son yapay zeka mesajını seç

LAST_REPLY_SELECTORS = {
    # sitelerin sayfa yapısı değişebilir; bulunamazsa uygulama bunu bildirir. İlk eşleşen seçici kullanılır
    "claude.ai": ['[data-testid="assistant-message"]', ".font-claude-response", ".font-claude-message",
                  '[class*="font-claude-"]'],
    "chatgpt.com": ['[data-message-author-role="assistant"]', 'article[data-testid^="conversation-turn"] .markdown'],
    "chat.openai.com": ['[data-message-author-role="assistant"]'],
    "gemini.google.com": ["model-response message-content", "message-content", ".model-response-text",
                          "model-response"],
}


def LastReplySelectors(url: str) -> list:
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    for h, sel in LAST_REPLY_SELECTORS.items():
        if host == h or host.endswith("." + h): return list(sel)
    return []


def LastReplyJs(selectors: list) -> str:
    """Sayfadaki son eşleşen öğenin içeriğini seçer; seçilen karakter sayısını döndürür (0: bulunamadı)."""
    return (
        "(function(sels){"
        "for (var i=0;i<sels.length;i++){"
        "var els=document.querySelectorAll(sels[i]); if(!els.length) continue;"
        "var el=els[els.length-1]; var txt=(el.innerText||'').trim(); if(!txt) continue;"
        "el.scrollIntoView({block:'center'});"
        "var r=document.createRange(); r.selectNodeContents(el);"
        "var s=window.getSelection(); s.removeAllRanges(); s.addRange(r); return txt.length;}"
        "return 0;})(" + json.dumps(selectors) + ")"
    )
