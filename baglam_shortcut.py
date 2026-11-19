"""ggContext'in Windows Başlat menüsü kısayolu: Windows aramasında (Başlat > yazarak ara) görünmesini sağlar"""
import os
import subprocess
import sys
import threading
from pathlib import Path

APP_TITLE = "ggContext"


def ShortcutPath() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home()) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_TITLE}.lnk"


def _q(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"   # PowerShell tek tırnak kaçışı


def BuildScript(lnk: Path, exe: str) -> str:
    """kısayolu oluşturan PowerShell betiği"""
    return (
        f"$d = Split-Path {_q(lnk)}; if (-not (Test-Path $d)) {{ New-Item -ItemType Directory -Path $d | Out-Null }}; "
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_q(lnk)}); "
        f"$s.TargetPath = {_q(exe)}; $s.WorkingDirectory = {_q(Path(exe).parent)}; "
        f"$s.IconLocation = {_q(exe)}; $s.Description = {_q(APP_TITLE)}; $s.Save()"
    )


def CanCreate() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))   # yalnızca derlenmiş exe için


def EnsureStartMenuShortcut(store, force: bool = False) -> bool:
    """kısayol yoksa ya da exe başka yere taşındıysa (ya da force) arka planda oluşturur; başlatılırsa True döner"""
    if not CanCreate(): return False
    exe, lnk = sys.executable, ShortcutPath()
    if not force and lnk.exists() and store.GetMeta("shortcut_target") == exe: return False

    def work():
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", BuildScript(lnk, exe)],
                creationflags=0x08000000, timeout=30, check=True, capture_output=True,   # CREATE_NO_WINDOW
            )
            store.SetMeta("shortcut_target", exe)
        except Exception: pass

    threading.Thread(target=work, daemon=True).start()
    return True
