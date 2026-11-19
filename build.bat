@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Baglam Koprusu - exe olusturucu
set PYTHONUTF8=1
set PIP_DISABLE_PIP_VERSION_CHECK=1

echo ================================================
echo   Baglam Koprusu - exe olusturucu
echo ================================================
echo.

rem ---- 1) Python'u bul
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto :nopython

rem ---- 2) Surumu denetle: 3.10 ve ustu gerekli, 3.15'e kadar desteklenir
%PY% -c "import sys; v=sys.version_info[:2]; sys.exit(1 if v<(3,10) else (2 if v>(3,15) else 0))" >nul 2>nul
set "RC=%errorlevel%"
if "%RC%"=="0" goto :pyok
if "%RC%"=="2" goto :pynew
if "%RC%"=="1" goto :pyold
goto :nopython

:pynew
echo [UYARI] Python surumunuz 3.15'ten yeni. PySide6 henuz desteklemiyor olabilir, deneniyor...
goto :pyok

:pyok
%PY% --version
echo.

rem ---- 3) Paketler: sistemde zaten varsa onlari kullan, yoksa .venv icine kur
set "RUNPY=%PY%"
%PY% -c "import PySide6, PyInstaller; from PySide6 import QtWebEngineWidgets" >nul 2>nul
if not errorlevel 1 (
    echo PySide6 ^(web bileseniyle^) ve PyInstaller zaten kurulu, mevcut kurulum kullanilacak.
    goto :runtests
)

echo PySide6 / PyInstaller bulunamadi. .venv klasorune kurulacak. PySide6 buyuk bir pakettir, ilk seferde birkac dakika surebilir...
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
)
set "RUNPY=.venv\Scripts\python.exe"
%RUNPY% -m pip install --upgrade pip
%RUNPY% -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail

:runtests
echo.
echo [1/2] Testler calistiriliyor...
%RUNPY% test_core.py
if errorlevel 1 (
    echo [HATA] Testler basarisiz oldu, exe olusturulmadi.
    goto :fail
)

echo.
echo [2/2] Uygulama olusturuluyor. Gomulu tarayici nedeniyle bu adim birkac dakika surebilir...
%RUNPY% -m PyInstaller --noconfirm --clean --noconsole --onedir --icon ggcontext.ico --name ggContext main.py
if errorlevel 1 goto :fail
if not exist "dist\ggContext\ggContext.exe" goto :fail

echo.
echo ================================================
echo   TAMAM:  dist\ggContext\ggContext.exe
echo   Tum dist\ggContext klasoru birlikte tasinmalidir.
echo ================================================
explorer "dist\ggContext"
goto :end

:nopython
echo [HATA] Calisan bir Python bulunamadi.
echo Python 3.12 onerilir: https://www.python.org/downloads/
echo Kurulumda "Add python.exe to PATH" kutusunu isaretleyin, sonra bu dosyayi tekrar calistirin.
goto :fail

:pyold
echo [HATA] Python 3.10 veya daha yenisi gerekli. Mevcut surum:
%PY% --version
echo https://www.python.org/downloads/ adresinden guncel surumu kurun.
goto :fail

:fail
echo.
echo Build basarisiz. Yukaridaki hata mesajini kopyalayip bana gonderin.
pause
exit /b 1

:end
pause
exit /b 0
