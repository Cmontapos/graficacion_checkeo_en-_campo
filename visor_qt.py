#!/usr/bin/env python3
"""Visor rápido de CSV MicroGas con pyqtgraph: mapa OpenStreetMap a la izquierda, gráficas enlazadas a la derecha."""
from __future__ import annotations

import argparse
import io
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

import graficar as g

pg.setConfigOptions(imageAxisOrder='row-major', antialias=False, background='w', foreground='#1b1f24')

WORLD = 2 * math.pi * 6378137.0
PROVIDERS = {
    'OpenStreetMap': ('osm', 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', '© OpenStreetMap contributors'),
    'Satélite (Esri)': ('esri', 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 'Esri, Maxar, Earthstar Geographics'),
}
X_LABELS = {'fecha': 'Fecha y hora', 'transcurrido': 'Tiempo transcurrido (s)', 'indice': 'Número de muestra'}
CACHE = Path.home() / '.cache' / 'gaslab_tiles'


def fetch_tile(provider, z, x, y):
    """RGB uint8 array of one tile (disk cached), or None when offline."""
    name, url, _ = provider
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
        z = int(np.clip(round(math.log2(WORLD / (256 * (x1 - x0) / width))), 1, 19))
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

    def __init__(self, frame, time_column, zone, unit):
        self.n = len(frame)
        self.vars = g.numeric_columns(frame)
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
        try:
            segments, _ = g.gps_segments(frame)
            lat_col = next(c for c in ('latitud', 'latitude', 'lat') if c in frame)
            lon_col = next(c for c in ('longitud', 'longitude', 'lon', 'lng') if c in frame)
            lat, lon = g.numeric(frame[lat_col]), g.numeric(frame[lon_col])
            ok = (lat.between(-90, 90) & lon.between(-180, 180)).to_numpy()
            self.lat = np.where(ok, lat.to_numpy(dtype=float), np.nan)
            self.lon = np.where(ok, lon.to_numpy(dtype=float), np.nan)
            self.mx, self.my = g._mercator(self.lon, self.lat)
            route_x, route_y = [], []
            for segment in segments:
                sx, sy = g._mercator(np.array([p[2] for p in segment]), np.array([p[1] for p in segment]))
                route_x += list(sx) + [np.nan]
                route_y += list(sy) + [np.nan]
            self.route = (np.array(route_x), np.array(route_y))
            self.has_gps = True
        except (ValueError, StopIteration):
            pass


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
        self._building = False
        self.path = None
        self.settings = QtCore.QSettings('GasLab', 'VisorRapido')
        self.night = str(self.settings.value('night', 'false')).lower() == 'true'
        self.muted = '#262c33'
        self._build_ui()
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
        bar.addWidget(QtWidgets.QLabel('  Color de la ruta '))
        self.colorbox = QtWidgets.QComboBox()
        self.colorbox.currentTextChanged.connect(self.recolor)
        bar.addWidget(self.colorbox)
        self.fity = QtWidgets.QCheckBox('Ajustar Y al tramo')
        self.fity.setChecked(True)
        self.fity.toggled.connect(lambda _: self.on_range())
        bar.addWidget(self.fity)
        bar.addSeparator()
        self.nightbox = QtWidgets.QCheckBox('Modo noche')
        self.nightbox.setChecked(self.night)
        self.nightbox.toggled.connect(self.set_night)
        bar.addWidget(self.nightbox)
        bar.addAction('Restablecer zoom', self.reset_zoom)
        bar.addAction('Exportar PNG…', self.export_png)
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
        self.points = pg.ScatterPlotItem(size=6, pen=None)
        self.highlight = pg.PlotDataItem(pen=pg.mkPen('#ff7f0e', width=5), connect='finite')
        self.map_cursor = pg.ScatterPlotItem(size=16, brush=pg.mkBrush('w'), pen=pg.mkPen('k', width=2))
        self.ends = []
        for emoji in (g.START_ICON, g.END_ICON):
            badge = pg.TextItem(emoji, anchor=(0.5, 0.5), fill=pg.mkBrush(255, 255, 255, 235), border=pg.mkPen('#333', width=2))
            badge.setFont(QtGui.QFont('Noto Color Emoji', 16))
            badge.setColor('#000000')
            self.ends.append(badge)
        for z, item in enumerate((self.route, self.points, self.highlight, self.map_cursor, *self.ends)):
            item.setZValue(z)
            self.view.addItem(item)

    # ---------- loading ----------
    def open_dialog(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Abrir CSV', g.documents_dir(), 'CSV (*.csv)')
        if path:
            self.load(path)

    def load(self, path, columns=None, time_column=None):
        try:
            head = pd.read_csv(path, sep=None, engine='python', encoding='utf-8-sig', nrows=0)
            names = [str(c).strip() for c in head.columns]
            time_column = time_column if time_column in names else next((c for c in g.TIME_COLUMNS if c in names), names[0])
            frame = g.load_csv(path, self.only_new, time_column, self.unit)
            self.data = Data(frame, time_column, self.zone, self.unit)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, 'No se pudo cargar', str(exc))
            return
        self.path = path
        data = self.data
        self.setWindowTitle(f'GasLab · {g.short_name(path)}')
        self.varlist.blockSignals(True)
        self.varlist.clear()
        gps_names = {'latitud', 'latitude', 'lat', 'longitud', 'longitude', 'lon', 'lng'}
        default = [c for c in (columns or ()) if c in data.vars] or [c for c in ('co2_ppm', 'temperatura_c', 'humedad_pct', 'pm2_5') if c in data.vars] \
            or [c for c in data.vars if c not in gps_names][:4] or data.vars[:1]
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
        self.range, self.big = None, None
        self.left.setVisible(data.has_gps)
        self.build_map()
        self.build_plots()
        self.info.setText(f'{data.n:,} filas · {g.short_name(path)}')

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
        self.attribution.setStyleSheet(f'color:{self.muted};font-size:10px')
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
        self.route.setData(*d.route)
        valid = np.flatnonzero(np.isfinite(d.mx))
        self.valid_pts = valid
        keep = valid[np.linspace(0, len(valid) - 1, min(len(valid), 4000)).astype(int)] if len(valid) else valid
        self.marker_idx = np.unique(keep)
        self.recolor()
        first, last = valid[0], valid[-1]
        for badge, i in zip(self.ends, (first, last)):
            badge.setPos(d.mx[i], d.my[i])
        pad_x = max((np.nanmax(d.mx) - np.nanmin(d.mx)) * 0.12, 60)
        pad_y = max((np.nanmax(d.my) - np.nanmin(d.my)) * 0.12, 60)
        self.view.setRange(xRange=(np.nanmin(d.mx) - pad_x, np.nanmax(d.mx) + pad_x), yRange=(np.nanmin(d.my) - pad_y, np.nanmax(d.my) + pad_y), padding=0)
        self.tile_timer.start()

    def recolor(self, *_):
        d = self.data
        if not d or not d.has_gps:
            return
        idx = self.marker_idx
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

    # ---------- plots ----------
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
            pi.setLabel('left', name, color=color, **{'font-size': '10pt', 'font-weight': 'bold'})
            left = pi.getAxis('left')
            left.setPen(pg.mkPen(color, width=2))
            left.setTextPen(pg.mkPen(color))
            small = QtGui.QFont(self.font())
            small.setPointSize(8)
            for side in ('left', 'bottom'):
                pi.getAxis(side).setStyle(tickFont=small, tickTextOffset=4)
            left.setWidth(58)
            curve = pi.plot(self.xv, d.y[name][:m], pen=pg.mkPen(color, width=1.6), connect='finite', symbol=None, symbolSize=4,
                            symbolBrush=color, symbolPen=None)
            curve.setDownsampling(auto=True, method='peak')
            curve.setClipToView(True)
            line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(self.cursor_color, width=1, style=QtCore.Qt.DashLine))
            line.hide()
            pi.addItem(line, ignoreBounds=True)
            if first is None:
                first = pi
                pi.vb.sigXRangeChanged.connect(self.on_x_changed)
            else:
                pi.setXLink(first)
            p = {'name': name, 'pi': pi, 'curve': curve, 'line': line, 'color': color, 'k': k, 'ncols': ncols, 'stat': '', 'val': ''}
            self.plots.append(p)
            self.refresh_title(p)
        self.layout_plots()
        self.reset_zoom()

    def layout_plots(self):
        self.glw.ci.clear()
        shown = [p for p in self.plots if self.big is None or p is self.big]
        ncols = 1 if self.big else (self.plots[0]['ncols'] if self.plots else 1)
        self.glw.setMinimumHeight(0 if self.big else 260 * math.ceil(len(shown) / ncols))
        for i, p in enumerate(shown):
            self.glw.ci.addItem(p['pi'], row=i // ncols, col=i % ncols)

    def refresh_title(self, p):
        p['pi'].setTitle(f'<span style="color:{p["color"]};font-size:10pt"><b>{p["name"]}</b> {p["val"]}</span> '
                         f'<br><span style="color:{self.muted};font-size:8pt">{p["stat"]}</span>')

    def reset_zoom(self):
        self.range = None
        for p in self.plots:
            p['pi'].enableAutoRange()
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
        if self.range is None or not m:
            return 0, m - 1
        lo, hi = min(self.range), max(self.range)
        return int(np.searchsorted(self.xv, lo, 'left')), max(0, int(np.searchsorted(self.xv, hi, 'right')) - 1)

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
            p['curve'].setSymbol('o' if i1 - i0 < 400 else None)
            self.refresh_title(p)
        if self.data.has_gps:
            if zoomed:
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
        return f'<table style="font-size:9pt"><tr><td colspan="2" style="color:{p["color"]}"><b>Muestra {i + 1}</b></td></tr>{body}</table>'

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
                self.set_cursor(i)
                self.show_tip(p, i, pos)
                return

    def on_map_move(self, pos):
        d = self.data
        if not d or not d.has_gps or not self.view.sceneBoundingRect().contains(pos):
            return
        pt = self.view.mapSceneToView(pos)
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
