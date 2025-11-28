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
import tempfile
import platform
import webbrowser
import subprocess
import shutil
import json
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

# Video-Aufnahme Konfiguration
VIDEO_QUALITY = 65  # Qualität für Video-Aufnahmen (0-100, höher = bessere Qualität, größere Datei)

# Konfigurationsdatei
CONFIG_FILE = 'config.json'

# Globale Login-Daten für alle Kameras (werden aus config.json geladen)
camera_username = 'admin'
camera_password = '123456'
credentials_lock = threading.Lock()

# Aufnahme-Einstellungen (werden aus config.json geladen)
record_half_resolution = True  # True = halbierte Auflösung für Aufnahmen (Standard: True)

# FFmpeg Verfügbarkeit
ffmpeg_available = None
ffmpeg_path = None

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
            position: relative;
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
        
        .settings-icon {
            position: absolute;
            top: 0;
            right: 20px;
            font-size: 2em;
            cursor: pointer;
            color: #4CAF50;
            transition: transform 0.3s;
        }
        
        .settings-icon:hover {
            transform: rotate(90deg);
            color: #45a049;
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
        
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.7);
            overflow: auto;
        }
        
        .modal-content {
            background-color: #2a2a2a;
            margin: 10% auto;
            padding: 30px;
            border: 2px solid #4CAF50;
            border-radius: 10px;
            width: 90%;
            max-width: 500px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.5);
            position: relative;
        }
        
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #555;
        }
        
        .modal-header h2 {
            margin: 0;
            color: #4CAF50;
            font-size: 1.5em;
        }
        
        .close {
            color: #aaa;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
            line-height: 1;
            transition: color 0.3s;
        }
        
        .close:hover {
            color: #fff;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #fff;
            font-weight: bold;
            font-size: 1em;
        }
        
        .form-group input {
            width: 100%;
            padding: 12px;
            border: 1px solid #555;
            border-radius: 5px;
            background: #1a1a1a;
            color: #fff;
            font-size: 16px;
            box-sizing: border-box;
        }
        
        .form-group input:focus {
            outline: none;
            border-color: #4CAF50;
        }
        
        .form-actions {
            display: flex;
            gap: 10px;
            justify-content: flex-end;
            margin-top: 25px;
            padding-top: 20px;
            border-top: 1px solid #555;
        }
        
        .btn-secondary {
            background: #666;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            transition: background 0.3s;
        }
        
        .btn-secondary:hover {
            background: #777;
        }
        
        .recordings-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        
        .recording-item {
            background: #333;
            border-radius: 8px;
            padding: 15px;
            border: 1px solid #555;
            transition: border-color 0.3s;
        }
        
        .recording-item:hover {
            border-color: #4CAF50;
        }
        
        .recording-info {
            margin-bottom: 10px;
        }
        
        .recording-info h4 {
            margin: 0 0 5px 0;
            color: #4CAF50;
            font-size: 1em;
        }
        
        .recording-info p {
            margin: 3px 0;
            color: #aaa;
            font-size: 0.85em;
        }
        
        .recording-video {
            width: 100%;
            max-height: 200px;
            border-radius: 5px;
            background: #000;
        }
        
        .recording-actions {
            margin-top: 10px;
            display: flex;
            gap: 10px;
        }
        
        .btn-small {
            padding: 6px 12px;
            font-size: 12px;
        }
        
        .no-recordings {
            text-align: center;
            padding: 40px;
            color: #aaa;
        }
        
        .date-group {
            margin-bottom: 25px;
            border: 1px solid #555;
            border-radius: 8px;
            overflow: hidden;
            background: #2a2a2a;
        }
        
        .date-header {
            background: #333;
            padding: 15px 20px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid #4CAF50;
            transition: background 0.3s;
        }
        
        .date-header:hover {
            background: #3a3a3a;
        }
        
        .date-header h3 {
            margin: 0;
            color: #4CAF50;
            font-size: 1.3em;
        }
        
        .date-content {
            padding: 15px;
        }
        
        .time-group {
            margin-bottom: 20px;
            border: 1px solid #444;
            border-radius: 6px;
            overflow: hidden;
            background: #1f1f1f;
        }
        
        .time-header {
            background: #2a2a2a;
            padding: 12px 15px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #444;
            transition: background 0.3s;
        }
        
        .time-header:hover {
            background: #333;
        }
        
        .time-header h4 {
            margin: 0;
            color: #fff;
            font-size: 1em;
        }
        
        .time-content {
            padding: 15px;
        }
        
        .toggle-icon {
            color: #4CAF50;
            font-size: 0.9em;
            transition: transform 0.3s;
        }
        
        @media (max-width: 768px) {
            .grid {
                grid-template-columns: 1fr;
            }
            
            .settings-icon {
                right: 10px;
                font-size: 1.5em;
            }
            
            .modal-content {
                margin: 5% auto;
                padding: 20px;
                width: 95%;
            }
            
            .modal-header h2 {
                font-size: 1.2em;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <span class="settings-icon" onclick="openSettings()" title="Einstellungen">⚙️</span>
        <h1>📹 ONVIF Camera Viewer</h1>
        <p>Live-Streams aller gefundenen Kameras</p>
    </div>
    
    <!-- Settings Modal -->
    <div id="settingsModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2>⚙️ Kamera-Login Einstellungen</h2>
                <span class="close" onclick="closeSettings()">&times;</span>
            </div>
            <form onsubmit="saveSettings(event)">
                <div class="form-group">
                    <label for="username">Benutzername:</label>
                    <input type="text" id="username" name="username" required>
                </div>
                <div class="form-group">
                    <label for="password">Passwort:</label>
                    <input type="password" id="password" name="password" required>
                </div>
                <div class="form-group">
                    <label style="display: flex; align-items: center; cursor: pointer;">
                        <input type="checkbox" id="halfResolution" name="halfResolution" style="width: auto; margin-right: 10px; cursor: pointer;">
                        <span>Auflösung für Aufnahmen halbieren (kleinere Dateien, weniger Speicher)</span>
                    </label>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn-secondary" onclick="closeSettings()">Abbrechen</button>
                    <button type="submit" class="btn">Speichern & Neu verbinden</button>
                </div>
            </form>
        </div>
    </div>
    
    <div class="controls">
        <button class="btn" onclick="scanCameras()">🔍 Kameras scannen</button>
        <button class="btn" onclick="location.reload()">🔄 Seite aktualisieren</button>
        <button class="btn" onclick="showRecordings()">📁 Aufnahmen anzeigen</button>
    </div>
    
    <!-- Recordings Modal -->
    <div id="recordingsModal" class="modal">
        <div class="modal-content" style="max-width: 900px;">
            <div class="modal-header">
                <h2>📁 Aufnahmen</h2>
                <span class="close" onclick="closeRecordings()">&times;</span>
            </div>
            <div id="recordingsList" style="max-height: 70vh; overflow-y: auto;">
                <div style="text-align: center; padding: 20px; color: #aaa;">
                    Lade Aufnahmen...
                </div>
            </div>
        </div>
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
                        <span id="record-mode-{{ loop.index0 }}" class="record-mode" style="font-size: 0.8em; color: #aaa; margin-left: 10px;"></span>
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
        
        function openSettings() {
            // Lade aktuelle Credentials
            fetch('/api/credentials')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('username').value = data.username || 'admin';
                    document.getElementById('password').value = '';
                    document.getElementById('settingsModal').style.display = 'block';
                })
                .catch(error => {
                    console.error('Fehler beim Laden der Credentials:', error);
                    document.getElementById('settingsModal').style.display = 'block';
                });
        }
        
        function closeSettings() {
            document.getElementById('settingsModal').style.display = 'none';
        }
        
        function saveSettings(event) {
            event.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            const halfResolution = document.getElementById('halfResolution').checked;
            
            fetch('/api/credentials', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    username: username, 
                    password: password,
                    half_resolution: halfResolution
                })
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('Login-Daten gespeichert! Kameras werden neu verbunden...');
                        closeSettings();
                        // Starte neuen Scan mit neuen Credentials
                        scanCameras();
                    } else {
                        alert('Fehler: ' + data.message);
                    }
                })
                .catch(error => {
                    alert('Fehler beim Speichern: ' + error);
                });
        }
        
        // Schließe Modal wenn außerhalb geklickt wird
        window.onclick = function(event) {
            const settingsModal = document.getElementById('settingsModal');
            const recordingsModal = document.getElementById('recordingsModal');
            if (event.target == settingsModal) {
                closeSettings();
            }
            if (event.target == recordingsModal) {
                closeRecordings();
            }
        }
        
        function showRecordings() {
            document.getElementById('recordingsModal').style.display = 'block';
            loadRecordings();
        }
        
        function closeRecordings() {
            document.getElementById('recordingsModal').style.display = 'none';
        }
        
        function loadRecordings() {
            const list = document.getElementById('recordingsList');
            list.innerHTML = '<div style="text-align: center; padding: 20px; color: #aaa;">Lade Aufnahmen...</div>';
            
            fetch('/api/recordings')
                .then(response => response.json())
                .then(data => {
                    if (data.success && data.recordings) {
                        // Prüfe ob Array oder Objekt (gruppiert)
                        const hasRecordings = Array.isArray(data.recordings) 
                            ? data.recordings.length > 0 
                            : Object.keys(data.recordings).length > 0;
                        
                        if (hasRecordings) {
                            displayRecordings(data);
                        } else {
                            list.innerHTML = '<div class="no-recordings"><p>Keine Aufnahmen gefunden</p></div>';
                        }
                    } else {
                        list.innerHTML = '<div class="no-recordings"><p>Keine Aufnahmen gefunden</p></div>';
                    }
                })
                .catch(error => {
                    console.error('Fehler beim Laden der Aufnahmen:', error);
                    list.innerHTML = '<div class="no-recordings"><p>Fehler beim Laden der Aufnahmen</p></div>';
                });
        }
        
        function displayRecordings(data) {
            const list = document.getElementById('recordingsList');
            let html = '';
            
            // Prüfe ob alte Format (Array) oder neues Format (gruppiert)
            if (Array.isArray(data.recordings)) {
                // Fallback für altes Format
                html = '<div class="recordings-grid">';
                data.recordings.forEach(recording => {
                    const date = new Date(recording.timestamp * 1000).toLocaleString('de-DE');
                    html += createRecordingItem(recording, date);
                });
                html += '</div>';
            } else {
                // Neues Format: gruppiert nach Datum und Stunden-Bereich
                const recordings = data.recordings;
                
                for (const date in recordings) {
                    const dateRecordings = recordings[date];
                    const dateObj = new Date(date + 'T00:00:00');
                    const dateFormatted = dateObj.toLocaleDateString('de-DE', { 
                        weekday: 'long', 
                        year: 'numeric', 
                        month: 'long', 
                        day: 'numeric' 
                    });
                    
                    html += `
                        <div class="date-group">
                            <div class="date-header" onclick="toggleDateGroup('${date}')">
                                <h3>📅 ${dateFormatted} (${date})</h3>
                                <span class="toggle-icon" id="toggle-${date}">▼</span>
                            </div>
                            <div class="date-content" id="content-${date}">
                    `;
                    
                    for (const timeRange in dateRecordings) {
                        const timeRecordings = dateRecordings[timeRange];
                        const timeRangeFormatted = timeRange.replace('_', ' - ');
                        
                        html += `
                            <div class="time-group">
                                <div class="time-header" onclick="toggleTimeGroup('${date}-${timeRange}')">
                                    <h4>🕐 ${timeRangeFormatted} Uhr (${timeRecordings.length} Aufnahme${timeRecordings.length !== 1 ? 'n' : ''})</h4>
                                    <span class="toggle-icon" id="toggle-${date}-${timeRange}">▼</span>
                                </div>
                                <div class="time-content" id="content-${date}-${timeRange}">
                                    <div class="recordings-grid">
                        `;
                        
                        timeRecordings.forEach(recording => {
                            const dateTime = new Date(recording.timestamp * 1000).toLocaleString('de-DE');
                            html += createRecordingItem(recording, dateTime);
                        });
                        
                        html += `
                                    </div>
                                </div>
                            </div>
                        `;
                    }
                    
                    html += `
                            </div>
                        </div>
                    `;
                }
            }
            
            list.innerHTML = html;
        }
        
        function createRecordingItem(recording, dateTime) {
            return `
                <div class="recording-item">
                    <div class="recording-info">
                        <h4>${recording.camera || recording.filename}</h4>
                        <p>📅 ${dateTime}</p>
                        <p>💾 ${(recording.size / (1024 * 1024)).toFixed(2)} MB</p>
                    </div>
                    <video class="recording-video" controls preload="metadata">
                        <source src="/api/recordings/play/${encodeURIComponent(recording.filename)}" type="video/mp4">
                        Ihr Browser unterstützt das Video-Tag nicht.
                    </video>
                    <div class="recording-actions">
                        <a href="/api/recordings/download/${encodeURIComponent(recording.filename)}" class="btn btn-small" download>⬇️ Download</a>
                    </div>
                </div>
            `;
        }
        
        function toggleDateGroup(date) {
            const content = document.getElementById(`content-${date}`);
            const toggle = document.getElementById(`toggle-${date}`);
            if (content.style.display === 'none') {
                content.style.display = 'block';
                toggle.textContent = '▼';
            } else {
                content.style.display = 'none';
                toggle.textContent = '▶';
            }
        }
        
        function toggleTimeGroup(id) {
            const content = document.getElementById(`content-${id}`);
            const toggle = document.getElementById(`toggle-${id}`);
            if (content.style.display === 'none') {
                content.style.display = 'block';
                toggle.textContent = '▼';
            } else {
                content.style.display = 'none';
                toggle.textContent = '▶';
            }
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
                        const modeEl = document.getElementById(`record-mode-${idx}`);
                        
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
                            // Zeige Aufnahme-Modus (FFmpeg oder OpenCV)
                            if (modeEl) {
                                if (status.use_ffmpeg) {
                                    modeEl.textContent = '🎤 FFmpeg (mit Audio)';
                                    modeEl.style.color = '#4CAF50';
                                } else {
                                    modeEl.textContent = '📹 OpenCV (ohne Audio)';
                                    modeEl.style.color = '#ff9800';
                                }
                            }
                        } else {
                            if (btn.classList.contains('recording')) {
                                btn.classList.remove('recording');
                                text.textContent = '⏺ Aufnahme starten';
                                statusEl.textContent = '';
                            }
                            if (modeEl) {
                                modeEl.textContent = '';
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


def load_config():
    """Lädt Konfiguration aus config.json"""
    global camera_username, camera_password, record_half_resolution
    
    if not os.path.exists(CONFIG_FILE):
        logger.info("Keine Konfigurationsdatei gefunden, verwende Standardwerte")
        save_config()  # Erstelle Standard-Konfigurationsdatei
        return
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        with credentials_lock:
            camera_username = config.get('username', 'admin')
            camera_password = config.get('password', '123456')
            record_half_resolution = config.get('half_resolution', True)
        
        logger.info(f"Konfiguration geladen: Username={camera_username}, HalfResolution={record_half_resolution}")
    except Exception as e:
        logger.error(f"Fehler beim Laden der Konfiguration: {e}, verwende Standardwerte")
        save_config()  # Erstelle Standard-Konfigurationsdatei bei Fehler


def save_config():
    """Speichert aktuelle Konfiguration in config.json"""
    global camera_username, camera_password, record_half_resolution
    
    try:
        with credentials_lock:
            config = {
                'username': camera_username,
                'password': camera_password,
                'half_resolution': record_half_resolution
            }
        
        # Erstelle Backup der alten Konfiguration falls vorhanden
        if os.path.exists(CONFIG_FILE):
            try:
                backup_file = CONFIG_FILE + '.bak'
                shutil.copy2(CONFIG_FILE, backup_file)
            except:
                pass
        
        # Speichere neue Konfiguration
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Konfiguration gespeichert: Username={camera_username}, HalfResolution={record_half_resolution}")
        return True
    except Exception as e:
        logger.error(f"Fehler beim Speichern der Konfiguration: {e}")
        return False


def check_ffmpeg():
    """Prüft ob FFmpeg verfügbar ist und gibt den Pfad zurück
    Sucht zuerst im System-PATH, dann im lokalen Programmordner"""
    global ffmpeg_available, ffmpeg_path
    
    if ffmpeg_available is not None:
        return ffmpeg_available, ffmpeg_path
    
    # Prüfe ob ffmpeg im PATH verfügbar ist
    ffmpeg_cmd = shutil.which('ffmpeg')
    if ffmpeg_cmd:
        # Teste ob FFmpeg funktioniert
        try:
            result = subprocess.run([ffmpeg_cmd, '-version'], 
                                  capture_output=True, 
                                  timeout=5)
            if result.returncode == 0:
                ffmpeg_available = True
                ffmpeg_path = ffmpeg_cmd
                logger.info(f"FFmpeg gefunden im PATH: {ffmpeg_path}")
                return True, ffmpeg_path
        except:
            pass
    
    # Prüfe lokale FFmpeg-Binaries im Programmordner
    script_dir = os.path.dirname(os.path.abspath(__file__))
    local_ffmpeg_paths = []
    
    # Windows: Prüfe verschiedene mögliche Pfade
    if platform.system() == 'Windows':
        local_ffmpeg_paths = [
            os.path.join(script_dir, 'ffmpeg', 'bin', 'ffmpeg.exe'),
            os.path.join(script_dir, 'ffmpeg', 'ffmpeg.exe'),
            os.path.join(script_dir, 'ffmpeg.exe'),
        ]
    else:
        # macOS/Linux: Prüfe verschiedene mögliche Pfade
        local_ffmpeg_paths = [
            os.path.join(script_dir, 'ffmpeg', 'bin', 'ffmpeg'),
            os.path.join(script_dir, 'ffmpeg', 'ffmpeg'),
            os.path.join(script_dir, 'ffmpeg'),
        ]
    
    # Teste lokale Pfade
    for local_path in local_ffmpeg_paths:
        if os.path.exists(local_path) and os.path.isfile(local_path):
            # Prüfe ob es ausführbar ist (bei Unix)
            if platform.system() != 'Windows':
                if not os.access(local_path, os.X_OK):
                    continue
            
            # Teste ob FFmpeg funktioniert
            try:
                result = subprocess.run([local_path, '-version'], 
                                      capture_output=True, 
                                      timeout=5)
                if result.returncode == 0:
                    ffmpeg_available = True
                    ffmpeg_path = local_path
                    logger.info(f"FFmpeg gefunden im lokalen Ordner: {ffmpeg_path}")
                    return True, ffmpeg_path
            except Exception as e:
                logger.debug(f"Lokaler FFmpeg-Pfad funktioniert nicht: {local_path} - {e}")
                continue
    
    ffmpeg_available = False
    ffmpeg_path = None
    logger.warning("FFmpeg nicht gefunden - Audio-Aufnahme nicht verfügbar")
    logger.info("Hinweis: Sie können FFmpeg-Binaries in den Programmordner legen:")
    if platform.system() == 'Windows':
        logger.info("  - ffmpeg/bin/ffmpeg.exe")
        logger.info("  - ffmpeg/ffmpeg.exe")
        logger.info("  - ffmpeg.exe (direkt im Programmordner)")
    else:
        logger.info("  - ffmpeg/bin/ffmpeg")
        logger.info("  - ffmpeg/ffmpeg")
        logger.info("  - ffmpeg (direkt im Programmordner)")
    return False, None


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


def get_stream_uri(camera, username, password, use_sub_stream=False):
    """Holt die RTSP-Streaming-URL direkt von der ONVIF-Kamera über die Media Service API
    use_sub_stream=True: Wählt das Profil mit der niedrigsten Auflösung (Sub-Stream) für Live-Vorschau
    use_sub_stream=False: Wählt das Profil mit der höchsten Auflösung (Main-Stream) für Aufnahmen"""
    try:
        # Erstelle Media Service (bereits authentifiziert über camera-Objekt)
        media_service = camera.create_media_service()
        
        # Hole alle Profile von der ONVIF-Kamera
        profiles = media_service.GetProfiles()
        
        if not profiles or len(profiles) == 0:
            logger.warning("Keine Profile von ONVIF-Kamera gefunden")
            return None
        
        # Finde das Profil mit der höchsten oder niedrigsten Auflösung je nach use_sub_stream
        best_profile = None
        if use_sub_stream:
            # Suche niedrigste Auflösung (Sub-Stream)
            min_resolution = float('inf')
            for profile in profiles:
                try:
                    video_config = None
                    try:
                        if hasattr(profile, 'VideoEncoderConfiguration') and profile.VideoEncoderConfiguration:
                            video_config_token = profile.VideoEncoderConfiguration.token
                            video_config = media_service.GetVideoEncoderConfiguration({'ConfigurationToken': video_config_token})
                    except Exception as e:
                        logger.debug(f"Konnte VideoEncoderConfiguration nicht holen: {e}")
                        continue
                    
                    if video_config:
                        width = 0
                        height = 0
                        try:
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
                            if resolution < min_resolution:
                                min_resolution = resolution
                                best_profile = profile
                                logger.debug(f"Neues bestes Profil (niedrigste Auflösung) gefunden: {width}x{height} (Auflösung: {resolution})")
                except Exception as e:
                    logger.debug(f"Fehler beim Prüfen des Profils: {e}")
                    continue
            
            if best_profile is None:
                logger.info("Konnte Auflösungen nicht ermitteln, verwende letztes Profil (meist Sub-Stream)")
                best_profile = profiles[-1] if len(profiles) > 1 else profiles[0]
            else:
                logger.info(f"Verwende Profil mit niedrigster Auflösung: {min_resolution} Pixel (Sub-Stream)")
        else:
            # Suche höchste Auflösung (Main-Stream)
            max_resolution = 0
            for profile in profiles:
                try:
                    video_config = None
                    try:
                        if hasattr(profile, 'VideoEncoderConfiguration') and profile.VideoEncoderConfiguration:
                            video_config_token = profile.VideoEncoderConfiguration.token
                            video_config = media_service.GetVideoEncoderConfiguration({'ConfigurationToken': video_config_token})
                    except Exception as e:
                        logger.debug(f"Konnte VideoEncoderConfiguration nicht holen: {e}")
                        continue
                    
                    if video_config:
                        width = 0
                        height = 0
                        try:
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
        # Hole Main-Stream URL per SOAP für Aufnahmen (höchste Auflösung)
        stream_url = get_stream_uri(camera, username, password, use_sub_stream=False)
        
        # Hole Sub-Stream URL per SOAP für Live-Vorschau (niedrigste Auflösung)
        live_stream_url = get_stream_uri(camera, username, password, use_sub_stream=True)
        
        # Wenn keine Stream-URL abgerufen werden konnte, Kamera nicht anzeigen
        if not stream_url:
            logger.debug(f"Keine Stream-URL für {host}:{port} - Kamera wird nicht angezeigt")
            return None
        
        # Verwende Sub-Stream als Fallback für Live-Vorschau falls verfügbar
        if not live_stream_url:
            live_stream_url = stream_url
        
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
            'stream_url': stream_url,  # Main-Stream für Aufnahmen
            'live_stream_url': live_stream_url,  # Sub-Stream für Live-Vorschau
            'device_info': device_info
        }
        
        logger.info(f"✓ Kamera gefunden (SOAP-Auth erfolgreich): {host}:{port} - {device_name}")
        logger.info(f"  Main-Stream (Aufnahme): {stream_url}")
        logger.info(f"  Sub-Stream (Live-Vorschau): {live_stream_url}")
        return camera_info
        
    except Exception as e:
        logger.error(f"Fehler beim Verarbeiten von {host}:{port}: {e}")
        # Bei Fehler Kamera nicht anzeigen
        return None


def scan_network(username=None, password=None, ports=[888, 835]):
    """Scannt das Netzwerk nach ONVIF-Kameras"""
    global found_cameras, scan_in_progress, camera_username, camera_password
    
    # Verwende globale Credentials falls nicht übergeben
    if username is None:
        with credentials_lock:
            username = camera_username
    if password is None:
        with credentials_lock:
            password = camera_password
    
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
            
            # Berechne Aufnahme-Auflösung basierend auf Einstellung
            with credentials_lock:
                use_half_resolution = record_half_resolution
            
            if use_half_resolution:
                recording_width = width // 2
                recording_height = height // 2
                logger.info(f"Aufnahme mit halbierter Auflösung: {recording_width}x{recording_height} (Original: {width}x{height})")
            else:
                recording_width = width
                recording_height = height
            
            # Prüfe ob FFmpeg verfügbar ist
            ffmpeg_avail, _ = check_ffmpeg()
            
            # Initialisiere Aufnahme-Status
            recording_status[camera_index] = {
                'recording': True,
                'writer': None,  # Wird im Thread erstellt (OpenCV)
                'ffmpeg_process': None,  # Wird im Thread erstellt (FFmpeg)
                'filename': filename,
                'cap': cap,
                'start_time': datetime.now(),
                'recording_width': recording_width,
                'recording_height': recording_height,
                'original_width': width,
                'original_height': height,
                'use_ffmpeg': ffmpeg_avail
            }
            recording_locks[camera_index] = threading.Lock()
            
            # Starte Aufnahme-Thread (FFmpeg wenn verfügbar, sonst OpenCV)
            if ffmpeg_avail:
                thread = threading.Thread(target=record_camera_ffmpeg, args=(camera_index,), daemon=True)
                logger.info(f"Aufnahme mit FFmpeg (mit Audio) gestartet für Kamera {camera_index}")
            else:
                thread = threading.Thread(target=record_camera_opencv, args=(camera_index,), daemon=True)
                logger.info(f"Aufnahme mit OpenCV (ohne Audio) gestartet für Kamera {camera_index}")
            thread.start()
            
            logger.info(f"Aufnahme gestartet für Kamera {camera_index}: {filename}")
            return True, filename
            
        except Exception as e:
            logger.error(f"Fehler beim Starten der Aufnahme: {e}")
            return False, str(e)


def record_camera_ffmpeg(camera_index):
    """Aufnahme-Thread für eine Kamera mit FFmpeg (unterstützt Audio)"""
    status = recording_status.get(camera_index)
    if not status:
        return
    
    camera = found_cameras[camera_index]
    stream_url = camera.get('stream_url')
    host = camera.get('host')
    port = camera.get('port')
    
    # Prüfe ob FFmpeg verfügbar ist
    ffmpeg_avail, ffmpeg_cmd = check_ffmpeg()
    if not ffmpeg_avail:
        logger.error("FFmpeg nicht verfügbar - verwende OpenCV ohne Audio")
        # Fallback auf OpenCV
        record_camera_opencv(camera_index)
        return
    
    # Hole Aufnahme-Auflösung aus Status
    recording_width = status.get('recording_width', 1920)
    recording_height = status.get('recording_height', 1080)
    
    # Segmentierung: Neue Datei alle 10 Minuten
    segment_duration = 600  # 10 Minuten in Sekunden
    segment_start_time = datetime.now()
    current_process = None
    current_filename = None
    segment_index = 0
    
    def create_new_segment():
        """Erstellt ein neues Video-Segment mit FFmpeg"""
        nonlocal current_process, current_filename, segment_start_time, segment_index
        
        # Stoppe alte Aufnahme
        if current_process is not None:
            try:
                # Sende 'q' Signal um FFmpeg sauber zu beenden
                # Warte länger damit FFmpeg die Datei vollständig schließen kann
                current_process.stdin.write(b'q\n')
                current_process.stdin.flush()
                current_process.wait(timeout=10)  # Mehr Zeit für sauberes Beenden
            except subprocess.TimeoutExpired:
                # Falls FFmpeg nicht sauber beendet, versuche terminate
                logger.warning(f"FFmpeg beendete sich nicht sauber, verwende terminate")
                try:
                    current_process.terminate()
                    current_process.wait(timeout=5)
                except:
                    try:
                        current_process.kill()
                    except:
                        pass
            except:
                try:
                    current_process.terminate()
                    current_process.wait(timeout=2)
                except:
                    try:
                        current_process.kill()
                    except:
                        pass
            # Prüfe ob Datei existiert und nicht leer ist
            if current_filename and os.path.exists(current_filename):
                file_size = os.path.getsize(current_filename)
                if file_size < 1024:  # Weniger als 1KB = wahrscheinlich korrupt
                    logger.warning(f"Segment-Datei sehr klein ({file_size} bytes), möglicherweise korrupt: {current_filename}")
                else:
                    logger.debug(f"Segment beendet: {current_filename} ({file_size} bytes)")
        
        # Erstelle neue Datei
        current_filename = get_recording_filename(host, port)
        # Füge Segment-Index hinzu falls Datei bereits existiert
        if os.path.exists(current_filename):
            base, ext = os.path.splitext(current_filename)
            current_filename = f"{base}_{segment_index}{ext}"
            segment_index += 1
        
        # FFmpeg-Befehl für RTSP-Aufnahme mit Audio
        # -rtsp_transport tcp: Stabilere Verbindung
        # -i: Input RTSP-Stream
        # -vf scale: Video-Skalierung (falls halbierte Auflösung)
        # -c:v libx264: H.264 Video-Codec
        # -preset medium: Encoding-Geschwindigkeit
        # -crf 23: Qualität (entspricht etwa VIDEO_QUALITY 65)
        # -c:a aac: AAC Audio-Codec
        # -b:a 128k: Audio-Bitrate
        # -f mp4: MP4 Format
        # -movflags +faststart: Schnelleres Abspielen
        # -y: Überschreibe Datei falls vorhanden
        
        ffmpeg_args = [
            ffmpeg_cmd,
            '-rtsp_transport', 'tcp',  # Stabilere RTSP-Verbindung
            '-i', stream_url,
        ]
        
        # Füge Video-Skalierung hinzu falls halbierte Auflösung
        original_width = status.get('original_width', recording_width * 2)
        original_height = status.get('original_height', recording_height * 2)
        if recording_width < original_width or recording_height < original_height:
            # Füge Scale-Filter hinzu
            scale_filter = f'scale={recording_width}:{recording_height}'
            ffmpeg_args.extend(['-vf', scale_filter])
        
        # Video- und Audio-Codec-Einstellungen
        # Verwende fragmentierte MP4s (+empty_moov+default_base_moof) damit Dateien
        # während der Aufnahme abspielbar sind und nicht korrupt werden
        ffmpeg_args.extend([
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',  # Qualität (entspricht etwa VIDEO_QUALITY 65)
            '-c:a', 'aac',
            '-b:a', '128k',
            '-f', 'mp4',
            '-movflags', '+empty_moov+default_base_moof',  # Fragmentierte MP4s - abspielbar während Aufnahme
            '-frag_duration', '1',  # Fragment alle 1 Sekunde für bessere Abspielbarkeit
            '-y',  # Überschreibe Datei
            current_filename
        ])
        
        try:
            # Starte FFmpeg-Prozess
            current_process = subprocess.Popen(
                ffmpeg_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )
            
            segment_start_time = datetime.now()
            status['ffmpeg_process'] = current_process
            status['filename'] = current_filename
            logger.info(f"FFmpeg-Segment gestartet: {current_filename}")
            return True
        except Exception as e:
            logger.error(f"Fehler beim Starten von FFmpeg: {e}")
            return False
    
    # Erstelle erstes Segment
    if not create_new_segment():
        logger.error("Konnte erstes FFmpeg-Segment nicht erstellen")
        return
    
    # Überwache Aufnahme und segmentiere alle 10 Minuten
    while status['recording']:
        try:
            # Prüfe ob Prozess noch läuft
            if current_process.poll() is not None:
                # Prozess beendet (Fehler oder Stream-Ende)
                logger.warning(f"FFmpeg-Prozess beendet (Returncode: {current_process.returncode})")
                # Versuche neu zu verbinden
                time.sleep(2)
                if not create_new_segment():
                    logger.error("Konnte FFmpeg-Segment nach Fehler nicht neu erstellen")
                    break
            
            # Prüfe ob Segment-Wechsel nötig ist
            elapsed = (datetime.now() - segment_start_time).total_seconds()
            if elapsed >= segment_duration:
                logger.info(f"Segment-Wechsel nach {elapsed:.0f}s (10 Minuten)")
                if not create_new_segment():
                    logger.error("Konnte neues Segment nicht erstellen")
                    break
            
            time.sleep(1)  # Prüfe jede Sekunde
            
        except Exception as e:
            logger.error(f"Fehler während FFmpeg-Aufnahme: {e}")
            time.sleep(2)
    
    # Finales Cleanup
    if current_process is not None:
        try:
            current_process.stdin.write(b'q\n')
            current_process.stdin.flush()
            current_process.wait(timeout=10)  # Mehr Zeit für sauberes Beenden
        except subprocess.TimeoutExpired:
            logger.warning(f"FFmpeg beendete sich nicht sauber beim Finalen Cleanup")
            try:
                current_process.terminate()
                current_process.wait(timeout=5)
            except:
                try:
                    current_process.kill()
                except:
                    pass
        except:
            try:
                current_process.terminate()
                current_process.wait(timeout=2)
            except:
                try:
                    current_process.kill()
                except:
                    pass
        
        # Prüfe letzte Datei
        if current_filename and os.path.exists(current_filename):
            file_size = os.path.getsize(current_filename)
            if file_size < 1024:
                logger.warning(f"Letzte Segment-Datei sehr klein ({file_size} bytes), möglicherweise korrupt: {current_filename}")
            else:
                logger.info(f"Letztes Segment geschlossen: {current_filename} ({file_size} bytes)")
    
    logger.info(f"FFmpeg-Aufnahme beendet für Kamera {camera_index}")


def record_camera_opencv(camera_index):
    """Aufnahme-Thread für eine Kamera mit OpenCV (ohne Audio) - Fallback"""
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
    
    # Hole Aufnahme-Auflösung aus Status (wurde in start_recording gesetzt)
    recording_width = status.get('recording_width', width)
    recording_height = status.get('recording_height', height)
    
    # Segmentierung: Neue Datei alle 10 Minuten
    segment_duration = 600  # 10 Minuten in Sekunden
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
                # Teste ob Codec funktioniert - verwende plattformunabhängigen temporären Pfad
                temp_dir = tempfile.gettempdir()
                test_file = os.path.join(temp_dir, f'test_codec_{os.getpid()}.mp4')
                test_writer = cv2.VideoWriter(test_file, test_fourcc, fps, (recording_width, recording_height))
                if test_writer.isOpened():
                    test_writer.release()
                    try:
                        if os.path.exists(test_file):
                            os.remove(test_file)
                    except:
                        pass
                    fourcc = test_fourcc
                    logger.debug(f"H.264 Codec '{codec_name}' funktioniert")
                    break
            except Exception as e:
                logger.debug(f"Codec '{codec_name}' Test fehlgeschlagen: {e}")
                continue
        
        # Fallback auf mp4v falls H.264 nicht verfügbar
        if fourcc is None:
            logger.warning("H.264 Codec nicht verfügbar, verwende mp4v")
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        
        # Erstelle VideoWriter mit Qualitätsparameter und korrekter Aufnahme-Auflösung
        # Versuche Qualitätsparameter zu setzen (nicht alle Codecs unterstützen das)
        try:
            current_writer = cv2.VideoWriter(current_filename, fourcc, fps, (recording_width, recording_height))
            # Setze Qualität aus Konfiguration (0-100, höher = bessere Qualität, größere Datei)
            current_writer.set(cv2.VIDEOWRITER_PROP_QUALITY, VIDEO_QUALITY)
        except:
            # Fallback ohne Qualitätsparameter
            current_writer = cv2.VideoWriter(current_filename, fourcc, fps, (recording_width, recording_height))
        
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
                # Resize Frame falls halbierte Auflösung aktiviert
                if recording_width != width or recording_height != height:
                    frame = cv2.resize(frame, (recording_width, recording_height), interpolation=cv2.INTER_LINEAR)
                
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
                    
                    # Prüfe ob neues Segment nötig ist (nur Zeit)
                    elapsed = (datetime.now() - segment_start_time).total_seconds()
                    
                    if elapsed >= segment_duration:
                        logger.info(f"Segment-Wechsel nach {elapsed:.0f}s (10 Minuten)")
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
    
    # Stoppe FFmpeg-Prozess falls aktiv
    if 'ffmpeg_process' in status and status['ffmpeg_process'] is not None:
        try:
            process = status['ffmpeg_process']
            process.stdin.write(b'q\n')
            process.stdin.flush()
            process.wait(timeout=10)  # Mehr Zeit für sauberes Beenden
        except subprocess.TimeoutExpired:
            logger.warning(f"FFmpeg beendete sich nicht sauber beim Stoppen")
            try:
                process.terminate()
                process.wait(timeout=5)
            except:
                try:
                    process.kill()
                except:
                    pass
        except:
            try:
                process.terminate()
                process.wait(timeout=2)
            except:
                try:
                    process.kill()
                except:
                    pass
    
    # Stoppe OpenCV Writer falls aktiv
    if 'writer' in status and status['writer'] is not None:
        try:
            status['writer'].release()
        except:
            pass
    
    # Schließe Video-Capture
    if 'cap' in status and status['cap'] is not None:
        try:
            status['cap'].release()
        except:
            pass
    
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
                'start_time': rec['start_time'].isoformat(),
                'use_ffmpeg': rec.get('use_ffmpeg', False)  # Zeigt ob FFmpeg oder OpenCV verwendet wird
            }
        else:
            status[idx] = {'recording': False}
    return status


@app.route('/api/credentials', methods=['GET'])
def get_credentials():
    """Gibt aktuelle Login-Daten und Einstellungen zurück"""
    with credentials_lock:
        return {
            'username': camera_username,
            'password': '***',  # Passwort nicht zurückgeben aus Sicherheitsgründen
            'half_resolution': record_half_resolution
        }


@app.route('/api/credentials', methods=['POST'])
def set_credentials():
    """Setzt neue Login-Daten und Einstellungen und verbindet Kameras neu"""
    global camera_username, camera_password, found_cameras, record_half_resolution
    
    try:
        from flask import request
        data = request.get_json()
        
        if not data or 'username' not in data or 'password' not in data:
            return {'success': False, 'message': 'Username und Password erforderlich'}, 400
        
        new_username = data['username'].strip()
        new_password = data['password'].strip()
        
        if not new_username or not new_password:
            return {'success': False, 'message': 'Username und Password dürfen nicht leer sein'}, 400
        
        # Aktualisiere Auflösungseinstellung
        new_half_resolution = data.get('half_resolution', False)
        
        # Stoppe alle laufenden Aufnahmen
        logger.info("Stoppe alle laufenden Aufnahmen vor Credential-Änderung...")
        for camera_index in list(recording_status.keys()):
            try:
                stop_recording(camera_index)
            except:
                pass
        
        # Aktualisiere Credentials und Einstellungen
        with credentials_lock:
            camera_username = new_username
            camera_password = new_password
            record_half_resolution = new_half_resolution
        
        # Speichere Konfiguration persistent
        if not save_config():
            logger.warning("Konnte Konfiguration nicht speichern, Änderungen gelten nur für diese Session")
        
        logger.info(f"Login-Daten aktualisiert: {new_username}")
        logger.info(f"Auflösungseinstellung: {'Halbierte Auflösung' if new_half_resolution else 'Volle Auflösung'}")
        
        # Starte neuen Scan mit neuen Credentials
        logger.info("Starte neuen Scan mit aktualisierten Credentials...")
        try:
            cameras = scan_network(username=new_username, password=new_password)
            logger.info(f"Neuer Scan abgeschlossen: {len(cameras)} Kamera(s) gefunden")
            return {
                'success': True,
                'message': f'Login-Daten aktualisiert. {len(cameras)} Kamera(s) mit neuen Credentials gefunden.'
            }
        except Exception as e:
            logger.error(f"Fehler beim Neuscan: {e}")
            return {
                'success': False,
                'message': f'Credentials gespeichert, aber Fehler beim Neuscan: {str(e)}'
            }
            
    except Exception as e:
        logger.error(f"Fehler beim Setzen der Credentials: {e}")
        return {'success': False, 'message': str(e)}, 500


@app.route('/api/recordings', methods=['GET'])
def get_recordings():
    """Gibt Liste aller Aufnahmen zurück, gruppiert nach Datum und Stunden-Bereich"""
    try:
        aufnahmen_dir = 'aufnahmen'
        if not os.path.exists(aufnahmen_dir):
            return {'success': True, 'recordings': {}}
        
        # Struktur: {date: {time_range: [recordings]}}
        recordings_by_time = {}
        
        # Durchlaufe alle Dateien rekursiv
        for root, dirs, files in os.walk(aufnahmen_dir):
            for file in files:
                if file.endswith('.mp4'):
                    file_path = os.path.join(root, file)
                    try:
                        # Hole Datei-Informationen
                        stat = os.stat(file_path)
                        file_size = stat.st_size
                        file_mtime = stat.st_mtime
                        
                        # Extrahiere Kamera-Info aus Dateinamen (Format: IP_PORT_YYYY-MM-DD_HH-MM-SS.mp4)
                        filename_parts = file.replace('.mp4', '').split('_')
                        camera_info = 'Unbekannt'
                        if len(filename_parts) >= 2:
                            camera_info = f"{filename_parts[0]}:{filename_parts[1]}"
                        
                        # Relativer Pfad für URL (Windows-kompatibel)
                        rel_path = os.path.relpath(file_path, aufnahmen_dir)
                        rel_path = rel_path.replace('\\', '/')  # Windows zu Unix-Pfad
                        
                        # Extrahiere Datum und Stunden-Bereich aus Pfad
                        # Format: aufnahmen/YYYY-MM-DD/HH-MM_HH-MM/filename.mp4
                        path_parts = rel_path.split('/')
                        date_str = 'Unbekannt'
                        time_range = 'Unbekannt'
                        
                        if len(path_parts) >= 3:
                            date_str = path_parts[0]  # YYYY-MM-DD
                            time_range = path_parts[1]  # HH-MM_HH-MM
                        
                        # Initialisiere Struktur falls nötig
                        if date_str not in recordings_by_time:
                            recordings_by_time[date_str] = {}
                        if time_range not in recordings_by_time[date_str]:
                            recordings_by_time[date_str][time_range] = []
                        
                        recordings_by_time[date_str][time_range].append({
                            'filename': rel_path,
                            'path': file_path,
                            'size': file_size,
                            'timestamp': file_mtime,
                            'camera': camera_info
                        })
                    except Exception as e:
                        logger.error(f"Fehler beim Lesen von {file_path}: {e}")
                        continue
        
        # Sortiere innerhalb jeder Gruppe nach Timestamp (neueste zuerst)
        for date in recordings_by_time:
            for time_range in recordings_by_time[date]:
                recordings_by_time[date][time_range].sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Sortiere Datum und Zeit-Bereiche (neueste zuerst)
        sorted_recordings = {}
        for date in sorted(recordings_by_time.keys(), reverse=True):
            sorted_recordings[date] = {}
            for time_range in sorted(recordings_by_time[date].keys(), reverse=True):
                sorted_recordings[date][time_range] = recordings_by_time[date][time_range]
        
        return {'success': True, 'recordings': sorted_recordings}
        
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Aufnahmen: {e}")
        return {'success': False, 'message': str(e)}, 500


@app.route('/api/recordings/play/<path:filename>')
def play_recording(filename):
    """Streamt eine Aufnahme-Datei für Video-Player"""
    try:
        # Sicherheitscheck: Nur Dateien aus aufnahmen-Ordner
        safe_path = os.path.join('aufnahmen', filename)
        safe_path = os.path.normpath(safe_path)
        
        if not safe_path.startswith(os.path.normpath('aufnahmen')):
            return {'error': 'Ungültiger Pfad'}, 403
        
        if not os.path.exists(safe_path):
            return {'error': 'Datei nicht gefunden'}, 404
        
        from flask import send_file
        return send_file(safe_path, mimetype='video/mp4')
        
    except Exception as e:
        logger.error(f"Fehler beim Abspielen der Aufnahme: {e}")
        return {'error': str(e)}, 500


@app.route('/api/recordings/download/<path:filename>')
def download_recording(filename):
    """Lädt eine Aufnahme-Datei herunter"""
    try:
        # Sicherheitscheck: Nur Dateien aus aufnahmen-Ordner
        safe_path = os.path.join('aufnahmen', filename)
        safe_path = os.path.normpath(safe_path)
        
        if not safe_path.startswith(os.path.normpath('aufnahmen')):
            return {'error': 'Ungültiger Pfad'}, 403
        
        if not os.path.exists(safe_path):
            return {'error': 'Datei nicht gefunden'}, 404
        
        from flask import send_file
        return send_file(safe_path, as_attachment=True, download_name=os.path.basename(filename))
        
    except Exception as e:
        logger.error(f"Fehler beim Download der Aufnahme: {e}")
        return {'error': str(e)}, 500


def get_camera_stream(camera_index):
    """Generator für Video-Stream von einer Kamera (verwendet Sub-Stream für Live-Vorschau)"""
    if camera_index >= len(found_cameras):
        return
    
    camera = found_cameras[camera_index]
    # Verwende live_stream_url (Sub-Stream) für Live-Vorschau, Fallback auf stream_url
    stream_url = camera.get('live_stream_url') or camera.get('stream_url')
    
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
                
                # Stoppe FFmpeg-Prozess falls aktiv
                if 'ffmpeg_process' in status and status['ffmpeg_process'] is not None:
                    try:
                        process = status['ffmpeg_process']
                        process.stdin.write(b'q\n')
                        process.stdin.flush()
                        process.wait(timeout=5)
                    except:
                        try:
                            process.terminate()
                            process.wait(timeout=2)
                        except:
                            try:
                                process.kill()
                            except:
                                pass
                
                # Warte kurz, damit Thread sauber beendet wird
                time.sleep(0.5)
                
                # Schließe Writer explizit (OpenCV)
                if 'writer' in status and status['writer'] is not None:
                    try:
                        status['writer'].release()
                        logger.info(f"Aufnahme geschlossen: {status.get('filename', 'unbekannt')}")
                    except:
                        pass
                
                # Schließe Video-Capture
                if 'cap' in status and status['cap'] is not None:
                    try:
                        status['cap'].release()
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
    # Windows unterstützt nur SIGINT, nicht SIGTERM
    signal.signal(signal.SIGINT, signal_handler)
    if platform.system() != 'Windows':
        signal.signal(signal.SIGTERM, signal_handler)
    else:
        # Auf Windows: SIGBREAK als Alternative (falls verfügbar)
        try:
            signal.signal(signal.SIGBREAK, signal_handler)
        except AttributeError:
            pass  # SIGBREAK nicht verfügbar
    
    # Registriere Cleanup-Funktionen
    atexit.register(cleanup_recordings)
    atexit.register(cleanup_captures)
    
    # Erstelle aufnahmen-Ordner beim Start
    ensure_recordings_dir()
    
    # Lade Konfiguration beim Start
    load_config()
    
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
    
    # URL für Dashboard
    dashboard_url = 'http://localhost:8080'
    
    # Öffne Browser nach kurzer Verzögerung (damit Server gestartet ist)
    def open_browser():
        time.sleep(1.5)  # Warte bis Server gestartet ist
        try:
            # webbrowser.open() öffnet automatisch den Standard-Browser
            # und öffnet einen neuen Tab, falls Browser bereits geöffnet ist
            webbrowser.open(dashboard_url)
            print(f"✓ Browser geöffnet: {dashboard_url}")
        except Exception as e:
            print(f"⚠️ Konnte Browser nicht automatisch öffnen: {e}")
            print(f"   Bitte öffnen Sie manuell: {dashboard_url}")
    
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()
    
    try:
        # Debug=False verhindert doppeltes Laden des Codes
        app.run(host='0.0.0.0', port=8080, debug=False)
    finally:
        cleanup_captures()

