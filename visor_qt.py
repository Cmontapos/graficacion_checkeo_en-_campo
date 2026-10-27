#!/usr/bin/env python3
"""Visor rápido de CSV MicroGas con pyqtgraph: mapa OpenStreetMap a la izquierda, gráficas enlazadas a la derecha."""
from __future__ import annotations

import argparse
import datetime
import io
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

import graficar as g
import mapa_calor as mc

pg.setConfigOptions(imageAxisOrder='row-major', antialias=False, background='w', foreground='#1b1f24')

WORLD = 2 * math.pi * 6378137.0
ANIM_SECONDS = 8  # duracion de la animacion del recorrido
PROVIDERS = {
    'OpenStreetMap': ('osm', 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', '© OpenStreetMap contributors', 19),
    'Satélite (Esri)': ('esri', 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 'Esri, Maxar, Earthstar Geographics', 18),
}
X_LABELS = {'fecha': 'Fecha y hora', 'transcurrido': 'Tiempo transcurrido (s)', 'indice': 'Número de muestra'}
COVER_CELLS = (0.5, 1, 2, 5, 10, 25, 50, 100, 250)
MM_PER_PX = 0.26  # tamano del punto del visor (px) -> QGIS (mm)
SMOOTH = (('sin suavizar', 0.0), ('suavizado 1 celda', 1.0), ('suavizado 2 celdas', 2.0), ('suavizado 3 celdas', 3.0))
CACHE = Path.home() / '.cache' / 'gaslab_tiles'


def fetch_tile(provider, z, x, y):
    """RGB uint8 array of one tile (disk cached), or None when offline."""
    name, url = provider[:2]
    file = CACHE / name / str(z) / str(x) / f'{y}.png'
    try:
        from PIL import Image
        if file.exists():
            data = file.read_bytes()
        else:
            import requests
            reply = requests.get(url.format(z=z, x=x, y=y), timeout=8, headers={'User-Agent': 'GasLab-graficacion/1.0 (local CSV viewer)'})
            reply.raise_for_status()
            data = reply.content
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        return np.asarray(Image.open(io.BytesIO(data)).convert('RGB'))
    except Exception:
        return None


HUE_180 = np.array([[-0.574, 1.430, 0.144], [0.426, 0.430, 0.144], [0.426, 1.430, -0.856]])


def night_tile(image, name):
    """Dark version of a map tile: invert + rotate hue (like the usual CSS dark-map filter); satellite is only dimmed."""
    if name == 'esri':
        return (image * 0.7).astype(np.uint8)
    inverted = 255 - image.astype(np.float32)
    return np.clip(inverted @ HUE_180.T * 0.92, 0, 255).astype(np.uint8)


class TileLayer(QtCore.QObject):
    """Loads the tiles needed for the visible area (in a thread pool) and places them in a ViewBox."""
    ready = QtCore.Signal(object)

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.provider = PROVIDERS['OpenStreetMap']
        self.items, self.pending, self.failed = {}, set(), set()
        self.pool = ThreadPoolExecutor(6)
        self.night = False
        self.ready.connect(self._place)

    def set_provider(self, name):
        self.provider = PROVIDERS[name]
        for item in self.items.values():
            self.view.removeItem(item)
        self.items, self.pending, self.failed = {}, set(), set()
        self.update()

    def set_night(self, flag):
        self.night = flag
        self.set_provider(next(n for n, v in PROVIDERS.items() if v is self.provider))

    def update(self):
        (x0, x1), (y0, y1) = self.view.viewRange()
        width = max(1, self.view.width())
        if x1 <= x0 or not np.isfinite(x1 - x0):
            return
        z = int(np.clip(round(math.log2(WORLD / (256 * (x1 - x0) / width))), 1, self.provider[3]))  # sobre el maximo se amplia el ultimo nivel
        while True:
            n = 2 ** z
            tx0, tx1 = (int(np.clip(math.floor((v + WORLD / 2) / WORLD * n), 0, n - 1)) for v in (x0, x1))
            ty0, ty1 = (int(np.clip(math.floor((WORLD / 2 - v) / WORLD * n), 0, n - 1)) for v in (y1, y0))
            if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) <= 64 or z <= 1:
                break
            z -= 1
        self.z = z
        provider = self.provider
        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                key = (provider[0], z, tx, ty)
                if key in self.items or key in self.pending or key in self.failed:
                    continue
                self.pending.add(key)
                self.pool.submit(self._load, key, provider)

    def _load(self, key, provider):
        self.ready.emit((key, fetch_tile(provider, *key[1:])))

    def _place(self, result):
        key, image = result
        self.pending.discard(key)
        name, z, tx, ty = key
        if name != self.provider[0]:
            return
        if image is None:
            self.failed.add(key)
            return
        n = 2 ** z
        size = WORLD / n
        if self.night:
            image = night_tile(image, name)
        item = pg.ImageItem(np.ascontiguousarray(image[::-1]), levels=(0, 255), autoLevels=False)
        item.setRect(QtCore.QRectF(tx * size - WORLD / 2, WORLD / 2 - (ty + 1) * size, size, size))
        item.setZValue(-1000 + z)
        self.view.addItem(item)
        self.items[key] = item
        if len(self.items) > 220:
            for old in [k for k in self.items if abs(k[1] - getattr(self, 'z', z)) > 1][:60]:
                self.view.removeItem(self.items.pop(old))


class Data:
    """Numeric arrays of a CSV, already sorted by time (see graficar.load_csv)."""

    def __init__(self, frame, time_column, zone, unit, variables=None):
        self.frame, self.time_column = frame, time_column  # para exportar el tramo a Excel
        self.n = len(frame)
        self.vars = variables or [c for c in g.numeric_columns(frame) if c not in g.DRONE_GPS]
        self.y = {c: g.numeric(frame[c]).to_numpy(dtype=float) for c in self.vars}
        self.x = {'indice': np.arange(1, self.n + 1, dtype=float)}
        self.utc = None
        try:
            local, _, dates = g.time_axis(frame, 'fecha', time_column, zone, unit)
            wall = (local.dt.tz_localize(None) - pd.Timestamp('1970-01-01')).dt.total_seconds()
            self.x['fecha'] = wall.to_numpy(dtype=float)
            self.x['transcurrido'] = g.time_axis(frame, 'transcurrido', time_column, zone, unit)[0].to_numpy(dtype=float)
            self.utc = dates.dt.strftime('%Y-%m-%d %H:%M:%S').fillna('').to_numpy()
        except ValueError:
            pass
        self.modes = [m for m in ('fecha', 'transcurrido', 'indice') if m in self.x]
        self.has_gps = False
        self.gps = {}  # 'datos' (receptor) y, si el CSV trae latitud_dron/longitud_dron, 'dron' (solo esas posiciones)
        try:
            self.gps['datos'] = self._gps_set(frame)
            if all(c in frame for c in g.DRONE_GPS):
                try:
                    self.gps['dron'] = self._gps_set(g.use_drone_gps(frame))
                except ValueError:
                    pass  # el CSV trae las columnas pero sin ninguna posicion del dron
            self.set_gps('datos')
            self.has_gps = True
        except (ValueError, StopIteration):
            pass

    @staticmethod
    def _gps_set(frame):
        segments, _ = g.gps_segments(frame)
        lat_col = next(c for c in g.LAT_COLUMNS if c in frame)
        lon_col = next(c for c in g.LON_COLUMNS if c in frame)
        lat, lon = g.numeric(frame[lat_col]), g.numeric(frame[lon_col])
        ok = g.gps_valid(lat, lon).to_numpy()
        lat = np.where(ok, lat.to_numpy(dtype=float), np.nan)
        lon = np.where(ok, lon.to_numpy(dtype=float), np.nan)
        mx, my = g._mercator(lon, lat)
        route_x, route_y = [], []
        for segment in segments:
            sx, sy = g._mercator(np.array([p[2] for p in segment]), np.array([p[1] for p in segment]))
            route_x += list(sx) + [np.nan]
            route_y += list(sy) + [np.nan]
        return lat, lon, mx, my, (np.array(route_x), np.array(route_y))

    def set_gps(self, name):
        self.gps_name = name
        self.lat, self.lon, self.mx, self.my, self.route = self.gps[name]


def fmt(v):
    if v is None or not np.isfinite(v):
        return '—'
    return f'{v:.1f}' if abs(v) >= 1000 else f'{v:.2f}' if abs(v) >= 10 else f'{v:.3f}'


def viridis_stops():
    cmap = pg.colormap.get('viridis')
    return cmap, ', '.join(f'stop:{t:.2f} rgb({r},{gg},{b})' for t, (r, gg, b, _) in zip(np.linspace(0, 1, 6), cmap.map(np.linspace(0, 1, 6), mode='byte')))


class Viewer(QtWidgets.QMainWindow):
    def __init__(self, zone=g.DEFAULT_ZONE, unit='auto', only_new=False):
        super().__init__()
        self.setWindowTitle('GasLab · Visor rápido')
        self.zone, self.unit, self.only_new = zone, unit, only_new
        self.data = None
        self.plots, self.selected, self.big = [], [], None
        self.xmode, self.range = 'fecha', None
        self.days, self.hours, self.intervals = {}, {}, []
        self.window = None  # (i0, i1): tramo elegido; limita el mapa y la ampliacion de las graficas
        self._building = False
        self.anim = None  # (indices a recorrer, instante de inicio) mientras corre la animacion del recorrido
        self.anim_timer = QtCore.QTimer(self, interval=33, timeout=self.anim_step)
        self.path = None
        self.settings = QtCore.QSettings('GasLab', 'VisorRapido')
        self.fontsize = int(self.settings.value('fontsize', 12))
        self.night = str(self.settings.value('night', 'false')).lower() == 'true'
        self.muted = '#262c33'
        self._build_ui()
        self.apply_font()
        self.apply_theme()
        self.range_timer = QtCore.QTimer(singleShot=True, interval=60, timeout=self.on_range)
        self.tile_timer = QtCore.QTimer(singleShot=True, interval=150, timeout=lambda: self.tiles.update())

    # ---------- interface ----------
    def _build_ui(self):
        bar = self.addToolBar('Controles')
        bar.setMovable(False)
        bar.addAction('Abrir CSV…', self.open_dialog)
        bar.addSeparator()
        bar.addWidget(QtWidgets.QLabel(' Eje X '))
        self.xbox = QtWidgets.QComboBox()
        self.xbox.currentTextChanged.connect(self.on_xmode)
        bar.addWidget(self.xbox)
        bar.addWidget(QtWidgets.QLabel('  Mapa '))
        self.base = QtWidgets.QComboBox()
        self.base.addItems(list(PROVIDERS))
        self.base.currentTextChanged.connect(lambda n: (self.tiles.set_provider(n), self.attribution.setText('Mapa: ' + PROVIDERS[n][2])))
        bar.addWidget(self.base)
        self.gps_label = QtWidgets.QLabel('  GPS ')
        self.gpsbox = QtWidgets.QComboBox()
        self.gpsbox.addItem('Datos (receptor)', 'datos')
        self.gpsbox.addItem('Dron', 'dron')
        self.gpsbox.currentIndexChanged.connect(self.on_gps)
        self.gps_actions = [bar.addWidget(self.gps_label), bar.addWidget(self.gpsbox)]  # una barra oculta/muestra por la accion
        for action in self.gps_actions:
            action.setVisible(False)
        bar.addWidget(QtWidgets.QLabel('  Color de la ruta '))
        self.colorbox = QtWidgets.QComboBox()
        self.colorbox.currentTextChanged.connect(self.recolor)
        bar.addWidget(self.colorbox)
        self.fity = QtWidgets.QCheckBox('Ajustar Y al tramo')
        self.fity.setChecked(True)
        self.fity.toggled.connect(lambda _: self.on_range())
        bar.addWidget(self.fity)
        self.addToolBarBreak()
        bar = self.addToolBar('Intervalo')
        bar.setMovable(False)
        bar.addWidget(QtWidgets.QLabel(' Inactividad > '))
        self.gapbox = QtWidgets.QSpinBox()
        self.gapbox.setRange(1, 86400)
        self.gapbox.setValue(1200)
        self.gapbox.setSuffix(' s')
        self.gapbox.setToolTip('Una pausa mayor a este tiempo entre dos muestras divide la medición en otro tramo')
        self.gapbox.valueChanged.connect(self.compute_intervals)
        bar.addWidget(self.gapbox)
        bar.addWidget(QtWidgets.QLabel(' Tramo '))
        self.intervalbox = QtWidgets.QComboBox()
        self.intervalbox.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self.intervalbox.setToolTip('Tramos continuos de la medición; limita las gráficas y el mapa al tramo elegido')
        self.intervalbox.currentIndexChanged.connect(self.on_interval)
        bar.addWidget(self.intervalbox)
        bar.addAction('Todo', self.clear_window)
        self.anim_action = bar.addAction('▶ Animar recorrido', self.toggle_anim)
        bar.addAction('Exportar PNG…', self.export_png)
        self.addToolBarBreak()
        bar = self.addToolBar('Vista')
        bar.setMovable(False)
        bar.addWidget(QtWidgets.QLabel(' Día '))
        self.daybox = QtWidgets.QComboBox()
        self.daybox.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self.daybox.setToolTip('Días con mediciones; elige uno para ampliar las gráficas a ese día')
        self.daybox.currentIndexChanged.connect(self.on_day)
        bar.addWidget(self.daybox)
        bar.addWidget(QtWidgets.QLabel(' de '))
        self.hfrom = QtWidgets.QComboBox()
        self.hfrom.setToolTip('Hora de inicio (solo horas con mediciones del día elegido)')
        self.hfrom.currentIndexChanged.connect(self.on_hour_from)
        bar.addWidget(self.hfrom)
        bar.addWidget(QtWidgets.QLabel(' a '))
        self.hto = QtWidgets.QComboBox()
        self.hto.setToolTip('Hora de fin')
        self.hto.currentIndexChanged.connect(self.on_hour_to)
        bar.addWidget(self.hto)
        bar.addSeparator()
        bar.addWidget(QtWidgets.QLabel(' Letra '))
        self.fontbox = QtWidgets.QSpinBox()
        self.fontbox.setRange(8, 28)
        self.fontbox.setValue(self.fontsize)
        self.fontbox.setSuffix(' pt')
        self.fontbox.valueChanged.connect(self.set_fontsize)
        bar.addWidget(self.fontbox)
        bar.addSeparator()
        self.nightbox = QtWidgets.QCheckBox('Modo noche')
        self.nightbox.setChecked(self.night)
        self.nightbox.toggled.connect(self.set_night)
        bar.addWidget(self.nightbox)
        bar.addAction('Restablecer zoom', self.reset_zoom)
        bar.addAction('Exportar Excel…', self.export_excel)
        self.addToolBarBreak()
        self._build_heat_bar()
        self.info = QtWidgets.QLabel('Abre un CSV. Clic en una gráfica para ampliarla; Esc para volver.')
        self.statusBar().addWidget(self.info, 1)

        self.split = QtWidgets.QSplitter()
        self.setCentralWidget(self.split)
        # map
        left = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(left)
        lay.setContentsMargins(0, 0, 0, 0)
        self.mapw = pg.GraphicsLayoutWidget()
        self.view = self.mapw.addViewBox(lockAspect=True, enableMenu=False)
        self.view.setMouseEnabled(True, True)
        lay.addWidget(self.mapw, 1)
        self.legend = QtWidgets.QLabel()
        self.attribution = QtWidgets.QLabel('Mapa: ' + PROVIDERS['OpenStreetMap'][2])
        self.attribution.setStyleSheet('color:#5b6570;font-size:10px')
        lay.addWidget(self.legend)
        self.cover_legend = QtWidgets.QLabel()
        self.cover_legend.setWordWrap(True)
        self.cover_legend.hide()
        lay.addWidget(self.cover_legend)
        lay.addWidget(self.attribution)
        self.left = left
        self.tiles = TileLayer(self.view)
        self.view.sigRangeChanged.connect(lambda *_: self.tile_timer.start())
        self.mapw.scene().sigMouseMoved.connect(self.on_map_move)
        # plots
        self.glw = pg.GraphicsLayoutWidget()
        self.plot_scroll = QtWidgets.QScrollArea()
        self.plot_scroll.setWidgetResizable(True)
        self.plot_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.plot_scroll.setWidget(self.glw)
        self.glw.scene().sigMouseMoved.connect(self.on_plot_move)
        self.tip = QtWidgets.QLabel(self.glw)
        self.tip.setStyleSheet('background:rgba(255,255,255,235);border:1px solid #888;border-radius:5px;padding:5px 8px;color:#1b1f24')
        self.tip.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.tip.hide()
        self.glw.viewport().installEventFilter(self)
        self.glw.scene().sigMouseClicked.connect(self.on_plot_click)
        self.split.addWidget(left)
        self.split.addWidget(self.plot_scroll)
        self.split.setChildrenCollapsible(False)
        left.setMinimumWidth(250)
        self.plot_scroll.setMinimumWidth(300)
        self.split.setSizes([500, 700])
        self.split.setStretchFactor(0, 2)
        self.split.setStretchFactor(1, 3)
        # variables dock
        self.varlist = QtWidgets.QListWidget()
        self.varlist.itemChanged.connect(self.on_var_toggle)
        dock = QtWidgets.QDockWidget('Variables')
        box = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(box)
        row = QtWidgets.QHBoxLayout()
        for text, state in (('Todas', True), ('Ninguna', False)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(lambda _=False, s=state: self.set_all(s))
            row.addWidget(b)
        v.addLayout(row)
        v.addWidget(self.varlist)
        dock.setWidget(box)
        box.setMaximumWidth(190)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)
        self.dock = dock
        # map layers
        self.route = pg.PlotDataItem(pen=pg.mkPen('#7a8591', width=2), connect='finite')
        self.cover = pg.ImageItem()
        self.cover.hide()
        self.view.addItem(self.cover)
        self.cover.setZValue(-50)  # after addItem (ViewBox resets it): above the tiles, below the route
        self.cover_grid = None
        self.heat_points = pg.ScatterPlotItem(pen=None)  # modo Puntos del mapa de calor: una muestra = un punto de color
        self.heat_points.hide()
        self.heat_pts = None
        self.points = pg.ScatterPlotItem(size=6, pen=None)
        self.highlight = pg.PlotDataItem(pen=pg.mkPen('#ff7f0e', width=5), connect='finite')
        self.map_cursor = pg.ScatterPlotItem(size=16, brush=pg.mkBrush('w'), pen=pg.mkPen('k', width=2))
        self.ends = []
        for emoji in (g.START_ICON, g.END_ICON):
            badge = pg.TextItem(emoji, anchor=(0.5, 0.5), fill=pg.mkBrush(255, 255, 255, 235), border=pg.mkPen('#333', width=2))
            badge.setFont(QtGui.QFont('Noto Color Emoji', 16))
            badge.setColor('#000000')
            self.ends.append(badge)
        for z, item in enumerate((self.route, self.points, self.heat_points, self.highlight, self.map_cursor, *self.ends)):
            item.setZValue(z)
            self.view.addItem(item)

    def _build_heat_bar(self):
        """Mapa de calor: cobertura (cantidad de muestras) o una variable georreferenciada por celdas (mapa_calor.py)."""
        bar = self.addToolBar('Mapa de calor')
        bar.setMovable(False)
        self.coverbox = QtWidgets.QCheckBox('Mapa de calor')
        self.coverbox.setToolTip('Divide el mapa en celdas y colorea cada una según las muestras que caen en ella')
        self.coverbox.toggled.connect(self.update_coverage)
        bar.addWidget(self.coverbox)
        bar.addWidget(QtWidgets.QLabel(' Valor '))
        self.heatvar = QtWidgets.QComboBox()
        self.heatvar.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self.heatvar.setToolTip('Muestras = cobertura (% de las muestras por celda); o la variable a georreferenciar')
        self.heatvar.addItem('Muestras (cobertura)', None)
        self.heatvar.currentIndexChanged.connect(self.update_coverage)
        bar.addWidget(self.heatvar)
        self.drawbox = QtWidgets.QComboBox()
        self.drawbox.addItem('Puntos', 'puntos')
        self.drawbox.addItem('Celdas', 'celdas')
        self.drawbox.setToolTip('Puntos: cada muestra en su coordenada, coloreada por su valor. Celdas: el valor agrupado por celdas')
        self.drawbox.currentIndexChanged.connect(self.update_coverage)
        bar.addWidget(self.drawbox)
        self.sizebox = QtWidgets.QSpinBox()
        self.sizebox.setRange(2, 30)
        self.sizebox.setValue(7)
        self.sizebox.setSuffix(' px')
        self.sizebox.setToolTip('Tamaño de los puntos (en QGIS se exporta proporcional, en mm)')
        self.sizebox.valueChanged.connect(self.update_coverage)
        bar.addWidget(self.sizebox)
        self.statbox = QtWidgets.QComboBox()
        for key in ('media', 'maximo', 'p95'):
            self.statbox.addItem(mc.STATS[key], key)
        self.statbox.setToolTip('Qué valor toma cada celda a partir de las muestras que caen en ella')
        self.statbox.currentIndexChanged.connect(self.update_coverage)
        bar.addWidget(self.statbox)
        self.cellbox = QtWidgets.QComboBox()
        for meters in COVER_CELLS:
            self.cellbox.addItem(f'celda {meters:g} m', meters)
        self.cellbox.setCurrentIndex(COVER_CELLS.index(25))
        self.cellbox.currentIndexChanged.connect(self.update_coverage)
        bar.addWidget(self.cellbox)
        self.smoothbox = QtWidgets.QComboBox()
        for text, sigma in SMOOTH:
            self.smoothbox.addItem(text, sigma)
        self.smoothbox.setToolTip('Reparte cada valor con un núcleo gaussiano; solo se dibuja hasta ~2 veces el suavizado desde la ruta')
        self.smoothbox.currentIndexChanged.connect(self.update_coverage)
        bar.addWidget(self.smoothbox)
        bar.addWidget(QtWidgets.QLabel(' Desfase '))
        self.lagbox = QtWidgets.QDoubleSpinBox()
        self.lagbox.setRange(0, 120)
        self.lagbox.setDecimals(1)
        self.lagbox.setSuffix(' s')
        self.lagbox.setToolTip('Retraso del sensor: el valor registrado en t se coloca donde estaba el equipo en t − desfase')
        self.lagbox.valueChanged.connect(self.update_coverage)
        bar.addWidget(self.lagbox)
        bar.addWidget(QtWidgets.QLabel(' Válido de '))
        self.vmin, self.vmax = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        for box, tip in ((self.vmin, 'mínimo'), (self.vmax, 'máximo')):
            box.setPlaceholderText(tip)
            box.setMaximumWidth(80)
            box.setToolTip(f'Valor {tip} válido de la variable; los valores fuera de rango se ignoran (vacío = sin límite)')
            box.editingFinished.connect(self.update_coverage)
        bar.addWidget(self.vmin)
        bar.addWidget(QtWidgets.QLabel(' a '))
        bar.addWidget(self.vmax)
        bar.addAction('Exportar GeoTIFF/QGIS…', self.export_heat)

    # ---------- loading ----------
    def open_dialog(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Abrir CSV', g.documents_dir(), 'CSV (*.csv)')
        if path:
            self.load(path)

    def load(self, path, columns=None, time_column=None):
        self.stop_anim()
        try:
            frame = g.load_csv(path, self.only_new, time_column or g.TIME_COLUMNS[0], self.unit)
            time_column = g.find_time_column(frame, time_column) or str(frame.columns[0])
            if not any(c in frame for c in g.LAT_COLUMNS):
                frame = self.ask_gps_columns(frame)
            self.data = Data(frame, time_column, self.zone, self.unit)
            self.full_data, self.dron_data = self.data, None  # dron_data: solo las filas con posicion del dron (se crea al elegirlo)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, 'No se pudo cargar', str(exc))
            return
        self.path = path
        data = self.data
        self.setWindowTitle(f'GasLab · {g.short_name(path)}')
        self.varlist.blockSignals(True)
        self.varlist.clear()
        default = [c for c in (columns or ()) if c in data.vars] or [c for c in ('co2_ppm', 'temperatura_c', 'humedad_pct', 'pm2_5') if c in data.vars] \
            or [c for c in data.vars if c not in g.GPS_NAMES][:4] or data.vars[:1]
        for name in data.vars:
            item = QtWidgets.QListWidgetItem(name)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if name in default else QtCore.Qt.Unchecked)
            item.setForeground(pg.mkColor(self.color_of(name)))
            self.varlist.addItem(item)
        self.varlist.blockSignals(False)
        self.selected = [c for c in data.vars if c in default]
        self.xbox.blockSignals(True)
        self.xbox.clear()
        self.xbox.addItems([X_LABELS[m] for m in data.modes])
        self.xbox.blockSignals(False)
        self.xmode = data.modes[0]
        self.colorbox.blockSignals(True)
        self.colorbox.clear()
        self.colorbox.addItems(['(un solo color)'] + data.vars)
        self.colorbox.setCurrentText('co2_ppm' if 'co2_ppm' in data.vars else (default[0] if default else '(un solo color)'))
        self.colorbox.blockSignals(False)
        self.heatvar.blockSignals(True)
        self.heatvar.clear()
        self.heatvar.addItem('Muestras (cobertura)', None)
        for name in data.vars:
            if name not in g.GPS_NAMES:
                self.heatvar.addItem(name, name)
        self.heatvar.setCurrentIndex(max(self.heatvar.findData('co2_ppm'), 0))
        self.heatvar.blockSignals(False)
        self.range, self.big, self.window = None, None, None
        self.left.setVisible(data.has_gps)
        for action in self.gps_actions:
            action.setVisible('dron' in data.gps)
        self.gpsbox.blockSignals(True)
        self.gpsbox.setCurrentIndex(0)
        self.gpsbox.blockSignals(False)
        self.build_map()
        self.build_plots()
        self.compute_days()
        self.compute_intervals()
        self.info.setText(f'{data.n:,} filas · {len(self.days)} días · {g.short_name(path)}')

    def ask_gps_columns(self, frame):
        """CSV sin columnas de GPS con nombre conocido: el usuario elige cuáles son la latitud y la longitud (o sigue sin mapa)."""
        values = {c: g.numeric(frame[c]) for c in frame.columns}
        lat_like = [c for c, v in values.items() if v.notna().any() and v.dropna().between(-90, 90).all()]
        lon_like = [c for c, v in values.items() if v.notna().any() and v.dropna().between(-180, 180).all()]
        if not lat_like or len(lon_like) < 2:
            return frame
        picks = []
        for label, options, hint in (('latitud', lat_like, 'lat'), ('longitud', lon_like, 'lon')):
            options = [c for c in options if c not in picks]
            guess = next((i for i, c in enumerate(options) if hint in c.lower()), 0)
            name, ok = QtWidgets.QInputDialog.getItem(
                self, 'Columnas de GPS', f'No se reconocieron columnas de GPS.\nElige la columna de {label} (grados decimales)\no Cancelar para abrir sin mapa:', options, guess, False)
            if not ok:
                return frame
            picks.append(name)
        return frame.assign(latitud=values[picks[0]], longitud=values[picks[1]])

    def color_of(self, name):
        color = g.PALETTE[self.data.vars.index(name) % len(g.PALETTE)] if self.data else '#007f86'
        if self.night:  # lighten for contrast on a dark background
            rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
            color = '#' + ''.join(f'{int(c + (255 - c) * 0.4):02x}' for c in rgb)
        return color

    def apply_theme(self):
        night = self.night
        app = QtWidgets.QApplication.instance()
        app.setStyle('Fusion')
        if night:
            palette = QtGui.QPalette()
            for role, value in ((QtGui.QPalette.Window, '#1b2026'), (QtGui.QPalette.WindowText, '#e6e9ee'), (QtGui.QPalette.Base, '#14181d'),
                                (QtGui.QPalette.AlternateBase, '#1b2026'), (QtGui.QPalette.Text, '#e6e9ee'), (QtGui.QPalette.Button, '#262d35'),
                                (QtGui.QPalette.ButtonText, '#e6e9ee'), (QtGui.QPalette.Highlight, '#007f86'), (QtGui.QPalette.HighlightedText, '#ffffff'),
                                (QtGui.QPalette.ToolTipBase, '#262d35'), (QtGui.QPalette.ToolTipText, '#e6e9ee'), (QtGui.QPalette.PlaceholderText, '#7d8794')):
                palette.setColor(role, QtGui.QColor(value))
            for role in (QtGui.QPalette.Text, QtGui.QPalette.ButtonText, QtGui.QPalette.WindowText):
                palette.setColor(QtGui.QPalette.Disabled, role, QtGui.QColor('#7d8794'))
            app.setPalette(palette)
        else:
            app.setPalette(app.style().standardPalette())
        background, foreground = ('#14181d', '#e6e9ee') if night else ('w', '#1b1f24')
        pg.setConfigOptions(background=background, foreground=foreground)
        self.glw.setBackground(background)
        self.mapw.setBackground(background)
        self.muted = '#d3d9e0' if night else '#262c33'
        self.cursor_color = '#d0d5db' if night else '#555'
        self.tip.setStyleSheet(('background:rgba(27,32,38,240);border:1px solid #7d8794;color:#e6e9ee;' if night else
                                'background:rgba(255,255,255,235);border:1px solid #888;color:#1b1f24;') + 'border-radius:5px;padding:5px 8px')
        self.attribution.setStyleSheet(f'color:{self.muted};font-size:{max(self.fontsize - 2, 7)}pt')
        # los botones de las barras (acciones) se dibujan planos por defecto: relieve, borde y relleno para verlos como botones
        base, border, hover, press, text = ('#2f3943', '#6b7886', '#3b4854', '#222a32', '#e6e9ee') if night else ('#eef2f5', '#8a97a3', '#d6e8ea', '#bcd6d9', '#1b1f24')
        self.setStyleSheet(f'QToolBar QToolButton {{ background:{base}; color:{text}; border:1px solid {border}; border-radius:5px; padding:2px 8px; margin:1px 2px }}'
                           f'QToolBar QToolButton:hover {{ background:{hover}; border-color:#007f86 }}'
                           f'QToolBar QToolButton:pressed {{ background:{press} }}')
        self.tiles.set_night(night)

    def set_night(self, flag):
        self.night = bool(flag)
        self.settings.setValue('night', 'true' if flag else 'false')
        self.apply_theme()
        if self.data:
            for i in range(self.varlist.count()):
                item = self.varlist.item(i)
                item.setForeground(pg.mkColor(self.color_of(item.text())))
            self.build_plots()

    # ---------- map ----------
    def build_map(self):
        d = self.data
        if not d.has_gps:
            return
        if self.window is None:
            self.route.setData(*d.route)
            inside = np.ones(d.n, bool)
        else:
            i0, i1 = self.window
            inside = np.zeros(d.n, bool)
            inside[i0:i1 + 1] = True
            x, y = d.mx[i0:i1 + 1], d.my[i0:i1 + 1]
            t = d.x.get('fecha', d.x.get('transcurrido'))
            if t is not None and len(x) > 1:  # la ruta no une puntos separados por una pausa larga
                cut = np.flatnonzero(np.diff(t[i0:i1 + 1]) > self.gapbox.value()) + 1
                x, y = np.insert(x, cut, np.nan), np.insert(y, cut, np.nan)
            self.route.setData(x, y)
        valid = np.flatnonzero(np.isfinite(d.mx) & inside)
        self.valid_pts = valid
        keep = valid[np.linspace(0, len(valid) - 1, min(len(valid), 4000)).astype(int)] if len(valid) else valid
        self.marker_idx = np.unique(keep)
        self.recolor()
        self.update_coverage()
        for badge in self.ends:
            badge.setVisible(len(valid) > 0)
        if not len(valid):
            self.map_cursor.setData([], [])
            return
        for badge, i in zip(self.ends, (valid[0], valid[-1])):
            badge.setPos(d.mx[i], d.my[i])
        mx, my = d.mx[valid], d.my[valid]
        pad_x = max((mx.max() - mx.min()) * 0.12, 60)
        pad_y = max((my.max() - my.min()) * 0.12, 60)
        self.view.setRange(xRange=(mx.min() - pad_x, mx.max() + pad_x), yRange=(my.min() - pad_y, my.max() + pad_y), padding=0)
        self.tile_timer.start()

    def toggle_anim(self):
        """Recorre de inicio a fin las muestras con posicion (las del tramo elegido) en ANIM_SECONDS: el mapa dibuja la ruta recorrida y las graficas siguen al cursor."""
        if self.anim:
            self.stop_anim()
            return
        idx = getattr(self, 'valid_pts', [])
        if self.data is None or not self.data.has_gps or len(idx) < 2:
            return
        self.anim = (idx, time.monotonic())
        self.anim_action.setText('■ Detener animación')
        self.anim_timer.start()

    def anim_step(self):
        idx, t0 = self.anim
        progress = min((time.monotonic() - t0) / ANIM_SECONDS, 1.0)
        k = int(progress * (len(idx) - 1))
        d = self.data
        x, y = d.mx[idx[:k + 1]], d.my[idx[:k + 1]]
        t = d.x.get('fecha', d.x.get('transcurrido'))
        if t is not None and len(x) > 1:  # la estela no une vuelos o tramos separados por una pausa larga
            cut = np.flatnonzero(np.diff(t[idx[:k + 1]]) > self.gapbox.value()) + 1
            x, y = np.insert(x, cut, np.nan), np.insert(y, cut, np.nan)
        self.highlight.setData(x, y)
        self.set_cursor(int(idx[k]))
        if progress >= 1.0:
            self.stop_anim()

    def stop_anim(self):
        running = self.anim is not None
        self.anim_timer.stop()
        self.anim = None
        self.anim_action.setText('▶ Animar recorrido')
        if running:
            self.on_range()  # devuelve el resaltado del mapa a lo que marcan las graficas

    def on_gps(self, *_):
        self.stop_anim()
        """Datos: todas las filas con el GPS del receptor. Dron: solo las filas con posicion del dron, y mapa y graficas usan esas."""
        if not self.data or not self.data.has_gps:
            return
        full = self.full_data
        if self.gpsbox.currentData() == 'dron':
            if self.dron_data is None:
                keep = np.isfinite(full.gps['dron'][2])
                self.dron_data = Data(full.frame[keep].reset_index(drop=True), full.time_column, self.zone, self.unit, full.vars)
                lat, lon, mx, my, _ = self.dron_data.gps['dron']
                self.dron_data.gps['dron'] = (lat, lon, mx, my, full.gps['dron'][4])  # la ruta del dron no une vuelos distintos
                self.dron_data.set_gps('dron')
            self.data = self.dron_data
        else:
            self.data = full
        self.selected = [c for c in self.selected if c in self.data.vars]
        self.range, self.big, self.window = None, None, None
        self.build_map()
        self.build_plots()
        self.compute_days()
        self.compute_intervals()
        self.info.setText(f'{self.data.n:,} filas · {len(self.days)} días · {g.short_name(self.path)}')

    def recolor(self, *_):
        d = self.data
        if not d or not d.has_gps:
            return
        idx = self.marker_idx
        if not len(idx):
            self.points.setData([], [])
            self.legend.setText('')
            self.legend.setStyleSheet('')
            return
        name = self.colorbox.currentText()
        if name in d.y:
            values = d.y[name][idx]
            lo, hi = np.nanmin(values), np.nanmax(values)
            norm = np.nan_to_num((values - lo) / (hi - lo) if hi > lo else np.zeros_like(values), nan=0.0)
            cmap, stops = viridis_stops()
            colors = cmap.map(norm, mode='byte')
            self.points.setData(x=d.mx[idx], y=d.my[idx], brush=[pg.mkBrush(*c) for c in colors])
            self.legend.setText(f'{name}: {fmt(lo)}  →  {fmt(hi)}')
            self.legend.setStyleSheet(f'color:white;font-weight:600;padding:2px 8px;background:qlineargradient(x1:0,y1:0,x2:1,y2:0,{stops})')
        else:
            self.points.setData(x=d.mx[idx], y=d.my[idx], brush=pg.mkBrush('#c1121f'))
            self.legend.setText('')
            self.legend.setStyleSheet('')

    def heat_inputs(self, idx):
        """Posiciones (Web Mercator, ya corregidas por el desfase) y valores de las muestras `idx` para el mapa de calor."""
        d = self.data
        name = self.heatvar.currentData()
        values = d.y[name][idx].copy() if name else np.ones(len(idx))
        lo, hi = self.valid_range()
        if lo is not None:
            values[values < lo] = np.nan
        if hi is not None:
            values[values > hi] = np.nan
        t = d.x.get('fecha', d.x.get('transcurrido'))
        self.lagbox.setEnabled(t is not None)
        x, y = mc.lag_positions(t, d.mx, d.my, self.lagbox.value() if t is not None else 0)
        return x[idx], y[idx], values

    def valid_range(self):
        out = []
        for box in (self.vmin, self.vmax):
            try:
                out.append(float(box.text().strip().replace(',', '.')))
                box.setStyleSheet('')
            except ValueError:
                out.append(None)
                box.setStyleSheet('' if not box.text().strip() else 'border:1px solid #c1121f')
        return tuple(out)

    def update_coverage(self, *_):
        """Mapa de calor: celdas cuadradas coloreadas por su % de muestras (cobertura) o por una variable (ver mapa_calor.py)."""
        d = self.data
        name = self.heatvar.currentData()
        as_points = name is not None and self.drawbox.currentData() == 'puntos'
        for box in (self.statbox, self.cellbox, self.smoothbox):
            box.setEnabled(not as_points and (name is not None or box is not self.statbox))
        self.drawbox.setEnabled(name is not None)
        self.sizebox.setEnabled(as_points)
        on = self.coverbox.isChecked() and d is not None and d.has_gps and len(self.valid_pts) > 0
        self.cover.setVisible(on and not as_points)
        self.heat_points.setVisible(on and as_points)
        self.points.setVisible(not (on and as_points))  # los puntos de 'Color de la ruta' estorban a los del mapa
        self.cover_legend.setVisible(on)
        self.cover_grid = self.heat_pts = None
        if not on:
            return
        if as_points:
            self.draw_heat_points(name)
            return
        meters = self.cellbox.currentData()
        stat = self.statbox.currentData() if name else 'muestras'
        smooth = self.smoothbox.currentData()
        idx = self.valid_pts
        cell = mc.cell_units(meters, float(np.nanmedian(d.lat[idx])))
        try:
            values, counts, x0, y0 = mc.grid(*self.heat_inputs(idx), cell, stat, smooth)
        except ValueError as exc:
            self.cover.hide()
            self.cover_legend.setText(f'Mapa de calor: {exc}')
            return
        if stat == 'muestras':
            values = values / len(idx) * 100
        shown = values[np.isfinite(values)]
        lo, hi = (0.0, float(shown.max())) if stat == 'muestras' else (float(shown.min()), float(shown.max()))
        norm = np.nan_to_num((values - lo) / (hi - lo)) if hi > lo else np.zeros_like(values)
        if stat == 'muestras':
            cmap = pg.colormap.get('inferno')
            rgba = cmap.map(norm, mode='byte').astype(np.uint8)
            ramp = [(t, tuple(c[:3])) for t, c in zip(np.linspace(0, 1, 6), cmap.map(np.linspace(0, 1, 6), mode='byte'))]
        else:
            rgba = np.zeros(values.shape + (4,), np.uint8)
            rgba[..., :3] = mc.ramp_colors(norm)
            ramp = mc.RAMP
        rgba[..., 3] = np.where(np.isfinite(values), 200, 0)
        self.cover.setImage(rgba, levels=(0, 255), autoLevels=False)
        self.cover.setRect(QtCore.QRectF(x0, y0, values.shape[1] * cell, values.shape[0] * cell))
        self.cover_grid = (x0, y0, cell, counts, values, stat)
        stops = ', '.join(f'stop:{t:.2f} rgb({r},{gg},{b})' for t, (r, gg, b) in ramp)
        extra = f' · suavizado {smooth:g}' if smooth else ''
        extra += f' · desfase {self.lagbox.value():g} s' if self.lagbox.isEnabled() and self.lagbox.value() else ''
        if stat == 'muestras':
            self.cover_base = f'Cobertura · celdas de {meters} m{extra} · {int((counts > 0).sum()):,} con datos · 0 → {hi:.1f}% de {len(idx):,} muestras'
        else:
            self.cover_base = f'{mc.STATS[stat]} de {name} · celdas de {meters} m{extra} · {fmt(lo)} → {fmt(hi)}'
        self.cover_legend.setText(self.cover_base)
        self.cover_legend.setStyleSheet(f'color:white;font-weight:600;padding:2px 8px;background:qlineargradient(x1:0,y1:0,x2:1,y2:0,{stops})')

    def draw_heat_points(self, name):
        """Modo Puntos: cada muestra del tramo en su posicion (con desfase), coloreada por su valor; los altos encima."""
        x, y, values = self.heat_inputs(self.valid_pts)
        ok = np.flatnonzero(np.isfinite(x) & np.isfinite(y) & np.isfinite(values))
        if not len(ok):
            self.heat_points.setData([], [])
            self.cover_legend.setText(f'Mapa de calor: no hay muestras de {name} con posición y valor válido.')
            return
        ok = ok[np.argsort(values[ok], kind='stable')]
        x, y, values = x[ok], y[ok], values[ok]
        lo, hi = float(values[0]), float(values[-1])
        level = np.round((values - lo) / (hi - lo) * 63).astype(int) if hi > lo else np.zeros(len(values), int)
        brushes = [pg.mkBrush(*c, 235) for c in mc.ramp_colors(np.linspace(0, 1, 64))]
        self.heat_points.setData(x=x, y=y, size=self.sizebox.value(), brush=[brushes[k] for k in level])
        self.heat_pts = (x, y, values)
        lag = f' · desfase {self.lagbox.value():g} s' if self.lagbox.isEnabled() and self.lagbox.value() else ''
        self.cover_base = f'{name} · {len(values):,} puntos{lag} · {fmt(lo)} → {fmt(hi)}'
        self.cover_legend.setText(self.cover_base)
        stops = ', '.join(f'stop:{t:.2f} rgb({r},{gg},{b})' for t, (r, gg, b) in mc.RAMP)
        self.cover_legend.setStyleSheet(f'color:white;font-weight:600;padding:2px 8px;background:qlineargradient(x1:0,y1:0,x2:1,y2:0,{stops})')

    def cover_hover(self, pt):
        if self.heat_pts is not None:
            x, y, values = self.heat_pts
            dist = np.hypot(x - pt.x(), y - pt.y())
            k = int(np.argmin(dist))
            near = dist[k] <= max(self.sizebox.value(), 10) * self.view.viewPixelSize()[0]
            self.cover_legend.setText(f'{self.cover_base} · bajo el cursor: {fmt(values[k])}' if near else self.cover_base)
            return
        if self.cover_grid is None:
            return
        x0, y0, cell, counts, values, stat = self.cover_grid
        col, row = int((pt.x() - x0) // cell), int((pt.y() - y0) // cell)
        if 0 <= row < counts.shape[0] and 0 <= col < counts.shape[1] and np.isfinite(values[row, col]):
            n = int(counts[row, col])
            value = f'{values[row, col]:.2f}%' if stat == 'muestras' else fmt(values[row, col])
            self.cover_legend.setText(f'{self.cover_base} · bajo el cursor: {value} ({n:,} muestras en la celda)')
        else:
            self.cover_legend.setText(self.cover_base)

    def export_heat(self):
        """Guarda el mapa de calor de la variable elegida como GeoTIFF + puntos GeoJSON + proyecto QGIS (mapa_calor.export)."""
        d = self.data
        name = self.heatvar.currentData()
        if not d or not d.has_gps or not len(getattr(self, 'valid_pts', [])):
            QtWidgets.QMessageBox.warning(self, 'Exportar mapa de calor', 'Este CSV no tiene posiciones GPS válidas.')
            return
        if name is None:
            QtWidgets.QMessageBox.information(self, 'Exportar mapa de calor', 'En «Valor» elige la variable que quieres georreferenciar.')
            return
        idx = self.valid_pts
        stem = f'{g.short_name(self.path)}_{name}'
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Exportar mapa de calor', str(Path(g.documents_dir()) / f'{stem}.tif'), 'GeoTIFF (*.tif)')
        if not path:
            return
        extra = []
        answer = QtWidgets.QMessageBox.question(
            self, 'Exportar mapa de calor', '¿Agregar al proyecto de QGIS otro GeoTIFF debajo del mapa de calor?\n'
            '(por ejemplo, el mosaico térmico temperatura_python.tif de TermoReferencia)',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
        if answer == QtWidgets.QMessageBox.Yes:
            other, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'GeoTIFF adicional', str(Path(path).parent), 'GeoTIFF (*.tif *.tiff)')
            extra = [other] if other else []
        t = d.x.get('fecha', d.x.get('transcurrido'))
        values = np.full(d.n, np.nan)
        values[idx] = d.y[name][idx]  # todas las posiciones (para el desfase), solo los valores del tramo
        mode = self.drawbox.currentData()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            summary = mc.export(path, d.lat, d.lon, values, name, self.cellbox.currentData(), self.statbox.currentData(),
                                self.smoothbox.currentData(), t, self.lagbox.value(), d.utc, self.valid_range(), extra,
                                float(np.nanmedian(d.lat[idx])), mode, round(self.sizebox.value() * MM_PER_PX, 2))
        except (ValueError, OSError, KeyError) as exc:
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.critical(self, 'Exportar mapa de calor', str(exc))
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        scope = 'el tramo elegido' if self.window else 'todo el archivo'
        QtWidgets.QMessageBox.information(self, 'Exportar mapa de calor', f'Se exportó {scope}.\n\n{summary}\n\nAbre el .qgz con QGIS.')

    # ---------- plots ----------
    # ---------- day / hour ----------
    # Ver CHANGELOG.md (2026-10-14, "Día y hora") y la seccion "Día y hora" del README antes de cambiar esto.
    def compute_days(self):
        """Llena el selector de dias con los dias que tienen muestras (hora local de la zona elegida)."""
        d = self.data
        self.days = {}
        self.daybox.blockSignals(True)
        self.daybox.clear()
        t = d.x.get('fecha') if d is not None else None
        if t is not None:
            t = t[np.isfinite(t)]
            day_index = np.floor(t / 86400).astype(np.int64)
            self.daybox.addItem(f'Todos los días ({len(np.unique(day_index))})')
            for day in np.unique(day_index):
                inside = np.flatnonzero(day_index == day)
                self.days[len(self.days) + 1] = (int(day), int(inside[0]), int(inside[-1]))
                date = datetime.datetime.fromtimestamp(int(day) * 86400, tz=datetime.timezone.utc)
                self.daybox.addItem(f'{date:%d/%m/%Y} · {len(inside):,} muestras')
        self.daybox.setEnabled(bool(self.days))
        self.daybox.blockSignals(False)
        self.fill_hours(0)

    def fill_hours(self, day_row):
        """Horas con muestras del dia elegido; 'de' lista inicios de hora y 'a' lista finales (hora + 1)."""
        d = self.data
        self.hours = []  # (hora, i0, i1)
        for box in (self.hfrom, self.hto):
            box.blockSignals(True)
            box.clear()
        if day_row in self.days:
            t = d.x['fecha'][np.isfinite(d.x['fecha'])]
            day, i0, i1 = self.days[day_row]
            hour_index = np.floor((t[i0:i1 + 1] - day * 86400) / 3600).astype(int)
            for hour in np.unique(hour_index):
                inside = np.flatnonzero(hour_index == hour) + i0
                self.hours.append((int(hour), int(inside[0]), int(inside[-1])))
                self.hfrom.addItem(f'{hour:02d}:00')
                self.hto.addItem(f'{hour + 1:02d}:00')
            self.hto.setCurrentIndex(len(self.hours) - 1)
        for box in (self.hfrom, self.hto):
            box.setEnabled(bool(self.hours))
            box.blockSignals(False)

    def span(self, i0, i1):
        """Rango X (con un margen de 2 %) que ocupan las muestras i0..i1."""
        i0, i1 = min(i0, self.m - 1), min(i1, self.m - 1)
        lo, hi = float(self.xv[i0]), float(self.xv[i1])
        pad = (hi - lo) * 0.02 or 1.0
        return lo - pad, hi + pad

    def zoom_rows(self, i0, i1):
        """Amplia las graficas a las muestras i0..i1 (indices de la serie ordenada por tiempo)."""
        self.plots[0]['pi'].setXRange(*self.span(i0, i1), padding=0)

    def lock_plots(self):
        """Con un tramo elegido, las curvas solo contienen sus muestras y el zoom/desplazamiento no sale de él."""
        d = self.data
        for p in self.plots:
            y = d.y[p['name']][:self.m]
            if self.window:
                i0, i1 = self.window
                p['curve'].setData(self.xv[i0:i1 + 1], y[i0:i1 + 1])
                lo, hi = self.span(i0, i1)
                p['pi'].vb.setLimits(xMin=lo, xMax=hi)
            else:
                p['curve'].setData(self.xv, y)
                p['pi'].vb.setLimits(xMin=None, xMax=None)

    def on_day(self, row):
        if not self.plots or row < 0:
            return
        self.fill_hours(row)
        self.reset_box(self.intervalbox)
        if row in self.days:
            self.apply_window(*self.days[row][1:])
        else:
            self.clear_window()

    def on_hour_from(self, row):
        if row < 0 or not self.hours:
            return
        if self.hto.currentIndex() < row:  # el fin no puede quedar antes del inicio
            self.hto.blockSignals(True)
            self.hto.setCurrentIndex(row)
            self.hto.blockSignals(False)
        self.apply_hours()

    def on_hour_to(self, row):
        if row < 0 or not self.hours:
            return
        if self.hfrom.currentIndex() > row:
            self.hfrom.blockSignals(True)
            self.hfrom.setCurrentIndex(row)
            self.hfrom.blockSignals(False)
        self.apply_hours()

    def apply_hours(self):
        """Ventana = desde el inicio de la hora 'de' hasta el final de la hora 'a'."""
        if not self.plots:
            return
        self.reset_box(self.intervalbox)
        self.apply_window(self.hours[self.hfrom.currentIndex()][1], self.hours[self.hto.currentIndex()][2])

    def compute_intervals(self, *_):
        """Tramos continuos: una pausa mayor a 'Inactividad' entre dos muestras abre un tramo nuevo."""
        d = self.data
        self.intervals = []
        self.intervalbox.blockSignals(True)
        self.intervalbox.clear()
        t = d.x.get('fecha') if d is not None else None
        if t is not None:
            t = t[np.isfinite(t)]
            if len(t):
                cuts = np.flatnonzero(np.diff(t) > self.gapbox.value()) + 1
                self.intervals = list(zip(np.concatenate(([0], cuts)).tolist(), np.concatenate((cuts - 1, [len(t) - 1])).tolist()))
            self.intervalbox.addItem(f'Todo · {len(self.intervals)} tramos')
            for k, (i0, i1) in enumerate(self.intervals, 1):
                a, b = (datetime.datetime.fromtimestamp(v, tz=datetime.timezone.utc) for v in (t[i0], t[i1]))
                span = f'{a:%d/%m %H:%M:%S} → {b:%H:%M:%S}' if a.date() == b.date() else f'{a:%d/%m %H:%M} → {b:%d/%m %H:%M}'
                secs = int(t[i1] - t[i0])
                dur = f'{secs // 3600} h {secs % 3600 // 60:02d} min' if secs >= 3600 else f'{secs // 60} min {secs % 60:02d} s'
                self.intervalbox.addItem(f'{k} · {span} · {dur} · {i1 - i0 + 1:,} muestras')
        self.intervalbox.setEnabled(bool(self.intervals))
        self.gapbox.setEnabled(t is not None)
        self.intervalbox.blockSignals(False)
        self.update_gaps()

    def on_interval(self, row):
        if not self.plots or row < 0:
            return
        self.reset_box(self.daybox, hours=True)
        if 1 <= row <= len(self.intervals):
            self.apply_window(*self.intervals[row - 1])
        else:
            self.clear_window()

    def reset_box(self, box, hours=False):
        box.blockSignals(True)
        box.setCurrentIndex(0)
        box.blockSignals(False)
        if hours:
            self.fill_hours(0)

    def apply_window(self, i0, i1):
        """Limita las graficas (zoom) y el mapa (ruta, puntos, cobertura) a las muestras i0..i1."""
        d = self.data
        i0, i1 = max(0, i0), min(i1, self.m - 1)
        self.window = (i0, i1)
        self.lock_plots()
        self.zoom_rows(i0, i1)
        self.build_map()
        n = i1 - i0 + 1
        self.info.setText(f'Tramo: {n:,} muestras' + (f' · {d.utc[i0]} → {d.utc[i1]} UTC' if d.utc is not None else ''))

    def clear_window(self):
        if not self.data:
            return
        self.window = None
        self.reset_box(self.daybox, hours=True)
        self.reset_box(self.intervalbox)
        self.build_map()
        if self.plots:
            self.lock_plots()
            self.reset_zoom()
        self.info.setText(f'{self.data.n:,} filas · {g.short_name(self.path)}')

    # ---------- font size ----------
    def set_fontsize(self, size):
        self.fontsize = int(size)
        self.settings.setValue('fontsize', self.fontsize)
        self.apply_font()
        if self.data:
            self.build_plots()

    def apply_font(self):
        size = self.fontsize
        font = QtGui.QFont(QtWidgets.QApplication.instance().font())
        font.setPointSize(size)
        QtWidgets.QApplication.instance().setFont(font)
        self.setFont(font)
        for label in (self.legend, self.cover_legend, self.attribution, self.info):
            label.setFont(font)
        self.attribution.setStyleSheet(f'color:{self.muted};font-size:{max(size - 2, 7)}pt')

    def on_xmode(self, label):
        if not self.data:
            return
        self.xmode = next(m for m, text in X_LABELS.items() if text == label)
        self.range = None
        self.build_plots()

    def on_var_toggle(self, _item):
        self.selected = [self.varlist.item(i).text() for i in range(self.varlist.count()) if self.varlist.item(i).checkState() == QtCore.Qt.Checked]
        if not self.selected:
            self.varlist.blockSignals(True)
            self.varlist.item(0).setCheckState(QtCore.Qt.Checked)
            self.varlist.blockSignals(False)
            self.selected = [self.varlist.item(0).text()]
        self.big = None
        self.build_plots()

    def set_all(self, state):
        self.varlist.blockSignals(True)
        for i in range(self.varlist.count()):
            self.varlist.item(i).setCheckState(QtCore.Qt.Checked if state else QtCore.Qt.Unchecked)
        self.varlist.blockSignals(False)
        self.on_var_toggle(None)

    def build_plots(self):
        d = self.data
        self.glw.clear()
        self.plots = []
        x_full = d.x[self.xmode]
        m = int(np.isfinite(x_full).sum())
        self.m, self.xv = m, x_full[:m]
        ncols = 3
        first = None
        for k, name in enumerate(self.selected):
            color = self.color_of(name)
            axis = {'bottom': pg.DateAxisItem(orientation='bottom', utcOffset=0)} if self.xmode == 'fecha' else {}
            pi = pg.PlotItem(axisItems=axis)
            pi.showGrid(x=True, y=True, alpha=0.3)
            pi.setMinimumSize(60, 60)  # lets the panels shrink with the window instead of overflowing
            pi.setLabel('left', name, color=color, **{'font-size': f'{self.fontsize}pt', 'font-weight': 'bold'})
            left = pi.getAxis('left')
            left.setPen(pg.mkPen(color, width=2))
            left.setTextPen(pg.mkPen(color))
            small = QtGui.QFont(self.font())
            small.setPointSize(max(self.fontsize - 1, 7))
            for side in ('left', 'bottom'):
                pi.getAxis(side).setStyle(tickFont=small, tickTextOffset=4)
            left.setWidth(58)
            curve = pi.plot(self.xv, d.y[name][:m], pen=None, symbol='o', symbolSize=4, symbolBrush=color, symbolPen=None)  # solo puntos
            curve.setClipToView(True)
            thread_color = pg.mkColor(color)
            thread_color.setAlpha(140)
            thread = pg.PlotDataItem(pen=pg.mkPen(thread_color, width=0.8), connect='finite')  # hilo fino entre muestras seguidas
            gap = pg.PlotDataItem(pen=pg.mkPen(color, width=1.2, style=QtCore.Qt.DashLine), connect='finite')  # une los puntos a ambos lados de una pausa
            pi.addItem(thread)
            pi.addItem(gap)
            curve.setZValue(1)  # los puntos quedan encima del hilo
            line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(self.cursor_color, width=1, style=QtCore.Qt.DashLine))
            line.hide()
            pi.addItem(line, ignoreBounds=True)
            if first is None:
                first = pi
                pi.vb.sigXRangeChanged.connect(self.on_x_changed)
            else:
                pi.setXLink(first)
            p = {'name': name, 'pi': pi, 'curve': curve, 'thread': thread, 'gap': gap, 'line': line, 'color': color, 'k': k, 'ncols': ncols, 'stat': '', 'val': ''}
            self.plots.append(p)
            self.refresh_title(p)
        self.layout_plots()
        self.update_gaps()
        if self.window and self.plots:
            self.lock_plots()
        self.reset_zoom()

    def update_gaps(self, *_):
        """Puntos unidos por un hilo fino; donde hay una pausa mayor a 'Inactividad' el hilo se corta y una linea discontinua une el ultimo punto con el siguiente."""
        if not self.plots:
            return
        x = self.xv
        cuts = np.flatnonzero(np.diff(x) > self.gapbox.value()) if self.xmode != 'indice' else np.array([], int)
        for p in self.plots:
            y = self.data.y[p['name']][:self.m]
            gx, gy = [], []
            for i in cuts:
                before, after = np.flatnonzero(np.isfinite(y[:i + 1])), np.flatnonzero(np.isfinite(y[i + 1:]))
                if len(before) and len(after):
                    a, b = before[-1], i + 1 + after[0]
                    gx += [x[a], x[b], np.nan]
                    gy += [y[a], y[b], np.nan]
            p['gap'].setData(np.array(gx), np.array(gy))
            p['thread'].setData(np.insert(x, cuts + 1, np.nan), np.insert(y, cuts + 1, np.nan))

    def layout_plots(self):
        self.glw.ci.clear()
        shown = [p for p in self.plots if self.big is None or p is self.big]
        ncols = 1 if self.big else (self.plots[0]['ncols'] if self.plots else 1)
        self.glw.setMinimumHeight(0 if self.big else int(26 * self.fontsize) * math.ceil(len(shown) / ncols))
        for i, p in enumerate(shown):
            self.glw.ci.addItem(p['pi'], row=i // ncols, col=i % ncols)

    def refresh_title(self, p):
        p['pi'].setTitle(f'<span style="color:{p["color"]};font-size:{self.fontsize}pt"><b>{p["name"]}</b> {p["val"]}</span> '
                         f'<br><span style="color:{self.muted};font-size:{max(self.fontsize - 2, 7)}pt">{p["stat"]}</span>')

    def reset_zoom(self):
        """Vuelve a ver todo el archivo o, si hay un tramo elegido, todo el tramo."""
        self.range = None
        for p in self.plots:
            p['pi'].enableAutoRange()
        if self.window and self.plots:
            self.zoom_rows(*self.window)
        self.on_range()

    def on_plot_click(self, event):
        if event.button() != QtCore.Qt.LeftButton or not self.plots or len(self.plots) < 2 and not self.big:
            return
        pos = event.scenePos()
        for p in self.plots:
            if p['pi'].isVisible() and p['pi'].sceneBoundingRect().contains(pos):
                self.big = None if self.big is p else p
                self.layout_plots()
                return

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape and self.big:
            self.big = None
            self.layout_plots()
        else:
            super().keyPressEvent(event)

    # ---------- visible range: stats, Y fit, route highlight ----------
    def on_x_changed(self, vb, rng):
        full = self.plots[0]['curve'].getData()[0] if self.plots else None
        self.range = tuple(rng)
        self.range_timer.start()

    def visible_idx(self):
        m = self.m
        first, last = self.window or (0, m - 1)
        if self.range is None or not m:
            return first, last
        lo, hi = min(self.range), max(self.range)
        i0, i1 = int(np.searchsorted(self.xv, lo, 'left')), max(0, int(np.searchsorted(self.xv, hi, 'right')) - 1)
        return max(i0, first), min(i1, last)  # nunca fuera del tramo elegido

    def on_range(self):
        if not self.plots:
            return
        i0, i1 = self.visible_idx()
        i0, i1 = max(0, min(i0, self.m - 1)), max(0, min(i1, self.m - 1))
        zoomed = self.range is not None and (i1 - i0 + 1) < self.m
        for p in self.plots:
            seg = self.data.y[p['name']][i0:i1 + 1]
            finite = seg[np.isfinite(seg)]
            if len(finite):
                mn, mx = float(finite.min()), float(finite.max())
                p['stat'] = f'mín {fmt(mn)} · prom {fmt(float(finite.mean()))} · máx {fmt(mx)}'
                if self.fity.isChecked() and zoomed:
                    pad = (mx - mn) * 0.08 or abs(mx) * 0.02 or 1
                    p['pi'].setYRange(mn - pad, mx + pad, padding=0)
                else:
                    p['pi'].enableAutoRange(axis='y')
            else:
                p['stat'] = 'sin datos'
            self.refresh_title(p)
        if self.data.has_gps:
            base = (self.window[1] - self.window[0] + 1) if self.window else self.m  # el tramo elegido ya es el mapa completo
            if zoomed and (i1 - i0 + 1) < 0.9 * base:
                self.highlight.setData(self.data.mx[i0:i1 + 1], self.data.my[i0:i1 + 1])
            else:
                self.highlight.setData([], [])

    # ---------- shared cursor ----------
    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Leave:
            self.tip.hide()
        return super().eventFilter(obj, event)

    def tip_html(self, p, i):
        d = self.data
        x = d.x[self.xmode][i]
        if self.xmode == 'fecha':
            xt = pd.to_datetime(x, unit='s').strftime('%Y-%m-%d %H:%M:%S')
        elif self.xmode == 'transcurrido':
            xt = f'{x:.1f} s'
        else:
            xt = f'{int(x)}'
        rows = [(X_LABELS[self.xmode], xt), (p['name'], fmt(d.y[p['name']][i]))]
        if d.has_gps:
            rows += [('Latitud', f'{d.lat[i]:.6f}' if np.isfinite(d.lat[i]) else 'No disponible'),
                     ('Longitud', f'{d.lon[i]:.6f}' if np.isfinite(d.lon[i]) else 'No disponible')]
        height = g.altitude_column(d.y)
        if height:
            rows.append(('Altitud', f'{fmt(d.y[height][i])} m'))
        body = ''.join(f'<tr><td style="color:{self.muted};padding-right:10px">{k}</td><td><b>{v}</b></td></tr>' for k, v in rows)
        return f'<table style="font-size:{max(self.fontsize - 1, 7)}pt"><tr><td colspan="2" style="color:{p["color"]}"><b>Muestra {i + 1}</b></td></tr>{body}</table>'

    def show_tip(self, p, i, pos):
        self.tip.setText(self.tip_html(p, i))
        self.tip.adjustSize()
        spot = self.glw.mapFromScene(pos)
        x, y = spot.x() + 16, spot.y() + 16
        if x + self.tip.width() > self.glw.width():
            x = spot.x() - self.tip.width() - 16
        if y + self.tip.height() > self.glw.height():
            y = spot.y() - self.tip.height() - 16
        self.tip.move(max(0, x), max(0, y))
        self.tip.show()
        self.tip.raise_()

    def on_plot_move(self, pos):
        self.tip.hide()
        for p in self.plots:
            if p['pi'].isVisible() and p['pi'].vb.sceneBoundingRect().contains(pos) and self.m:
                x = p['pi'].vb.mapSceneToView(pos).x()
                i = int(np.searchsorted(self.xv, x))
                if i > 0 and (i >= self.m or abs(self.xv[i - 1] - x) <= abs(self.xv[i] - x)):
                    i -= 1
                i = min(i, self.m - 1)
                if self.window:
                    i = min(max(i, self.window[0]), self.window[1])
                self.set_cursor(i)
                self.show_tip(p, i, pos)
                return

    def on_map_move(self, pos):
        d = self.data
        if not d or not d.has_gps or not self.view.sceneBoundingRect().contains(pos):
            return
        pt = self.view.mapSceneToView(pos)
        self.cover_hover(pt)
        idx = self.valid_pts
        dist = np.hypot(d.mx[idx] - pt.x(), d.my[idx] - pt.y())
        k = int(np.argmin(dist))
        if dist[k] <= 25 * self.view.viewPixelSize()[0]:
            self.set_cursor(int(idx[k]))

    def set_cursor(self, i):
        d = self.data
        for p in self.plots:
            x = d.x[self.xmode][i]
            if np.isfinite(x):
                p['line'].setPos(x)
                p['line'].show()
            p['val'] = '= ' + fmt(d.y[p['name']][i])
            self.refresh_title(p)
        text = f'Muestra {i + 1}'
        if d.utc is not None and d.utc[i]:
            text += f' · {d.utc[i]} UTC'
        if d.has_gps and np.isfinite(d.mx[i]):
            self.map_cursor.setData(x=[d.mx[i]], y=[d.my[i]])
            text += f' · {d.lat[i]:.6f}, {d.lon[i]:.6f}'
        else:
            self.map_cursor.setData([], [])
        self.info.setText(text)

    def export_png(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Exportar PNG', (g.short_name(self.path) if self.path else 'grafica') + '.png', 'PNG (*.png)')
        if path:
            self.split.grab().save(path)

    def export_excel(self):
        """Exporta a Excel lo que se ve: las variables marcadas y las muestras visibles (dentro del tramo elegido)."""
        d = self.data
        if not d or not self.plots:
            return
        i0, i1 = self.visible_idx()
        i0, i1 = max(0, min(i0, self.m - 1)), max(0, min(i1, self.m - 1))
        if self.window:
            i0, i1 = max(i0, self.window[0]), min(i1, self.window[1])
        if i1 < i0:
            QtWidgets.QMessageBox.warning(self, 'Exportar Excel', 'No hay muestras visibles para exportar.')
            return
        n = i1 - i0 + 1
        scope = 'el tramo elegido' if self.window else 'todo el archivo'
        if (i0, i1) != (self.window or (0, self.m - 1)):
            scope = 'la parte ampliada' + (' del tramo' if self.window else '')
        when = f'\n{d.utc[i0]} → {d.utc[i1]} UTC' if d.utc is not None else ''
        answer = QtWidgets.QMessageBox.question(
            self, 'Exportar Excel', f'Se exportará {scope}: {n:,} muestras.{when}\n\nVariables ({len(self.selected)}): {", ".join(self.selected)}'
            '\n\nPara cambiarlo elige otro tramo, amplía las gráficas o marca otras variables.')
        if answer != QtWidgets.QMessageBox.Yes:
            return
        name = g.short_name(self.path) + (f'_{d.utc[i0][:16]}'.replace(':', '').replace(' ', '_') if d.utc is not None else '')
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Exportar Excel', str(Path(g.documents_dir()) / f'{name}.xlsx'), 'Excel (*.xlsx)')
        if not path:
            return
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            output = g.make_excel(d.frame.iloc[i0:i1 + 1], path, self.selected, d.time_column, self.zone, self.unit, g.short_name(self.path))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, 'No se pudo exportar', str(exc))
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.info.setText(f'Excel guardado: {output} · {n:,} muestras')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', nargs='?', type=Path)
    parser.add_argument('--y', nargs='+', help='Variables iniciales')
    parser.add_argument('--tiempo', help='Columna de fecha o timestamp')
    parser.add_argument('--zona', default=g.DEFAULT_ZONE)
    parser.add_argument('--unidad', choices=['auto', 's', 'ms', 'us', 'ns'], default='auto')
    parser.add_argument('--solo-nuevas', action='store_true')
    parser.add_argument('--captura', type=Path, help='Guardar una captura PNG de la ventana y salir (pruebas)')
    args = parser.parse_args(argv)
    app = QtWidgets.QApplication(sys.argv[:1])
    viewer = Viewer(args.zona, args.unidad, args.solo_nuevas)
    viewer.resize(1500, 850)
    if args.captura:
        viewer.show()
    else:
        viewer.showMaximized()
    if args.csv:
        viewer.load(str(args.csv), args.y, args.tiempo)
    if args.captura:
        def shot():
            viewer.grab().save(str(args.captura))
            app.quit()
        QtCore.QTimer.singleShot(5000, shot)
    sys.exit(app.exec_() if hasattr(app, 'exec_') else app.exec())


if __name__ == '__main__':
    main()
