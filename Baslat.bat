@echo off
setlocal EnableExtensions
chcp 65001 > nul
cd /d "%~dp0"

echo =======================================================
echo    TICARET SICIL GAZETESI ARAMA
echo =======================================================
echo.

rem --- Python bul (3.11 veya uzeri)
set "PY="
for %%V in (3.12 3.11 3.13 3.14) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [HATA] Python 3.11 veya uzeri bulunamadi.
    echo.
    echo  1. https://www.python.org/downloads/ adresinden Python 3.12 indirin.
    echo  2. Kurulumda "Add python.exe to PATH" kutusunu isaretleyin.
    echo  3. Bu dosyaya tekrar cift tiklayin.
    echo.
    pause
    exit /b 1
)

rem --- Sanal ortam (ilk calistirmada bir kez)
if not exist ".venv\Scripts\python.exe" (
    echo [*] Ilk kurulum: sanal ortam olusturuluyor...
    %PY% -m venv .venv
    if errorlevel 1 goto :hata
)

rem --- Bagimliliklar (requirements.txt degisince yeniden kurulur)
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1
if errorlevel 1 (
    echo [*] Bagimliliklar kuruluyor. Ilk seferde birkac dakika surebilir...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 goto :hata
    copy /y requirements.txt ".venv\requirements.installed" >nul
)

echo [*] Uygulama baslatiliyor. Tarayiciniz acilacak.
echo     Kapatmak icin bu pencerede Ctrl+C tuslarina basin.
echo.
".venv\Scripts\python.exe" run_server.py
if errorlevel 1 goto :hata
exit /b 0

:hata
echo.
echo [HATA] Bir sorun olustu. Yukaridaki mesaji kontrol edin.
echo        Sik nedenler: internet/proxy erisimi (pip), eksik Python, 8000 portunun baska uygulamada kullanimi.
echo        Baska bir port icin: set PORT=8010 yazip bu dosyayi ayni pencereden calistirin.
pause
exit /b 1
