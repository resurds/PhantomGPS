import sys
import re
import json
import math
import subprocess
import multiprocessing
multiprocessing.freeze_support()  # Required for PyInstaller --onefile on Windows
import urllib.request
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QStatusBar, QFrame,
    QMessageBox, QComboBox, QSlider, QButtonGroup, QRadioButton
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtCore import Qt, QUrl, QThread, pyqtSignal, QTimer, QObject, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel

PYTHON = sys.executable


# ── Tunnel Manager ─────────────────────────────────────────────────────────────

class TunnelManager(QThread):
    tunnel_ready  = pyqtSignal(str, int)
    tunnel_failed = pyqtSignal(str)
    tunnel_log    = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._proc = None
        self.rsd_host = None
        self.rsd_port = None

    def run(self):
        try:
            self._proc = subprocess.Popen(
                [PYTHON, "-m", "pymobiledevice3", "lockdown", "start-tunnel"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            for line in self._proc.stdout:
                line = line.rstrip()
                self.tunnel_log.emit(line)
                m = re.search(r'--rsd\s+(\S+)\s+(\d+)', line)
                if m:
                    self.rsd_host = m.group(1)
                    self.rsd_port = int(m.group(2))
                    self.tunnel_ready.emit(self.rsd_host, self.rsd_port)
        except Exception as e:
            self.tunnel_failed.emit(str(e))

    def stop(self):
        if self._proc:
            try: self._proc.terminate()
            except: pass


# ── Device Monitor ─────────────────────────────────────────────────────────────

class DeviceMonitor(QThread):
    device_connected    = pyqtSignal(str)
    device_disconnected = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._running = True
        self._last_udid = None

    def run(self):
        while self._running:
            try:
                r = subprocess.run(["idevice_id", "-l"], capture_output=True, text=True, timeout=3)
                udids = [u.strip() for u in r.stdout.strip().splitlines() if u.strip()]
                if udids:
                    if udids[0] != self._last_udid:
                        self._last_udid = udids[0]
                        self.device_connected.emit(udids[0])
                else:
                    if self._last_udid is not None:
                        self._last_udid = None
                        self.device_disconnected.emit()
            except: pass
            self.msleep(2000)

    def stop(self): self._running = False


# ── Route Fetcher ──────────────────────────────────────────────────────────────

class RouteFetcher(QThread):
    route_ready  = pyqtSignal(list)   # list of (lat, lng)
    route_failed = pyqtSignal(str)

    def __init__(self, start_lat, start_lng, end_lat, end_lng):
        super().__init__()
        self.start_lat = start_lat
        self.start_lng = start_lng
        self.end_lat   = end_lat
        self.end_lng   = end_lng

    def run(self):
        try:
            url = (
                f"http://router.project-osrm.org/route/v1/foot/"
                f"{self.start_lng},{self.start_lat};"
                f"{self.end_lng},{self.end_lat}"
                f"?overview=full&geometries=geojson"
            )
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            coords = data["routes"][0]["geometry"]["coordinates"]
            # OSRM returns [lng, lat] — flip to (lat, lng)
            points = [(c[1], c[0]) for c in coords]
            self.route_ready.emit(points)
        except Exception as e:
            self.route_failed.emit(str(e))


# ── Map Bridge ─────────────────────────────────────────────────────────────────

class MapBridge(QObject):
    location_selected = pyqtSignal(float, float, str)   # lat, lng, marker_type

    @pyqtSlot(float, float, str)
    def on_map_click(self, lat, lng, marker_type):
        self.location_selected.emit(lat, lng, marker_type)


# ── Main Window ────────────────────────────────────────────────────────────────

class GPSSpoofWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_udid   = None
        self.selected_lat   = 51.5074
        self.selected_lng   = -0.1278
        self.dest_lat       = None
        self.dest_lng       = None
        self.spoofing_active = False
        self.walk_mode      = False
        self.route_points   = []
        self.walk_index     = 0
        self.rsd_host       = None
        self.rsd_port       = None
        self.tunnel_manager = None

        # Spoof timer (instant mode: 5s, walk mode: dynamic)
        self.loop_timer = QTimer()
        self.loop_timer.timeout.connect(self._tick)

        self._init_ui()
        self._start_device_monitor()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _init_ui(self):
        self.setWindowTitle("PhantomGPS — iOS Location Spoofer")
        self.setMinimumSize(1150, 740)
        self.setStyleSheet(STYLESHEET)
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        self.map_view = self._build_map()
        root.addWidget(self.map_view, stretch=1)
        self.status_bar = QStatusBar()
        self.status_bar.setObjectName("statusBar")
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Connect your iPhone via USB to begin.")

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(310)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(20, 24, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(self._lbl("⟨ PhantomGPS ⟩", "appTitle"))
        layout.addWidget(self._lbl("iOS USB Location Spoofer", "appSubtitle"))
        layout.addWidget(self._divider())

        # Device + tunnel
        layout.addWidget(self._section_label("DEVICE"))
        self.device_label = self._lbl("No device connected", "deviceLabel")
        self.device_label.setWordWrap(True)
        layout.addWidget(self.device_label)

        layout.addWidget(self._section_label("TUNNEL"))
        self.tunnel_label = self._lbl("Not started", "tunnelLabel")
        self.tunnel_label.setWordWrap(True)
        layout.addWidget(self.tunnel_label)

        layout.addWidget(self._divider())

        # Mode selector
        layout.addWidget(self._section_label("MODE"))
        mode_row = QHBoxLayout()
        self.mode_instant = QRadioButton("📍 Instant")
        self.mode_walk    = QRadioButton("🚶 Walk Route")
        self.mode_instant.setChecked(True)
        self.mode_instant.setObjectName("modeBtn")
        self.mode_walk.setObjectName("modeBtn")
        self.mode_instant.toggled.connect(self._on_mode_change)
        mode_row.addWidget(self.mode_instant)
        mode_row.addWidget(self.mode_walk)
        layout.addLayout(mode_row)

        # Walk speed (hidden until walk mode selected)
        self.speed_frame = QFrame()
        speed_layout = QVBoxLayout(self.speed_frame)
        speed_layout.setContentsMargins(0, 0, 0, 0)
        speed_layout.setSpacing(4)
        speed_layout.addWidget(self._section_label("WALK SPEED"))
        speed_row = QHBoxLayout()
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setMinimum(1)
        self.speed_slider.setMaximum(20)
        self.speed_slider.setValue(5)
        self.speed_slider.setObjectName("speedSlider")
        self.speed_slider.valueChanged.connect(self._on_speed_change)
        self.speed_label = self._lbl("5 km/h", "speedLabel")
        speed_row.addWidget(self.speed_slider)
        speed_row.addWidget(self.speed_label)
        speed_layout.addLayout(speed_row)

        # Destination coords (walk mode)
        dest_layout = QVBoxLayout()
        dest_layout.setSpacing(4)
        dest_layout.addWidget(self._section_label("DESTINATION"))
        dest_lat_row = QHBoxLayout()
        dest_lat_row.addWidget(QLabel("Lat"))
        self.dest_lat_input = QLineEdit("click map →")
        self.dest_lat_input.setObjectName("coordInput")
        self.dest_lat_input.setReadOnly(True)
        dest_lat_row.addWidget(self.dest_lat_input)
        dest_layout.addLayout(dest_lat_row)
        dest_lng_row = QHBoxLayout()
        dest_lng_row.addWidget(QLabel("Lng"))
        self.dest_lng_input = QLineEdit("click map →")
        self.dest_lng_input.setObjectName("coordInput")
        self.dest_lng_input.setReadOnly(True)
        dest_lng_row.addWidget(self.dest_lng_input)
        dest_layout.addLayout(dest_lng_row)
        speed_layout.addLayout(dest_layout)

        self.speed_frame.setVisible(False)
        layout.addWidget(self.speed_frame)

        layout.addWidget(self._divider())

        # Coordinates (instant mode)
        self.coords_frame = QFrame()
        coords_layout = QVBoxLayout(self.coords_frame)
        coords_layout.setContentsMargins(0, 0, 0, 0)
        coords_layout.setSpacing(4)
        coords_layout.addWidget(self._section_label("COORDINATES"))
        lat_row = QHBoxLayout()
        lat_row.addWidget(QLabel("Lat"))
        self.lat_input = QLineEdit(str(self.selected_lat))
        self.lat_input.setObjectName("coordInput")
        lat_row.addWidget(self.lat_input)
        coords_layout.addLayout(lat_row)
        lng_row = QHBoxLayout()
        lng_row.addWidget(QLabel("Lng"))
        self.lng_input = QLineEdit(str(self.selected_lng))
        self.lng_input.setObjectName("coordInput")
        lng_row.addWidget(self.lng_input)
        coords_layout.addLayout(lng_row)

        # Presets
        coords_layout.addWidget(self._section_label("QUICK LOCATIONS"))
        self.preset_combo = QComboBox()
        self.preset_combo.setObjectName("presetCombo")
        for name, _, _ in PRESETS:
            self.preset_combo.addItem(name)
        self.preset_combo.currentIndexChanged.connect(self._on_preset)
        coords_layout.addWidget(self.preset_combo)
        layout.addWidget(self.coords_frame)

        layout.addWidget(self._divider())

        # Buttons
        self.spoof_btn = QPushButton("▶  START SPOOFING")
        self.spoof_btn.setObjectName("spoofBtn")
        self.spoof_btn.setFixedHeight(48)
        self.spoof_btn.clicked.connect(self._toggle_spoof)
        layout.addWidget(self.spoof_btn)

        reset_btn = QPushButton("↺  Reset Location")
        reset_btn.setObjectName("resetBtn")
        reset_btn.clicked.connect(self._reset_location)
        layout.addWidget(reset_btn)

        layout.addWidget(self._divider())
        layout.addWidget(self._section_label("HOW TO USE"))
        help_text = self._lbl(
            "Instant: click map → Start Spoofing\n\n"
            "Walk: switch mode, set start on map\n"
            "(right-click = destination), then\n"
            "press Start — GPS walks the route!", "helpText"
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        layout.addStretch()
        layout.addWidget(self._lbl("v3.0  |  pymobiledevice3 + OSRM", "versionLabel"))
        return sidebar

    def _build_map(self):
        view = QWebEngineView()
        view.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        self.bridge = MapBridge()
        self.bridge.location_selected.connect(self._on_map_click)
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        view.page().setWebChannel(self.channel)
        view.setHtml(self._map_html(), QUrl("about:blank"))
        return view

    def _map_html(self):
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0d1117}}
#map{{width:100vw;height:100vh}}
.start-marker{{background:#00ffe0;border-radius:50%;border:3px solid #fff;box-shadow:0 0 12px #00ffe0}}
.dest-marker{{background:#ff4560;border-radius:50%;border:3px solid #fff;box-shadow:0 0 12px #ff4560}}
.walk-marker{{background:#f0b429;border-radius:50%;border:2px solid #fff;box-shadow:0 0 8px #f0b429}}
.leaflet-control-attribution{{display:none}}
#hint{{position:absolute;bottom:16px;left:50%;transform:translateX(-50%);
  background:rgba(13,17,23,0.85);color:#6e7681;font-family:monospace;
  font-size:11px;padding:6px 14px;border-radius:20px;z-index:1000;
  border:1px solid #21262d;pointer-events:none}}
</style></head><body>
<div id="map"></div>
<div id="hint">Left-click = set start &nbsp;|&nbsp; Right-click = set destination</div>
<script>
var map = L.map('map').setView([{self.selected_lat},{self.selected_lng}],15);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',{{maxZoom:19}}).addTo(map);

var startIcon = L.divIcon({{className:'start-marker',iconSize:[18,18],iconAnchor:[9,9]}});
var destIcon  = L.divIcon({{className:'dest-marker', iconSize:[18,18],iconAnchor:[9,9]}});
var walkIcon  = L.divIcon({{className:'walk-marker', iconSize:[12,12],iconAnchor:[6,6]}});

var startMarker = L.marker([{self.selected_lat},{self.selected_lng}],{{icon:startIcon,draggable:true}}).addTo(map);
startMarker.bindPopup('<b>Start / Current</b>');
var destMarker  = null;
var walkMarker  = null;
var routeLine   = null;

var bridge = null;
new QWebChannel(qt.webChannelTransport,function(ch){{bridge=ch.objects.bridge;}});

function send(lat,lng,type){{if(bridge)bridge.on_map_click(lat,lng,type);}}

// Left click = start position
map.on('click',function(e){{
  startMarker.setLatLng(e.latlng);
  send(e.latlng.lat,e.latlng.lng,'start');
}});

// Right click = destination
map.on('contextmenu',function(e){{
  if(!destMarker){{
    destMarker=L.marker(e.latlng,{{icon:destIcon,draggable:true}}).addTo(map);
    destMarker.bindPopup('<b>Destination</b>').openPopup();
    destMarker.on('dragend',function(){{
      var p=destMarker.getLatLng();
      send(p.lat,p.lng,'dest');
    }});
  }} else {{
    destMarker.setLatLng(e.latlng);
  }}
  send(e.latlng.lat,e.latlng.lng,'dest');
}});

startMarker.on('dragend',function(){{
  var p=startMarker.getLatLng();
  send(p.lat,p.lng,'start');
}});

function moveMarker(lat,lng){{
  startMarker.setLatLng([lat,lng]);
  map.setView([lat,lng],map.getZoom());
}}

function drawRoute(points){{
  if(routeLine)map.removeLayer(routeLine);
  routeLine=L.polyline(points,{{color:'#00ffe0',weight:4,opacity:0.7,dashArray:'8 4'}}).addTo(map);
  map.fitBounds(routeLine.getBounds(),{{padding:[40,40]}});
}}

function moveWalkMarker(lat,lng){{
  if(!walkMarker){{
    walkMarker=L.marker([lat,lng],{{icon:walkIcon}}).addTo(map);
  }} else {{
    walkMarker.setLatLng([lat,lng]);
  }}
  map.panTo([lat,lng],{{animate:true,duration:0.5}});
}}

function clearRoute(){{
  if(routeLine){{map.removeLayer(routeLine);routeLine=null;}}
  if(walkMarker){{map.removeLayer(walkMarker);walkMarker=null;}}
}}
</script></body></html>"""

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _lbl(self, text, obj):
        l = QLabel(text); l.setObjectName(obj); return l

    def _divider(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine); f.setObjectName("divider"); return f

    def _section_label(self, text):
        return self._lbl(text, "sectionLabel")

    # ── Mode ───────────────────────────────────────────────────────────────────

    def _on_mode_change(self):
        self.walk_mode = self.mode_walk.isChecked()
        self.speed_frame.setVisible(self.walk_mode)
        self.coords_frame.setVisible(not self.walk_mode)
        if not self.walk_mode:
            self.map_view.page().runJavaScript("clearRoute();")

    def _on_speed_change(self, val):
        self.speed_label.setText(f"{val} km/h")

    # ── Map events ─────────────────────────────────────────────────────────────

    def _on_map_click(self, lat, lng, marker_type):
        if marker_type == 'start':
            self.selected_lat = round(lat, 6)
            self.selected_lng = round(lng, 6)
            if not self.walk_mode:
                self.lat_input.setText(str(self.selected_lat))
                self.lng_input.setText(str(self.selected_lng))
            self.status_bar.showMessage(f"Start: {self.selected_lat}, {self.selected_lng}")
        elif marker_type == 'dest':
            self.dest_lat = round(lat, 6)
            self.dest_lng = round(lng, 6)
            self.dest_lat_input.setText(str(self.dest_lat))
            self.dest_lng_input.setText(str(self.dest_lng))
            self.status_bar.showMessage(f"Destination set: {self.dest_lat}, {self.dest_lng} — fetching route...")
            self._fetch_route()

    def _on_preset(self, index):
        if 0 <= index < len(PRESETS):
            _, lat, lng = PRESETS[index]
            self.selected_lat = lat; self.selected_lng = lng
            self.lat_input.setText(str(lat)); self.lng_input.setText(str(lng))
            self.map_view.page().runJavaScript(f"moveMarker({lat},{lng});")

    # ── Route ──────────────────────────────────────────────────────────────────

    def _fetch_route(self):
        if self.dest_lat is None:
            return
        self.status_bar.showMessage("Fetching walking route from OpenStreetMap...")
        fetcher = RouteFetcher(
            self.selected_lat, self.selected_lng,
            self.dest_lat, self.dest_lng
        )
        fetcher.route_ready.connect(self._on_route_ready)
        fetcher.route_failed.connect(self._on_route_failed)
        fetcher.start()
        self._route_fetcher = fetcher  # keep reference

    def _on_route_ready(self, points):
        self.route_points = points
        self.walk_index = 0
        js_points = str([[p[0], p[1]] for p in points])
        self.map_view.page().runJavaScript(f"drawRoute({js_points});")
        dist = self._route_distance_km(points)
        speed = self.speed_slider.value()
        mins = (dist / speed) * 60
        self.status_bar.showMessage(
            f"Route ready — {dist:.2f} km, ~{mins:.0f} min at {speed} km/h. Press Start Spoofing!"
        )

    def _on_route_failed(self, error):
        self.status_bar.showMessage(f"Route fetch failed: {error}. Check internet connection.")

    def _route_distance_km(self, points):
        total = 0.0
        for i in range(1, len(points)):
            total += self._haversine(points[i-1], points[i])
        return total

    def _haversine(self, p1, p2):
        R = 6371.0
        lat1, lng1 = math.radians(p1[0]), math.radians(p1[1])
        lat2, lng2 = math.radians(p2[0]), math.radians(p2[1])
        dlat = lat2 - lat1; dlng = lng2 - lng1
        a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlng/2)**2
        return R * 2 * math.asin(math.sqrt(a))

    # ── Spoofing ───────────────────────────────────────────────────────────────

    def _toggle_spoof(self):
        if not self.current_udid:
            QMessageBox.warning(self, "No Device", "Please connect your iPhone via USB first.")
            return
        if not self.rsd_host:
            QMessageBox.warning(self, "Tunnel Not Ready", "Tunnel is still starting. Please wait.")
            return
        if self.walk_mode and not self.route_points:
            QMessageBox.warning(self, "No Route", "Right-click the map to set a destination first.")
            return
        self._stop_spoof() if self.spoofing_active else self._start_spoof()

    def _start_spoof(self):
        self._read_coords()
        self.spoofing_active = True
        self.walk_index = 0
        self.spoof_btn.setText("⏹  STOP SPOOFING")
        self.spoof_btn.setObjectName("spoofBtnActive")
        self.spoof_btn.setStyle(self.spoof_btn.style())

        if self.walk_mode:
            interval = self._walk_interval_ms()
            self.loop_timer.start(interval)
        else:
            self.loop_timer.start(5000)

        self._tick()

    def _stop_spoof(self):
        self.loop_timer.stop()
        self.spoofing_active = False
        self.spoof_btn.setText("▶  START SPOOFING")
        self.spoof_btn.setObjectName("spoofBtn")
        self.spoof_btn.setStyle(self.spoof_btn.style())
        self.status_bar.showMessage("Spoofing stopped.")

    def _tick(self):
        if self.walk_mode and self.route_points:
            if self.walk_index >= len(self.route_points):
                self._stop_spoof()
                self.status_bar.showMessage("✓ Arrived at destination!")
                return
            lat, lng = self.route_points[self.walk_index]
            self.selected_lat = lat
            self.selected_lng = lng
            self.map_view.page().runJavaScript(f"moveWalkMarker({lat},{lng});")
            self.walk_index += 1
            pct = int((self.walk_index / len(self.route_points)) * 100)
            self.status_bar.showMessage(
                f"Walking… {pct}% — step {self.walk_index}/{len(self.route_points)}"
            )
            # Update interval dynamically based on speed
            self.loop_timer.setInterval(self._walk_interval_ms())
        else:
            self.status_bar.showMessage(f"Spoofing → {self.selected_lat}, {self.selected_lng}")

        self._send_location(self.selected_lat, self.selected_lng)

    def _walk_interval_ms(self):
        """Calculate ms between steps based on speed and point spacing."""
        speed_kmh = self.speed_slider.value()
        speed_ms  = speed_kmh * 1000 / 3600   # m/s
        if len(self.route_points) > 1 and self.walk_index < len(self.route_points) - 1:
            idx = min(self.walk_index, len(self.route_points) - 2)
            dist_m = self._haversine(
                self.route_points[idx], self.route_points[idx + 1]
            ) * 1000
            interval = max(200, int((dist_m / speed_ms) * 1000))
        else:
            interval = 1000
        return interval

    def _reset_location(self):
        if not self.rsd_host: return
        self._stop_spoof()
        try:
            subprocess.run(
                [PYTHON, "-m", "pymobiledevice3", "developer", "dvt",
                 "simulate-location", "stop", "--rsd", self.rsd_host, str(self.rsd_port)],
                capture_output=True, timeout=10
            )
            self.status_bar.showMessage("Location reset to real GPS.")
        except Exception as e:
            self.status_bar.showMessage(f"Reset failed: {e}")

    def _send_location(self, lat, lng):
        if not self.rsd_host: return
        try:
            subprocess.Popen(
                [PYTHON, "-m", "pymobiledevice3", "developer", "dvt",
                 "simulate-location", "set",
                 "--rsd", self.rsd_host, str(self.rsd_port),
                 "--", str(lat), str(lng)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
        except Exception as e:
            self.status_bar.showMessage(f"Send failed: {e}")

    def _read_coords(self):
        try:
            self.selected_lat = float(self.lat_input.text())
            self.selected_lng = float(self.lng_input.text())
        except ValueError: pass

    # ── Device / Tunnel ────────────────────────────────────────────────────────

    def _start_device_monitor(self):
        self.monitor = DeviceMonitor()
        self.monitor.device_connected.connect(self._on_device_connected)
        self.monitor.device_disconnected.connect(self._on_device_disconnected)
        self.monitor.start()

    def _on_device_connected(self, udid):
        self.current_udid = udid
        self.device_label.setText(f"✓ iPhone connected\n{udid[:8]}...")
        self.device_label.setObjectName("deviceLabelConnected")
        self.device_label.setStyle(self.device_label.style())
        self.status_bar.showMessage("Device connected — starting tunnel...")
        self._start_tunnel()

    def _on_device_disconnected(self):
        self.current_udid = None
        self.rsd_host = None; self.rsd_port = None
        self._stop_spoof(); self._stop_tunnel()
        self.device_label.setText("No device connected")
        self.device_label.setObjectName("deviceLabel")
        self.device_label.setStyle(self.device_label.style())
        self.tunnel_label.setText("Not started")
        self.tunnel_label.setObjectName("tunnelLabel")
        self.tunnel_label.setStyle(self.tunnel_label.style())
        self.status_bar.showMessage("Device disconnected.")

    def _start_tunnel(self):
        self._stop_tunnel()
        self.tunnel_label.setText("⏳ Starting tunnel...")
        self.tunnel_manager = TunnelManager()
        self.tunnel_manager.tunnel_ready.connect(self._on_tunnel_ready)
        self.tunnel_manager.tunnel_failed.connect(self._on_tunnel_failed)
        self.tunnel_manager.tunnel_log.connect(self._on_tunnel_log)
        self.tunnel_manager.start()

    def _stop_tunnel(self):
        if self.tunnel_manager:
            self.tunnel_manager.stop()
            self.tunnel_manager = None

    def _on_tunnel_ready(self, host, port):
        self.rsd_host = host; self.rsd_port = port
        self.tunnel_label.setText(f"✓ Tunnel ready\n{host}:{port}")
        self.tunnel_label.setObjectName("tunnelLabelConnected")
        self.tunnel_label.setStyle(self.tunnel_label.style())
        self.status_bar.showMessage("Tunnel ready — click the map and press Start Spoofing!")

    def _on_tunnel_failed(self, error):
        self.tunnel_label.setText("✗ Tunnel failed")
        self.status_bar.showMessage(f"Tunnel error: {error}")

    def _on_tunnel_log(self, line):
        if "ERROR" in line or "INFO" in line:
            self.status_bar.showMessage(line[:100])

    def closeEvent(self, event):
        self._stop_tunnel()
        self.monitor.stop(); self.monitor.wait()
        event.accept()


# ── Presets ────────────────────────────────────────────────────────────────────

PRESETS = [
    ("— Select a city —", 51.5074, -0.1278),
    ("London, UK", 51.5074, -0.1278),
    ("New York, USA", 40.7128, -74.0060),
    ("Paris, France", 48.8566, 2.3522),
    ("Tokyo, Japan", 35.6762, 139.6503),
    ("Sydney, Australia", -33.8688, 151.2093),
    ("Dubai, UAE", 25.2048, 55.2708),
    ("Los Angeles, USA", 34.0522, -118.2437),
    ("Berlin, Germany", 52.5200, 13.4050),
    ("Singapore", 1.3521, 103.8198),
]


# ── Stylesheet ─────────────────────────────────────────────────────────────────

STYLESHEET = """
QMainWindow, QWidget { background:#0d1117; color:#c9d1d9; font-family:'Consolas','Courier New',monospace; font-size:13px; }
#sidebar { background:#161b22; border-right:1px solid #21262d; }
#appTitle { font-size:18px; font-weight:bold; color:#00ffe0; letter-spacing:1px; }
#appSubtitle { font-size:11px; color:#6e7681; }
#sectionLabel { font-size:10px; color:#6e7681; letter-spacing:2px; margin-top:2px; }
#divider { color:#21262d; background:#21262d; max-height:1px; }
#deviceLabel, #tunnelLabel { color:#8b949e; font-size:12px; }
#deviceLabelConnected, #tunnelLabelConnected { color:#00ffe0; font-size:12px; }
#modeBtn { color:#c9d1d9; font-size:13px; }
#modeBtn::indicator { width:14px; height:14px; }
#modeBtn::indicator:checked { background:#00ffe0; border-radius:7px; border:2px solid #0d1117; }
#modeBtn::indicator:unchecked { background:#21262d; border-radius:7px; border:2px solid #30363d; }
#coordInput { background:#0d1117; border:1px solid #30363d; border-radius:4px; color:#00ffe0; padding:4px 8px; font-family:'Consolas',monospace; }
#coordInput:focus { border-color:#00ffe0; }
#presetCombo { background:#0d1117; border:1px solid #30363d; border-radius:4px; color:#c9d1d9; padding:4px; }
#presetCombo::drop-down { border:none; }
#speedSlider::groove:horizontal { background:#21262d; height:4px; border-radius:2px; }
#speedSlider::handle:horizontal { background:#00ffe0; width:14px; height:14px; margin:-5px 0; border-radius:7px; }
#speedSlider::sub-page:horizontal { background:#00ffe0; height:4px; border-radius:2px; }
#speedLabel { color:#00ffe0; font-size:12px; min-width:55px; }
#spoofBtn { background:#00ffe0; color:#0d1117; border:none; border-radius:6px; font-weight:bold; font-size:14px; letter-spacing:1px; }
#spoofBtn:hover { background:#00ccb4; }
#spoofBtnActive { background:#ff4560; color:#fff; border:none; border-radius:6px; font-weight:bold; font-size:14px; letter-spacing:1px; }
#spoofBtnActive:hover { background:#cc2040; }
#resetBtn { background:transparent; color:#8b949e; border:1px solid #30363d; border-radius:6px; padding:6px; }
#resetBtn:hover { border-color:#8b949e; color:#c9d1d9; }
#helpText { color:#6e7681; font-size:11px; line-height:1.6; }
#versionLabel { color:#30363d; font-size:10px; }
QStatusBar#statusBar { background:#010409; color:#6e7681; font-size:11px; border-top:1px solid #21262d; }
QLabel { color:#8b949e; }
"""


# ── Entry ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("PhantomGPS")
    window = GPSSpoofWindow()
    window.show()
    sys.exit(app.exec())
