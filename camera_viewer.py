#!/usr/bin/env python3
"""
ONVIF Camera Viewer - Findet Kameras im Netzwerk und zeigt Live-Streams in einem Grid
"""
import socket
import threading
import time
import os
import signal
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from onvif import ONVIFCamera, ONVIFError
import netifaces
from flask import Flask, render_template_string, Response
import logging
import cv2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask App
app = Flask(__name__)

# Globale Variable für gefundene Kameras
found_cameras = []

# Dictionary für aktive Video-Captures
video_captures = {}
capture_locks = {}

# Globale Variablen für Aufnahmen
recording_status = {}  # {camera_index: {'recording': bool, 'writer': VideoWriter, 'filename': str, 'cap': VideoCapture, 'start_time': datetime}}
recording_locks = {}   # Locks für Thread-sichere Aufnahmen
recording_start_locks = {}  # Locks um zu verhindern, dass mehrere Aufnahmen gleichzeitig gestartet werden

# Scan-Status
scan_in_progress = False
scan_lock = threading.Lock()

# HTML Template für die Web-Oberfläche
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ONVIF Camera Viewer</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #1a1a1a;
            color: #fff;
            padding: 20px;
        }
        
        .header {
            text-align: center;
            margin-bottom: 30px;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            color: #4CAF50;
        }
        
        .header p {
            color: #aaa;
            font-size: 1.1em;
        }
        
        .controls {
            text-align: center;
            margin-bottom: 30px;
        }
        
        .btn {
            background: #4CAF50;
            color: white;
            border: none;
            padding: 12px 30px;
            font-size: 16px;
            border-radius: 5px;
            cursor: pointer;
            margin: 0 10px;
            transition: background 0.3s;
        }
        
        .btn:hover {
            background: #45a049;
        }
        
        .btn:disabled {
            background: #666;
            cursor: not-allowed;
        }
        
        .status {
            text-align: center;
            margin: 20px 0;
            font-size: 1.1em;
        }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            max-width: 1800px;
            margin: 0 auto;
        }
        
        .camera-card {
            background: #2a2a2a;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
            transition: transform 0.3s;
        }
        
        .camera-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.4);
        }
        
        .camera-header {
            background: #333;
            padding: 15px;
            border-bottom: 2px solid #4CAF50;
        }
        
        .camera-header h3 {
            margin: 0;
            color: #4CAF50;
            font-size: 1.2em;
        }
        
        .camera-header p {
            margin: 5px 0 0 0;
            color: #aaa;
            font-size: 0.9em;
        }
        
        .recording-controls {
            margin-top: 10px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .btn-record {
            background: #f44336;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            transition: background 0.3s;
        }
        
        .btn-record:hover {
            background: #d32f2f;
        }
        
        .btn-record.recording {
            background: #4CAF50;
            animation: pulse 1.5s infinite;
        }
        
        .btn-record.recording:hover {
            background: #45a049;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }
        
        .record-status {
            color: #4CAF50;
            font-size: 0.9em;
            font-weight: bold;
        }
        
        .video-container {
            position: relative;
            width: 100%;
            padding-top: 56.25%; /* 16:9 Aspect Ratio */
            background: #000;
        }
        
        .video-container video {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            object-fit: contain;
        }
        
        .error-message {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: #f44336;
            text-align: center;
            padding: 20px;
        }
        
        .loading {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: #4CAF50;
            font-size: 1.2em;
        }
        
        @media (max-width: 768px) {
            .grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>📹 ONVIF Camera Viewer</h1>
        <p>Live-Streams aller gefundenen Kameras</p>
    </div>
    
    <div class="controls">
        <button class="btn" onclick="scanCameras()">🔍 Kameras scannen</button>
        <button class="btn" onclick="location.reload()">🔄 Seite aktualisieren</button>
    </div>
    
    <div class="status" id="status">
        {% if cameras %}
            {{ cameras|length }} Kamera(s) gefunden
        {% else %}
            Keine Kameras gefunden. Klicken Sie auf "Kameras scannen"
        {% endif %}
    </div>
    
    <div class="grid">
        {% if cameras %}
            {% for camera in cameras %}
            <div class="camera-card">
                <div class="camera-header">
                    <h3>{{ camera.name }}</h3>
                    <p>{{ camera.host }}:{{ camera.port }}</p>
                    <div class="recording-controls">
                        <button class="btn-record" onclick="toggleRecording({{ loop.index0 }})" id="record-btn-{{ loop.index0 }}">
                            <span id="record-text-{{ loop.index0 }}">⏺ Aufnahme starten</span>
                        </button>
                        <span id="record-status-{{ loop.index0 }}" class="record-status"></span>
                    </div>
                </div>
                <div class="video-container">
                    {% if camera.stream_url %}
                        <img src="/stream/{{ loop.index0 }}" alt="Camera Stream" style="width: 100%; height: 100%; object-fit: contain;">
                    {% else %}
                        <div class="error-message">
                            ⚠️ Keine Stream-URL verfügbar
                        </div>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        {% else %}
            <div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: #aaa;">
                <p style="font-size: 1.5em;">Keine Kameras gefunden</p>
                <p>Klicken Sie auf "Kameras scannen" um nach ONVIF-Kameras zu suchen</p>
            </div>
        {% endif %}
    </div>
    
    <script>
        function scanCameras() {
            document.getElementById('status').textContent = 'Suche nach Kameras...';
            fetch('/scan', {method: 'POST'})
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        document.getElementById('status').textContent = data.message;
                        setTimeout(() => location.reload(), 2000);
                    } else {
                        document.getElementById('status').textContent = 'Fehler: ' + data.message;
                    }
                })
                .catch(error => {
                    document.getElementById('status').textContent = 'Fehler beim Scannen: ' + error;
                });
        }
        
        function toggleRecording(cameraIndex) {
            const btn = document.getElementById(`record-btn-${cameraIndex}`);
            const text = document.getElementById(`record-text-${cameraIndex}`);
            const status = document.getElementById(`record-status-${cameraIndex}`);
            
            if (btn.classList.contains('recording')) {
                // Stoppe Aufnahme
                fetch(`/record/stop/${cameraIndex}`, {method: 'POST'})
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            btn.classList.remove('recording');
                            text.textContent = '⏺ Aufnahme starten';
                            status.textContent = '';
                        } else {
                            alert('Fehler: ' + data.message);
                        }
                    })
                    .catch(error => {
                        alert('Fehler beim Stoppen der Aufnahme: ' + error);
                    });
            } else {
                // Starte Aufnahme
                fetch(`/record/start/${cameraIndex}`, {method: 'POST'})
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            btn.classList.add('recording');
                            text.textContent = '⏹ Aufnahme stoppen';
                            status.textContent = 'Aufnahme läuft...';
                        } else {
                            alert('Fehler: ' + data.message);
                        }
                    })
                    .catch(error => {
                        alert('Fehler beim Starten der Aufnahme: ' + error);
                    });
            }
        }
        
        // Status regelmäßig aktualisieren
        setInterval(() => {
            fetch('/record/status')
                .then(response => response.json())
                .then(data => {
                    for (let idx in data) {
                        const status = data[idx];
                        const btn = document.getElementById(`record-btn-${idx}`);
                        const text = document.getElementById(`record-text-${idx}`);
                        const statusEl = document.getElementById(`record-status-${idx}`);
                        
                        if (!btn || !text || !statusEl) continue;
                        
                        if (status.recording) {
                            if (!btn.classList.contains('recording')) {
                                btn.classList.add('recording');
                                text.textContent = '⏹ Aufnahme stoppen';
                            }
                            if (status.start_time) {
                                const start = new Date(status.start_time);
                                const duration = Math.floor((new Date() - start) / 1000);
                                const mins = Math.floor(duration / 60);
                                const secs = duration % 60;
                                statusEl.textContent = `⏺ ${mins}:${secs.toString().padStart(2, '0')}`;
                            }
                        } else {
                            if (btn.classList.contains('recording')) {
                                btn.classList.remove('recording');
                                text.textContent = '⏺ Aufnahme starten';
                                statusEl.textContent = '';
                            }
                        }
                    }
                })
                .catch(error => {
                    // Ignoriere Fehler beim Status-Abruf
                });
        }, 1000);
    </script>
</body>
</html>
"""


def get_local_network():
    """Ermittelt das lokale Netzwerk - fokussiert auf 192.168.100.0/24"""
    return "192.168.100"


def check_port(host, port, timeout=0.3):
    """Prüft ob ein Port auf einem Host offen ist"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False


def test_onvif_connection(host, port, username, password):
    """Testet ONVIF-Verbindung mit gegebenen Credentials"""
    try:
        # Erstelle Camera mit kürzerem Timeout
        camera = ONVIFCamera(host, port, username, password)
        # Versuche Device-Info abzurufen (schneller Test)
        device_info = camera.devicemgmt.GetDeviceInformation()
        return True, camera, device_info
    except Exception as e:
        # Nur bei Debug-Level loggen, nicht bei jedem fehlgeschlagenen Versuch
        return False, None, None


def get_stream_uri(camera, username, password):
    """Holt die RTSP-Streaming-URL direkt von der ONVIF-Kamera über die Media Service API
    Wählt das Profil mit der höchsten Auflösung (Main-Stream)"""
    try:
        # Erstelle Media Service (bereits authentifiziert über camera-Objekt)
        media_service = camera.create_media_service()
        
        # Hole alle Profile von der ONVIF-Kamera
        profiles = media_service.GetProfiles()
        
        if not profiles or len(profiles) == 0:
            logger.warning("Keine Profile von ONVIF-Kamera gefunden")
            return None
        
        # Finde das Profil mit der höchsten Auflösung (Main-Stream)
        best_profile = None
        max_resolution = 0  # Starte mit 0, suche Maximum
        
        for profile in profiles:
            try:
                # Versuche VideoEncoderConfiguration zu holen
                video_config = None
                try:
                    # Hole VideoEncoderConfiguration für dieses Profil
                    if hasattr(profile, 'VideoEncoderConfiguration') and profile.VideoEncoderConfiguration:
                        video_config_token = profile.VideoEncoderConfiguration.token
                        video_config = media_service.GetVideoEncoderConfiguration({'ConfigurationToken': video_config_token})
                except Exception as e:
                    logger.debug(f"Konnte VideoEncoderConfiguration nicht holen: {e}")
                    continue
                
                if video_config:
                    # Berechne Auflösung (Breite * Höhe)
                    width = 0
                    height = 0
                    
                    try:
                        # Versuche Resolution zu extrahieren
                        if hasattr(video_config, 'Resolution'):
                            res = video_config.Resolution
                            if hasattr(res, 'Width'):
                                width = int(res.Width) if res.Width else 0
                            if hasattr(res, 'Height'):
                                height = int(res.Height) if res.Height else 0
                    except Exception as e:
                        logger.debug(f"Konnte Resolution nicht extrahieren: {e}")
                    
                    if width > 0 and height > 0:
                        resolution = width * height
                        
                        if resolution > max_resolution:
                            max_resolution = resolution
                            best_profile = profile
                            logger.debug(f"Neues bestes Profil (höchste Auflösung) gefunden: {width}x{height} (Auflösung: {resolution})")
            except Exception as e:
                logger.debug(f"Fehler beim Prüfen des Profils: {e}")
                continue
        
        # Falls kein Profil mit Auflösung gefunden wurde, verwende das erste (meist Main-Stream)
        if best_profile is None:
            logger.info("Konnte Auflösungen nicht ermitteln, verwende erstes Profil (meist Main-Stream)")
            best_profile = profiles[0]
        else:
            logger.info(f"Verwende Profil mit höchster Auflösung: {max_resolution} Pixel (Main-Stream)")
        
        profile = best_profile
        
        # Versuche StreamSetup über zeep_client zu erstellen (aus dem ONVIF Schema)
        try:
            # StreamSetup ist im ONVIF Schema (tt:) definiert, nicht im Media Service Namespace
            zeep_client = media_service.zeep_client
            stream_setup_type = zeep_client.get_type('ns0:StreamSetup')
            transport_type = zeep_client.get_type('ns0:Transport')
            
            # Erstelle Transport-Objekt
            transport = transport_type()
            transport.Protocol = 'RTSP'
            
            # Erstelle StreamSetup-Objekt
            stream_setup = stream_setup_type()
            stream_setup.Stream = 'RTP-Unicast'
            stream_setup.Transport = transport
            
            # Rufe GetStreamUri von der ONVIF-Kamera auf - gibt RTSP-URL zurück
            uri = media_service.GetStreamUri({
                'ProfileToken': profile.token,
                'StreamSetup': stream_setup
            })
        except Exception as e_setup:
            # Fallback: Versuche mit Dictionary-Struktur
            logger.debug(f"StreamSetup-Objekt-Erstellung fehlgeschlagen, verwende Dictionary: {e_setup}")
            try:
                uri = media_service.GetStreamUri({
                    'ProfileToken': profile.token,
                    'StreamSetup': {
                        'Stream': 'RTP-Unicast',
                        'Transport': {
                            'Protocol': 'RTSP'
                        }
                    }
                })
            except Exception as e_dict:
                # Letzter Fallback: Versuche ohne StreamSetup (manche Kameras unterstützen das)
                logger.debug(f"Dictionary-Ansatz fehlgeschlagen, versuche ohne StreamSetup: {e_dict}")
                uri = media_service.GetStreamUri({'ProfileToken': profile.token})
        
        # Die RTSP-URL kommt direkt von der ONVIF-Kamera
        stream_url = uri.Uri
        logger.debug(f"RTSP-URL von ONVIF-Kamera erhalten: {stream_url}")
        
        # Stelle sicher, dass Credentials in der RTSP-URL enthalten sind
        if stream_url and stream_url.startswith('rtsp://'):
            from urllib.parse import urlparse, urlunparse
            parsed = urlparse(stream_url)
            
            # Wenn keine Credentials in der URL sind, füge sie hinzu
            if not parsed.username:
                # Erstelle neue URL mit Credentials
                netloc = f"{username}:{password}@{parsed.hostname}"
                if parsed.port:
                    netloc += f":{parsed.port}"
                new_parsed = parsed._replace(netloc=netloc)
                stream_url = urlunparse(new_parsed)
                logger.debug(f"Credentials zur RTSP-URL hinzugefügt")
        
        return stream_url
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Stream-URL per SOAP: {e}")
        return None


def scan_camera(host, port, username, password):
    """Scannt eine einzelne Kamera - nur wenn SOAP-Auth mit admin/123456 erfolgreich"""
    # Teste Port schnell
    if not check_port(host, port, timeout=0.3):
        return None
    
    # Teste ONVIF-Verbindung per SOAP mit admin/123456
    success, camera, device_info = test_onvif_connection(host, port, username, password)
    
    # Wenn Authentifizierung fehlschlägt, Kamera nicht anzeigen
    if not success:
        return None
    
    try:
        # Hole Stream URL per SOAP (bereits authentifiziert)
        stream_url = get_stream_uri(camera, username, password)
        
        # Wenn keine Stream-URL abgerufen werden konnte, Kamera nicht anzeigen
        if not stream_url:
            logger.debug(f"Keine Stream-URL für {host}:{port} - Kamera wird nicht angezeigt")
            return None
        
        # Hole Device-Informationen
        device_name = f"Kamera {host}"
        if device_info:
            try:
                # Versuche Model-Name zu extrahieren
                model = getattr(device_info, 'Model', None)
                if model:
                    if hasattr(model, '_value_1'):
                        device_name = model._value_1
                    elif isinstance(model, str):
                        device_name = model
                    elif hasattr(model, 'text'):
                        device_name = model.text
            except:
                pass
        
        camera_info = {
            'host': host,
            'port': port,
            'name': device_name,
            'stream_url': stream_url,
            'device_info': device_info
        }
        
        logger.info(f"✓ Kamera gefunden (SOAP-Auth erfolgreich): {host}:{port} - {device_name}")
        logger.info(f"  RTSP-URL von ONVIF-Schnittstelle: {stream_url}")
        return camera_info
        
    except Exception as e:
        logger.error(f"Fehler beim Verarbeiten von {host}:{port}: {e}")
        # Bei Fehler Kamera nicht anzeigen
        return None


def scan_network(username='admin', password='123456', ports=[888, 835]):
    """Scannt das Netzwerk nach ONVIF-Kameras"""
    global found_cameras, scan_in_progress
    
    # Prüfe ob bereits ein Scan läuft
    with scan_lock:
        if scan_in_progress:
            logger.warning("Scan läuft bereits, überspringe...")
            return found_cameras
        
        scan_in_progress = True
    
    try:
        found_cameras = []
        
        network_base = get_local_network()
        logger.info(f"Scanne Netzwerk {network_base}.0/24 auf Ports {ports}...")
        
        # Erstelle Liste aller zu testenden Hosts
        hosts_to_scan = []
        for i in range(1, 255):
            for port in ports:
                hosts_to_scan.append((f"{network_base}.{i}", port))
        
        # Scanne parallel mit ThreadPoolExecutor - deutlich mehr Worker für schnelleren Scan
        with ThreadPoolExecutor(max_workers=100) as executor:
            futures = {
                executor.submit(scan_camera, host, port, username, password): (host, port)
                for host, port in hosts_to_scan
            }
            
            completed = 0
            total = len(futures)
            for future in as_completed(futures):
                completed += 1
                if completed % 50 == 0:
                    logger.info(f"Scan Fortschritt: {completed}/{total} ({completed*100//total}%)")
                result = future.result()
                if result:
                    found_cameras.append(result)
        
        logger.info(f"Scan abgeschlossen. {len(found_cameras)} Kamera(s) gefunden.")
        
        # Starte automatisch Aufnahmen für alle gefundenen Kameras
        if found_cameras:
            logger.info("Starte automatisch Aufnahmen für alle gefundenen Kameras...")
            for idx, camera in enumerate(found_cameras):
                # Prüfe ob bereits eine Aufnahme läuft
                if idx in recording_status and recording_status[idx].get('recording', False):
                    logger.info(f"Aufnahme läuft bereits für Kamera {idx} ({camera.get('host')}:{camera.get('port')}), überspringe...")
                    continue
                
                try:
                    success, message = start_recording(idx)
                    if success:
                        logger.info(f"Aufnahme gestartet für Kamera {idx}: {camera.get('host')}:{camera.get('port')}")
                    else:
                        logger.warning(f"Konnte Aufnahme nicht starten für Kamera {idx}: {message}")
                except Exception as e:
                    logger.error(f"Fehler beim Starten der Aufnahme für Kamera {idx}: {e}")
        
        return found_cameras
    finally:
        # Setze Scan-Status zurück
        with scan_lock:
            scan_in_progress = False


@app.route('/')
def index():
    """Hauptseite"""
    return render_template_string(HTML_TEMPLATE, cameras=found_cameras)


@app.route('/scan', methods=['POST'])
def scan():
    """Startet den Netzwerk-Scan"""
    try:
        cameras = scan_network()
        return {
            'success': True,
            'message': f'{len(cameras)} Kamera(s) gefunden',
            'cameras': len(cameras)
        }
    except Exception as e:
        logger.error(f"Fehler beim Scannen: {e}")
        return {
            'success': False,
            'message': str(e)
        }


@app.route('/cameras')
def cameras_json():
    """Gibt gefundene Kameras als JSON zurück"""
    return {'cameras': found_cameras}


def ensure_recordings_dir():
    """Erstellt den aufnahmen-Ordner falls nicht vorhanden"""
    os.makedirs('aufnahmen', exist_ok=True)


def cleanup_old_recordings(max_age_hours=24):
    """Löscht Aufnahmen, die älter als max_age_hours sind"""
    try:
        aufnahmen_dir = 'aufnahmen'
        if not os.path.exists(aufnahmen_dir):
            return 0, 0
        
        current_time = datetime.now()
        deleted_count = 0
        deleted_size = 0
        
        # Durchlaufe alle Dateien rekursiv
        for root, dirs, files in os.walk(aufnahmen_dir):
            for file in files:
                if file.endswith('.mp4'):
                    file_path = os.path.join(root, file)
                    try:
                        # Versuche Datum/Zeit aus Dateinamen zu extrahieren (Format: IP_PORT_YYYY-MM-DD_HH-MM-SS.mp4)
                        file_age_hours = None
                        try:
                            # Extrahiere Datum/Zeit aus Dateinamen
                            parts = file.replace('.mp4', '').split('_')
                            if len(parts) >= 4:
                                date_str = parts[-2]  # YYYY-MM-DD
                                time_str = parts[-1]  # HH-MM-SS
                                file_datetime = datetime.strptime(f"{date_str}_{time_str}", "%Y-%m-%d_%H-%M-%S")
                                file_age_hours = (current_time - file_datetime).total_seconds() / 3600
                        except:
                            pass
                        
                        # Fallback: Verwende mtime (Modifikationszeit)
                        if file_age_hours is None:
                            file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                            file_age_hours = (current_time - file_mtime).total_seconds() / 3600
                        
                        # Prüfe ob Datei älter als max_age_hours ist
                        if file_age_hours > max_age_hours:
                            file_size = os.path.getsize(file_path)
                            os.remove(file_path)
                            deleted_count += 1
                            deleted_size += file_size
                            logger.debug(f"Gelöscht (älter als {max_age_hours}h, {file_age_hours:.1f}h alt): {file_path}")
                    except Exception as e:
                        logger.error(f"Fehler beim Löschen von {file_path}: {e}")
        
        # Lösche leere Ordner
        for root, dirs, files in os.walk(aufnahmen_dir, topdown=False):
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                try:
                    if not os.listdir(dir_path):  # Ordner ist leer
                        os.rmdir(dir_path)
                        logger.debug(f"Leerer Ordner gelöscht: {dir_path}")
                except:
                    pass
        
        if deleted_count > 0:
            logger.info(f"Bereinigung: {deleted_count} Dateien gelöscht ({deleted_size/(1024*1024):.1f} MB), älter als {max_age_hours} Stunden")
        
        return deleted_count, deleted_size
    except Exception as e:
        logger.error(f"Fehler bei der Bereinigung alter Aufnahmen: {e}")
        return 0, 0


def cleanup_worker():
    """Hintergrund-Thread für regelmäßige Bereinigung alter Aufnahmen"""
    while True:
        try:
            # Warte 1 Stunde
            time.sleep(3600)
            # Führe Bereinigung durch (Dateien älter als 24 Stunden)
            cleanup_old_recordings(max_age_hours=24)
        except Exception as e:
            logger.error(f"Fehler im Cleanup-Worker: {e}")
            time.sleep(3600)  # Warte weiterhin bei Fehler


def get_recording_filename(camera_host, camera_port):
    """Erstellt Dateinamen und Ordnerstruktur: aufnahmen/YYYY-MM-DD/HH-MM_HH-MM/IP_PORT_YYYY-MM-DD_HH-MM-SS.mp4"""
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    
    # Erstelle Uhrzeit-Bereich (Stundensegment): 14-00_15-00
    hour = now.hour
    next_hour = (hour + 1) % 24
    time_range = f"{hour:02d}-00_{next_hour:02d}-00"
    
    # Erstelle Ordnerstruktur: aufnahmen/YYYY-MM-DD/HH-MM_HH-MM/
    day_folder = os.path.join('aufnahmen', date_str, time_range)
    os.makedirs(day_folder, exist_ok=True)
    
    timestamp = now.strftime('%Y-%m-%d_%H-%M-%S')
    filename = f"{camera_host}_{camera_port}_{timestamp}.mp4"
    return os.path.join(day_folder, filename)


def start_recording(camera_index):
    """Startet die Aufnahme für eine Kamera - Thread-sicher"""
    if camera_index >= len(found_cameras):
        return False, "Kamera nicht gefunden"
    
    # Erstelle Lock für diese Kamera, falls nicht vorhanden
    if camera_index not in recording_start_locks:
        recording_start_locks[camera_index] = threading.Lock()
    
    # Verwende Lock um sicherzustellen, dass nur ein Thread die Aufnahme startet
    with recording_start_locks[camera_index]:
        # Prüfe ob bereits eine Aufnahme läuft
        if camera_index in recording_status:
            status = recording_status[camera_index]
            if status.get('recording', False):
                logger.warning(f"Aufnahme läuft bereits für Kamera {camera_index}, überspringe...")
                return False, "Aufnahme läuft bereits"
            else:
                # Alte Aufnahme vorhanden, aber nicht aktiv - entferne sie sauber
                logger.info(f"Entferne alte inaktive Aufnahme für Kamera {camera_index}")
                try:
                    if 'writer' in status and status['writer'] is not None:
                        try:
                            status['writer'].release()
                        except:
                            pass
                    if 'cap' in status and status['cap'] is not None:
                        try:
                            status['cap'].release()
                        except:
                            pass
                except:
                    pass
                del recording_status[camera_index]
                if camera_index in recording_locks:
                    del recording_locks[camera_index]
        
        camera = found_cameras[camera_index]
        stream_url = camera.get('stream_url')
        host = camera.get('host')
        port = camera.get('port')
        
        if not stream_url:
            return False, "Keine Stream-URL verfügbar"
        
        try:
            ensure_recordings_dir()
            filename = get_recording_filename(host, port)
            
            # Öffne Video-Capture für Aufnahme
            cap = cv2.VideoCapture(stream_url)
            if not cap.isOpened():
                return False, "Konnte Stream nicht öffnen"
            
            # Hole Video-Eigenschaften
            fps = int(cap.get(cv2.CAP_PROP_FPS)) or 25
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            # Fallback falls keine gültigen Werte
            if width <= 0 or height <= 0:
                width, height = 1920, 1080  # Standard HD
            
            # Initialisiere Aufnahme-Status
            # Der VideoWriter wird im record_camera Thread erstellt für bessere Segmentierung
            recording_status[camera_index] = {
                'recording': True,
                'writer': None,  # Wird im Thread erstellt
                'filename': filename,
                'cap': cap,
                'start_time': datetime.now()
            }
            recording_locks[camera_index] = threading.Lock()
            
            # Starte Aufnahme-Thread
            thread = threading.Thread(target=record_camera, args=(camera_index,), daemon=True)
            thread.start()
            
            logger.info(f"Aufnahme gestartet für Kamera {camera_index}: {filename}")
            return True, filename
            
        except Exception as e:
            logger.error(f"Fehler beim Starten der Aufnahme: {e}")
            return False, str(e)


def record_camera(camera_index):
    """Aufnahme-Thread für eine Kamera - mit robuster Segmentierung für Crash-Sicherheit"""
    status = recording_status.get(camera_index)
    if not status:
        return
    
    cap = status['cap']
    lock = recording_locks.get(camera_index)
    camera = found_cameras[camera_index]
    host = camera.get('host')
    port = camera.get('port')
    
    # Video-Eigenschaften
    fps = int(cap.get(cv2.CAP_PROP_FPS)) or 25
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if width <= 0 or height <= 0:
        width, height = 1920, 1080
    
    # Segmentierung: Neue Datei alle 10 Minuten oder bei Dateigröße > 500MB
    segment_duration = 600  # 10 Minuten in Sekunden
    max_file_size = 500 * 1024 * 1024  # 500 MB
    frame_count = 0
    segment_start_time = datetime.now()
    current_writer = None
    current_filename = None
    
    def create_new_segment():
        """Erstellt ein neues Video-Segment"""
        nonlocal current_writer, current_filename, segment_start_time, frame_count
        
        # Schließe alte Datei sauber
        if current_writer is not None:
            try:
                current_writer.release()
                logger.debug(f"Segment geschlossen: {current_filename}")
            except:
                pass
        
        # Erstelle neue Datei
        current_filename = get_recording_filename(host, port)
        # MP4-Format mit H.264 Codec für bessere Komprimierung
        # Versuche verschiedene H.264 Codecs (abhängig von System)
        fourcc = None
        for codec_name in ['avc1', 'H264', 'h264', 'X264']:
            try:
                test_fourcc = cv2.VideoWriter_fourcc(*codec_name)
                # Teste ob Codec funktioniert
                test_writer = cv2.VideoWriter('/tmp/test_codec.mp4', test_fourcc, fps, (width, height))
                if test_writer.isOpened():
                    test_writer.release()
                    try:
                        os.remove('/tmp/test_codec.mp4')
                    except:
                        pass
                    fourcc = test_fourcc
                    logger.debug(f"H.264 Codec '{codec_name}' funktioniert")
                    break
            except:
                continue
        
        # Fallback auf mp4v falls H.264 nicht verfügbar
        if fourcc is None:
            logger.warning("H.264 Codec nicht verfügbar, verwende mp4v")
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        
        # Erstelle VideoWriter mit Qualitätsparameter
        # Versuche Qualitätsparameter zu setzen (nicht alle Codecs unterstützen das)
        try:
            current_writer = cv2.VideoWriter(current_filename, fourcc, fps, (width, height))
            # Setze Qualität (0-100, höher = bessere Qualität, größere Datei)
            # 85 ist ein guter Kompromiss zwischen Qualität und Dateigröße
            current_writer.set(cv2.VIDEOWRITER_PROP_QUALITY, 85)
        except:
            # Fallback ohne Qualitätsparameter
            current_writer = cv2.VideoWriter(current_filename, fourcc, fps, (width, height))
        
        if not current_writer.isOpened():
            logger.error(f"Konnte VideoWriter nicht erstellen: {current_filename}")
            return False
        
        segment_start_time = datetime.now()
        frame_count = 0
        status['writer'] = current_writer
        status['filename'] = current_filename
        logger.info(f"Neues Segment gestartet: {current_filename}")
        return True
    
    # Erstelle erstes Segment
    if not create_new_segment():
        logger.error("Konnte erstes Segment nicht erstellen")
        return
    
    while status['recording']:
        try:
            ret, frame = cap.read()
            if ret:
                with lock:
                    current_writer.write(frame)
                    frame_count += 1
                    
                    # Regelmäßiges Flushen (alle 30 Frames = ~1 Sekunde bei 30fps)
                    if frame_count % 30 == 0:
                        # Force flush durch Zugriff auf die Datei
                        try:
                            import sys
                            sys.stdout.flush()
                        except:
                            pass
                    
                    # Prüfe ob neues Segment nötig ist (Zeit oder Größe)
                    elapsed = (datetime.now() - segment_start_time).total_seconds()
                    file_size = os.path.getsize(current_filename) if os.path.exists(current_filename) else 0
                    
                    if elapsed >= segment_duration or file_size >= max_file_size:
                        logger.info(f"Segment-Wechsel: Zeit={elapsed:.0f}s, Größe={file_size/(1024*1024):.1f}MB")
                        if not create_new_segment():
                            logger.error("Konnte neues Segment nicht erstellen")
                            break
            else:
                # Stream unterbrochen, versuche neu zu verbinden
                time.sleep(0.1)
                cap.release()
                cap = cv2.VideoCapture(camera.get('stream_url'))
                if cap.isOpened():
                    status['cap'] = cap
                    # Aktualisiere Video-Eigenschaften
                    fps = int(cap.get(cv2.CAP_PROP_FPS)) or 25
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    if width <= 0 or height <= 0:
                        width, height = 1920, 1080
                else:
                    break
        except Exception as e:
            logger.error(f"Fehler während Aufnahme: {e}")
            break
    
    # Finales Cleanup - schließe letzte Datei sauber
    try:
        if current_writer is not None:
            current_writer.release()
            logger.info(f"Letztes Segment geschlossen: {current_filename}")
        cap.release()
    except Exception as e:
        logger.error(f"Fehler beim Cleanup: {e}")
    
    logger.info(f"Aufnahme beendet für Kamera {camera_index}")


def stop_recording(camera_index):
    """Stoppt die Aufnahme für eine Kamera"""
    if camera_index not in recording_status:
        return False, "Keine aktive Aufnahme"
    
    status = recording_status[camera_index]
    if not status['recording']:
        return False, "Keine aktive Aufnahme"
    
    status['recording'] = False
    filename = status['filename']
    
    # Warte kurz, damit Thread sauber beendet wird
    time.sleep(0.5)
    
    # Entferne aus Status
    if camera_index in recording_status:
        del recording_status[camera_index]
    if camera_index in recording_locks:
        del recording_locks[camera_index]
    
    logger.info(f"Aufnahme gestoppt: {filename}")
    return True, filename


@app.route('/record/start/<int:camera_index>', methods=['POST'])
def start_record(camera_index):
    """Startet Aufnahme für eine Kamera"""
    success, message = start_recording(camera_index)
    return {'success': success, 'message': message}


@app.route('/record/stop/<int:camera_index>', methods=['POST'])
def stop_record(camera_index):
    """Stoppt Aufnahme für eine Kamera"""
    success, message = stop_recording(camera_index)
    return {'success': success, 'message': message}


@app.route('/record/status')
def record_status():
    """Gibt Status aller Aufnahmen zurück"""
    status = {}
    for idx, camera in enumerate(found_cameras):
        if idx in recording_status:
            rec = recording_status[idx]
            status[idx] = {
                'recording': rec['recording'],
                'filename': rec['filename'],
                'start_time': rec['start_time'].isoformat()
            }
        else:
            status[idx] = {'recording': False}
    return status


def get_camera_stream(camera_index):
    """Generator für Video-Stream von einer Kamera"""
    if camera_index >= len(found_cameras):
        return
    
    camera = found_cameras[camera_index]
    stream_url = camera.get('stream_url')
    
    if not stream_url:
        return
    
    # Erstelle oder hole Video-Capture
    if camera_index not in video_captures:
        try:
            cap = cv2.VideoCapture(stream_url)
            if not cap.isOpened():
                logger.error(f"Konnte Stream nicht öffnen: {stream_url}")
                return
            video_captures[camera_index] = cap
            capture_locks[camera_index] = threading.Lock()
        except Exception as e:
            logger.error(f"Fehler beim Öffnen des Streams: {e}")
            return
    
    cap = video_captures[camera_index]
    lock = capture_locks[camera_index]
    
    while True:
        with lock:
            ret, frame = cap.read()
            if not ret:
                # Versuche Stream neu zu verbinden
                cap.release()
                try:
                    cap = cv2.VideoCapture(stream_url)
                    if cap.isOpened():
                        video_captures[camera_index] = cap
                        ret, frame = cap.read()
                    else:
                        break
                except:
                    break
            
            if ret:
                # Konvertiere Frame zu JPEG
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ret:
                    frame_bytes = buffer.tobytes()
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        
        time.sleep(0.033)  # ~30 FPS


@app.route('/stream/<int:camera_index>')
def video_stream(camera_index):
    """MJPEG-Stream Endpoint für eine Kamera"""
    return Response(get_camera_stream(camera_index),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


def cleanup_captures():
    """Schließt alle Video-Captures"""
    for idx, cap in video_captures.items():
        try:
            cap.release()
        except:
            pass
    video_captures.clear()
    capture_locks.clear()


def cleanup_recordings():
    """Schließt alle laufenden Aufnahmen sauber"""
    logger.info("Schließe alle laufenden Aufnahmen...")
    for camera_index in list(recording_status.keys()):
        try:
            status = recording_status[camera_index]
            if status['recording']:
                status['recording'] = False
                # Warte kurz, damit Thread sauber beendet wird
                time.sleep(0.5)
                # Schließe Writer explizit
                if 'writer' in status and status['writer'] is not None:
                    try:
                        status['writer'].release()
                        logger.info(f"Aufnahme geschlossen: {status.get('filename', 'unbekannt')}")
                    except:
                        pass
        except Exception as e:
            logger.error(f"Fehler beim Schließen der Aufnahme {camera_index}: {e}")
    
    recording_status.clear()
    recording_locks.clear()


def signal_handler(sig, frame):
    """Handler für sauberes Beenden bei Signalen (SIGINT, SIGTERM)"""
    print("\n" + "=" * 60)
    print("Server wird beendet...")
    print("Schließe alle Aufnahmen sauber, damit Dateien abspielbar bleiben...")
    print("=" * 60)
    logger.info("Beende Anwendung sauber - schließe alle Aufnahmen...")
    
    # Schließe alle Aufnahmen sauber
    cleanup_recordings()
    
    # Schließe alle Video-Captures
    cleanup_captures()
    
    print("✓ Alle Dateien wurden sauber geschlossen.")
    print("=" * 60)
    sys.exit(0)


if __name__ == '__main__':
    import atexit
    
    # Registriere Signal-Handler für sauberes Beenden
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Registriere Cleanup-Funktionen
    atexit.register(cleanup_recordings)
    atexit.register(cleanup_captures)
    
    # Erstelle aufnahmen-Ordner beim Start
    ensure_recordings_dir()
    
    # Starte Cleanup-Worker für automatisches Löschen alter Aufnahmen (24h)
    cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
    cleanup_thread.start()
    logger.info("Cleanup-Worker gestartet: Löscht automatisch Aufnahmen älter als 24 Stunden")
    
    # Führe einmalige Bereinigung beim Start durch
    deleted_count, deleted_size = cleanup_old_recordings(max_age_hours=24)
    if deleted_count > 0:
        print(f"\n✓ Bereinigung beim Start: {deleted_count} alte Dateien gelöscht ({deleted_size/(1024*1024):.1f} MB)")
    
    print("=" * 60)
    print("ONVIF Camera Viewer")
    print("=" * 60)
    print("\nStarte Web-Server auf http://localhost:8080")
    print("\nDie Kameras werden auf Ports 888 und 835 gescannt")
    print("Nur Kameras mit admin/123456 werden angezeigt")
    print("\nAufnahmen werden im Ordner 'aufnahmen' gespeichert")
    print("Format: aufnahmen/YYYY-MM-DD/HH-MM_HH-MM/IP_PORT_YYYY-MM-DD_HH-MM-SS.mp4")
    print("\n⚠️  WICHTIG: Beim Beenden (Ctrl+C) werden alle Dateien sauber geschlossen!")
    print("\nStarte automatischen Scan beim Serverstart...")
    print("=" * 60)
    
    # Automatischer Scan beim Start
    try:
        cameras = scan_network()
        print(f"\n✓ Scan abgeschlossen: {len(cameras)} Kamera(s) gefunden")
        if cameras:
            print("✓ Automatische Aufnahmen gestartet für alle Kameras")
        else:
            print("⚠ Keine Kameras gefunden - bitte manuell scannen über Web-Interface")
    except Exception as e:
        logger.error(f"Fehler beim automatischen Scan: {e}")
        print(f"⚠ Fehler beim automatischen Scan: {e}")
    
    print("\n" + "=" * 60)
    print("Web-Server läuft auf http://localhost:8080")
    print("=" * 60 + "\n")
    
    try:
        # Debug=False verhindert doppeltes Laden des Codes
        app.run(host='0.0.0.0', port=8080, debug=False)
    finally:
        cleanup_captures()

