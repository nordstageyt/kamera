# ONVIF Kamera-Überwachungssystem - Anleitung

## Systemanforderungen

- Windows 10/11 oder macOS
- Python 3.9 oder höher
- FFmpeg (optional, für Audio-Aufnahme empfohlen)
- Internetverbindung für die Installation

## Installation

### Schritt 1: Python installieren

**Windows:**
1. Laden Sie Python von https://www.python.org/downloads/ herunter
2. Installieren Sie Python (wichtig: Aktivieren Sie "Add Python to PATH" während der Installation)
3. Starten Sie den Computer neu

**macOS:**
1. Python ist bereits installiert, oder installieren Sie es über Homebrew: `brew install python3`

### Schritt 2: FFmpeg installieren (empfohlen)

**Option A: FFmpeg-Binaries in den Programmordner legen (empfohlen für Windows)**

1. Laden Sie FFmpeg von https://ffmpeg.org/download.html herunter
2. Entpacken Sie die Datei
3. Kopieren Sie die FFmpeg-Binaries in den Programmordner:
   - **Windows:** Kopieren Sie `ffmpeg.exe` oder den gesamten `ffmpeg`-Ordner in den Programmordner
   - Das Programm findet FFmpeg automatisch, wenn es im Programmordner liegt

**Option B: FFmpeg systemweit installieren**

**Windows:**
1. Laden Sie FFmpeg von https://ffmpeg.org/download.html herunter
2. Entpacken Sie die Datei
3. Fügen Sie den FFmpeg-Ordner zum System-PATH hinzu (Systemsteuerung → Umgebungsvariablen)

**macOS:**
```bash
brew install ffmpeg
```

### Schritt 3: Programm starten

**Windows:**
- Doppelklicken Sie auf `start.bat`

**macOS:**
- Doppelklicken Sie auf `start.sh` oder öffnen Sie ein Terminal und führen Sie aus:
```bash
./start.sh
```

Beim ersten Start werden automatisch alle benötigten Pakete installiert.

## Verwendung

### Dashboard öffnen

Nach dem Start öffnet sich automatisch Ihr Standard-Browser mit dem Dashboard:
- **URL:** http://localhost:8080

Falls sich der Browser nicht automatisch öffnet, geben Sie die URL manuell ein.

### Kameras scannen

1. Das System scannt beim Start automatisch nach Kameras im Netzwerk (192.168.100.0/24)
2. Gefundene Kameras werden automatisch im Dashboard angezeigt
3. Für funktionierende Kameras startet die Aufnahme automatisch

### Aufnahme steuern

- **Aufnahme starten:** Klicken Sie auf "⏺ Aufnahme starten" bei einer Kamera
- **Aufnahme stoppen:** Klicken Sie auf "⏹ Aufnahme stoppen"
- **Status:** Die Aufnahmedauer wird in Echtzeit angezeigt
- **Modus:** Es wird angezeigt, ob FFmpeg (mit Audio) oder OpenCV (ohne Audio) verwendet wird

### Einstellungen

Klicken Sie auf das ⚙️ Symbol oben rechts:

- **Benutzername:** Standard: `admin`
- **Passwort:** Standard: `123456`
- **Halbierte Auflösung:** Aktivieren Sie diese Option, um Speicherplatz zu sparen
- Nach Änderungen werden die Kameras automatisch neu gescannt

### Aufnahmen ansehen

1. Klicken Sie auf das 📁 Symbol (Recordings)
2. Wählen Sie ein Datum und eine Stunde aus
3. Klicken Sie auf eine Aufnahme zum Abspielen oder Download

### Aufnahmen speichern

Alle Aufnahmen werden im Ordner `aufnahmen/` gespeichert:
- Format: `aufnahmen/YYYY-MM-DD/HH-MM_HH-MM/IP_PORT_YYYY-MM-DD_HH-MM-SS.mp4`
- Beispiel: `aufnahmen/2025-11-28/19-00_20-00/192.168.100.107_888_2025-11-28_19-21-04.mp4`

### Automatische Bereinigung

- Aufnahmen älter als 24 Stunden werden automatisch gelöscht
- Dies geschieht im Hintergrund, Sie müssen nichts tun

## Technische Details

### Netzwerk

- Das System scannt automatisch im Bereich 192.168.100.0/24
- Typische Ports: 888 und 835
- Nur Kameras mit korrekten Login-Daten werden angezeigt

### Aufnahme-Einstellungen

- **Segmentierung:** Neue Datei alle 10 Minuten
- **Format:** MP4 (H.264 Video, AAC Audio wenn FFmpeg verfügbar)
- **Auflösung:** Konfigurierbar (Voll oder halbiert)
- **Qualität:** Standard: 65 (0-100, höher = bessere Qualität)

### Live-Stream

- Live-Vorschau verwendet den Sub-Stream (niedrigere Auflösung)
- Dies spart Bandbreite und Ressourcen

## Fehlerbehebung

### "FFmpeg nicht gefunden"

- Installieren Sie FFmpeg (siehe Schritt 2)
- Stellen Sie sicher, dass FFmpeg im System-PATH verfügbar ist
- Das System funktioniert auch ohne FFmpeg, aber ohne Audio-Aufnahme

### "Keine Kameras gefunden"

- Prüfen Sie, ob die Kameras im Netzwerk 192.168.100.0/24 sind
- Prüfen Sie die Login-Daten in den Einstellungen
- Prüfen Sie, ob die Kameras ONVIF unterstützen

### "Port bereits belegt"

- Ein anderes Programm verwendet Port 8080
- Beenden Sie das andere Programm oder ändern Sie den Port in `camera_viewer.py`

### Aufnahmen sind korrupt

- Stellen Sie sicher, dass genug Speicherplatz verfügbar ist
- Prüfen Sie die Netzwerkverbindung zur Kamera
- Das System verwendet fragmentierte MP4s, die auch bei unerwarteten Beendigungen abspielbar bleiben

## Programm beenden

**Windows:**
- Schließen Sie das Terminal-Fenster oder drücken Sie `Ctrl+C`

**macOS:**
- Drücken Sie `Ctrl+C` im Terminal

Alle laufenden Aufnahmen werden automatisch sauber beendet.

## Support

Bei Problemen prüfen Sie:
1. Die Logs im Terminal-Fenster
2. Ob alle Abhängigkeiten installiert sind
3. Die Netzwerkverbindung zu den Kameras

## Lizenz

Dieses Programm wird "wie besehen" bereitgestellt, ohne Gewährleistung.

