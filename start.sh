#!/bin/bash
# ONVIF Kamera-Überwachungssystem - macOS/Linux Start-Skript
# Dieses Skript startet das Kamera-Überwachungssystem

echo "========================================"
echo "ONVIF Kamera-Überwachungssystem"
echo "========================================"
echo ""

# Prüfe ob Python installiert ist
if ! command -v python3 &> /dev/null; then
    echo "FEHLER: Python 3 ist nicht installiert!"
    echo ""
    echo "Bitte installieren Sie Python 3:"
    echo "  macOS: brew install python3"
    echo "  Linux: sudo apt-get install python3"
    echo ""
    exit 1
fi

echo "Python gefunden"
python3 --version
echo ""

# Prüfe ob venv existiert, falls nicht erstelle es
if [ ! -d "venv" ]; then
    echo "Erstelle virtuelle Umgebung..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "FEHLER: Konnte virtuelle Umgebung nicht erstellen!"
        exit 1
    fi
fi

# Aktiviere virtuelle Umgebung
echo "Aktiviere virtuelle Umgebung..."
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "FEHLER: Konnte virtuelle Umgebung nicht aktivieren!"
    exit 1
fi

# Installiere/Update Abhängigkeiten
echo ""
echo "Installiere Abhängigkeiten..."
python3 -m pip install --upgrade pip
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "FEHLER: Konnte Abhängigkeiten nicht installieren!"
    exit 1
fi

# Prüfe ob FFmpeg verfügbar ist
echo ""
if command -v ffmpeg &> /dev/null; then
    echo "FFmpeg gefunden - Audio-Aufnahme verfügbar"
    echo ""
else
    echo "WARNUNG: FFmpeg nicht gefunden - Audio-Aufnahme nicht verfügbar"
    echo "Installieren Sie FFmpeg:"
    echo "  macOS: brew install ffmpeg"
    echo "  Linux: sudo apt-get install ffmpeg"
    echo ""
fi

# Starte das Programm
echo "========================================"
echo "Starte Kamera-Überwachungssystem..."
echo "========================================"
echo ""
echo "Das Dashboard öffnet sich automatisch im Browser"
echo "URL: http://localhost:8080"
echo ""
echo "Zum Beenden: Drücken Sie Ctrl+C"
echo ""

python3 camera_viewer.py

echo ""
echo "Programm beendet."

