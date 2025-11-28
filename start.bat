@echo off
REM ONVIF Kamera-Überwachungssystem - Windows Start-Skript
REM Dieses Skript startet das Kamera-Überwachungssystem

echo ========================================
echo ONVIF Kamera-Überwachungssystem
echo ========================================
echo.

REM Prüfe ob Python installiert ist
python --version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Python ist nicht installiert oder nicht im PATH!
    echo.
    echo Bitte installieren Sie Python von https://www.python.org/downloads/
    echo Wichtig: Aktivieren Sie "Add Python to PATH" waehrend der Installation
    echo.
    pause
    exit /b 1
)

echo Python gefunden
python --version
echo.

REM Prüfe ob venv existiert, falls nicht erstelle es
if not exist "venv\" (
    echo Erstelle virtuelle Umgebung...
    python -m venv venv
    if errorlevel 1 (
        echo FEHLER: Konnte virtuelle Umgebung nicht erstellen!
        pause
        exit /b 1
    )
)

REM Aktiviere virtuelle Umgebung
echo Aktiviere virtuelle Umgebung...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo FEHLER: Konnte virtuelle Umgebung nicht aktivieren!
    pause
    exit /b 1
)

REM Installiere/Update Abhängigkeiten
echo.
echo Installiere Abhaengigkeiten...
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo FEHLER: Konnte Abhaengigkeiten nicht installieren!
    pause
    exit /b 1
)

REM Prüfe ob FFmpeg verfügbar ist
echo.
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo WARNUNG: FFmpeg nicht gefunden - Audio-Aufnahme nicht verfuegbar
    echo Installieren Sie FFmpeg von https://ffmpeg.org/download.html
    echo.
) else (
    echo FFmpeg gefunden - Audio-Aufnahme verfuegbar
    echo.
)

REM Starte das Programm
echo ========================================
echo Starte Kamera-Überwachungssystem...
echo ========================================
echo.
echo Das Dashboard oeffnet sich automatisch im Browser
echo URL: http://localhost:8080
echo.
echo Zum Beenden: Druecken Sie Ctrl+C oder schliessen Sie dieses Fenster
echo.

python camera_viewer.py

REM Wenn das Programm beendet wird, warte auf Benutzereingabe
echo.
echo Programm beendet.
pause

