#!/usr/bin/env python3
"""GasLab 2.0: servidor local que abre la app en el navegador.

El CSV se elige en la página y se sube a este proceso (solo escucha en 127.0.0.1). Las gráficas reciben los datos
ya reducidos al ancho en píxeles (mínimo y máximo por columna de píxeles), y al hacer zoom se pide de nuevo el
tramo visible con más detalle; así un CSV grande no se manda completo al navegador.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo, available_timezones

import numpy as np
import pandas as pd

import graficar as g
import mapa_calor as mc
import terreno

WEB_DIR = Path(__file__).with_name('web')
DEFAULT_GASES = ('co2', 'so2', 'h2s')
SKIP_IN_DEFAULTS = ('temp', 'raw', 'mv', 'volt', 'current')  # p. ej. Sensor_CO2_Internal_Temp_Avg no es la concentración
MAX_ROUTE_POINTS = 20000
MAX_IMAGE_PX = 2600  # lado máximo de la imagen de la nube que se manda a la página
MAX_HEAT_POINTS = 15000  # muestras que se mandan para las barras 3D y para ver el valor con el mouse
MAX_UPLOAD = 1 << 30
KEEP_DATASETS = 4  # archivos abiertos que se conservan en memoria
CLOSE_GRACE = 5  # s que se espera tras cerrar la última página, por si solo se recargó
PAGE_TIMEOUT = 600  # s sin noticias de una página (las de segundo plano avisan a lo sumo una vez por minuto)
FIRST_PAGE_TIMEOUT = 120  # s que se espera a que abra la primera página antes de rendirse


def find_gas(variables, gas):
    """Primera columna con la concentración de ese gas (co2_ppm, CO2_Concentration_Avg, SO2 (ppm)...), o None."""
    return next((v for v in variables if re.search(rf'(^|[^a-z0-9]){gas}([^a-z0-9]|$)', v.lower())
                 and not any(word in v.lower() for word in SKIP_IN_DEFAULTS)), None)


def minmax(y, i0, i1, buckets):
    """Índices de [i0, i1) que conservan el mínimo y el máximo de y en cada uno de `buckets` grupos."""
    count = i1 - i0
    if count <= 2 * buckets:
        return np.arange(i0, i1)
    size = -(-count // buckets)
    block = np.full(buckets * size, np.nan)
    block[:count] = y[i0:i1]
    block = block.reshape(buckets, size)
    low = np.argmin(np.where(np.isnan(block), np.inf, block), axis=1)
    high = np.argmax(np.where(np.isnan(block), -np.inf, block), axis=1)
    base = i0 + np.arange(buckets) * size
    keep = np.unique(np.concatenate([base + low, base + high]))
    return keep[keep < i1]


def as_list(values, digits=6):
    """Lista JSON con None en lugar de NaN."""
    values = np.round(np.asarray(values, dtype=float), digits)
    return [None if v != v else v for v in values.tolist()]


class Dataset:
    def __init__(self, frame, name):
        self.name = name
        self.sheet, self.sheets = frame.attrs.get('sheet'), frame.attrs.get('sheets', [])  # solo en Excel
        self.time_column = g.find_time_column(frame, 'fecha_hora_utc')
        if not self.time_column:
            raise ValueError('No se encontró una columna de tiempo (fecha_hora_utc, timestamp, TIMESTAMP...).')
        dates = g.parse_time(frame, self.time_column)
        ok = dates.notna().to_numpy()
        frame, self.dates = frame[ok].reset_index(drop=True), dates[ok].reset_index(drop=True)
        self.lat_col = next((c for c in g.LAT_COLUMNS if c in frame), None)
        self.lon_col = next((c for c in g.LON_COLUMNS if c in frame), None)
        self.alt_col = g.altitude_column(frame.columns)
        hidden = {self.time_column, self.lat_col, self.lon_col}
        self.columns = {c: g.numeric(frame[c]).to_numpy(dtype=float) for c in g.numeric_columns(frame)}
        self.variables = [c for c in self.columns if c not in hidden]
        self.session = frame['session'].astype(str).to_numpy() if 'session' in frame else None
        self.rows = len(frame)
        self._local = {}
        utc = self.dates.to_numpy(dtype='datetime64[ms]').astype(np.int64).astype(float)
        steps = np.diff(utc)
        # Una pausa mayor que esto corta la línea (sin unir dos vuelos con una recta).
        self.gap_ms = max(20 * float(np.median(steps)), 10000.0) if len(steps) else 10000.0

    def local_ms(self, zone):
        """Hora local de la zona como milisegundos 'de reloj' (Plotly la muestra tal cual en el eje)."""
        if zone not in self._local:
            local = self.dates.dt.tz_convert(ZoneInfo(zone)).dt.tz_localize(None)
            ms = local.to_numpy(dtype='datetime64[ms]').astype(np.int64).astype(float)
            self._local[zone] = (ms, np.maximum.accumulate(ms))  # el acumulado sirve para buscar aunque haya cambio de horario
        return self._local[zone]

    def info(self):
        found = [find_gas(self.variables, gas) for gas in DEFAULT_GASES]
        return {'name': self.name, 'rows': self.rows, 'time_column': self.time_column, 'variables': self.variables,
                'defaults': [c for c in found if c], 'missing_gases': [gas.upper() for gas, c in zip(DEFAULT_GASES, found) if not c],
                'altitude': self.alt_col, 'gps': bool(self.lat_col and self.lon_col),
                'sheet': self.sheet, 'sheets': self.sheets}

    def values(self, name, limits=None):
        """Columna con los límites de saturación aplicados: lo que pasa del máximo queda en el máximo y lo que
        baja del mínimo queda en el mínimo (no se descarta ninguna muestra). limits = {nombre: (mínimo, máximo)},
        None en un lado = sin límite."""
        low, high = (limits or {}).get(name, (None, None))
        y = self.columns[name]
        if low is None and high is None:
            return y
        return np.clip(y, -np.inf if low is None else low, np.inf if high is None else high)

    def series(self, names, zone, start=None, end=None, width=1200, limits=None, original=False):
        t, sorted_t = self.local_ms(zone)
        i0 = int(np.searchsorted(sorted_t, start, 'left')) if start is not None else 0
        i1 = int(np.searchsorted(sorted_t, end, 'right')) if end is not None else len(t)
        # Un punto a cada lado del tramo para que la línea llegue a los bordes al hacer zoom.
        i0, i1 = max(i0 - 1, 0), min(i1 + 1, len(t))
        limits = limits or {}
        out = {}
        for name in names:
            if name not in self.columns:
                continue
            raw = self.columns[name]
            # Recortar no cambia qué muestra es la mínima o la máxima de cada grupo: se eligen sobre los datos originales.
            keep = minmax(raw, i0, i1, max(int(width), 50))
            xs = t[keep]
            breaks = np.nonzero(np.diff(xs) > self.gap_ms)[0] + 1
            line = lambda y: as_list(np.insert(y[keep], breaks, np.nan))
            out[name] = {'x': as_list(np.insert(xs, breaks, np.nan), 0), 'y': line(self.values(name, limits)),
                         'shown': int(len(keep)), 'total': int(i1 - i0)}
            if name in limits:
                low, high = limits[name]
                out[name].update(limits=[low, high], valid=int(np.isfinite(raw).sum()),
                                 below=int((raw < low).sum()) if low is not None else 0,
                                 above=int((raw > high).sum()) if high is not None else 0)
                if original:
                    out[name]['original'] = line(raw)
        return out

    def heat_samples(self, name, limits):
        """(lon, lat, valor ajustado, hora UTC, altura o None) de las muestras con GPS válido y valor."""
        if not (self.lat_col and self.lon_col):
            raise ValueError('Este archivo no tiene columnas de latitud/longitud: no se puede hacer el mapa de calor.')
        if name not in self.columns:
            raise ValueError(f'No existe la variable {name}.')
        lat, lon, values = self.columns[self.lat_col], self.columns[self.lon_col], self.values(name, limits)
        ok = np.asarray(g.gps_valid(pd.Series(lat), pd.Series(lon))) & np.isfinite(values)
        if not ok.any():
            raise ValueError(f'{name} no tiene muestras con GPS válido.')
        alt = self.columns[self.alt_col][ok] if self.alt_col else None
        return lon[ok], lat[ok], values[ok], self.dates[ok].dt.strftime('%Y-%m-%dT%H:%M:%SZ').to_numpy(), alt

    def heat(self, name, limits, bins=20, min_pct=5.0):
        """Escala por divisiones, tabla de porcentajes y muestras (para el 3D y para leer valores con el mouse)."""
        lon, lat, values, *_ = self.heat_samples(name, limits)
        edges, counts = mc.adaptive_classes(values, bins, min_pct)
        colors = mc.class_colors(len(counts))
        pick = np.arange(len(values))
        if len(pick) > MAX_HEAT_POINTS:
            pick = pick[np.linspace(0, len(pick) - 1, MAX_HEAT_POINTS).astype(int)]
        total = int(counts.sum())
        lons, lats = lon[pick], lat[pick]
        return {
            'name': name, 'samples': total, 'min': float(edges[0]), 'max': float(edges[-1]), 'limits': limits.get(name),
            'classes': [{'lo': float(edges[i]), 'hi': float(edges[i + 1]), 'count': int(n), 'pct': 100 * n / total,
                         'color': '#%02x%02x%02x' % tuple(int(k) for k in colors[i])} for i, n in enumerate(counts)],
            'bounds': [float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max())],
            'points': {'lon': as_list(lons, 7), 'lat': as_list(lats, 7), 'v': as_list(values[pick])},
        }

    def terrain(self, name, limits, bins=20, min_pct=5.0):
        """Lo mismo que heat() (escala y tabla) más, por muestra, la altura medida, la del terreno debajo (AWS Terrain
        Tiles, la misma fuente del relieve en la página) y la altura sobre el terreno, para dibujarla en el aire."""
        if not self.alt_col:
            raise ValueError('Este archivo no tiene columna de altura (altitud_m, altura_m...): no se puede ubicar cada muestra en el aire.')
        lon, lat, values, _, alt = self.heat_samples(name, limits)
        data = self.heat(name, limits, bins, min_pct)
        pick = np.arange(len(values))
        if len(pick) > MAX_HEAT_POINTS:
            pick = pick[np.linspace(0, len(pick) - 1, MAX_HEAT_POINTS).astype(int)]
        ground = terreno.elevation(lon[pick], lat[pick])
        above = alt[pick] - ground
        under = above < 0
        data['points'].update(alt=as_list(alt[pick], 2), ground=as_list(ground, 1), above=as_list(np.maximum(above, 0), 2))
        data['altitude'] = self.alt_col
        data['under'] = {'count': int(under.sum()), 'max': float(-np.nanmin(above)) if under.any() else 0.0}
        data['no_alt'] = int(np.isnan(alt[pick]).sum())
        return data

    def heat_image(self, name, limits, bins=20, min_pct=5.0, size_m=1.0, opacity=0.95, cool=1.0, reach=2.5, bbox=None, zoom=15.0, dpr=1.0):
        """PNG de la nube solo para la zona visible (bbox = oeste, sur, este, norte en grados) con la resolución de la
        pantalla: con nubes de 0,1–2 m se ve nítida con cualquier zoom."""
        lon, lat, values, *_ = self.heat_samples(name, limits)
        edges, _ = mc.adaptive_classes(values, bins, min_pct)
        west, south, east, north = bbox
        (xmin, xmax), (ymin, ymax) = (np.sort(a) for a in mc.mercator(np.array([west, east]), np.array([south, north])))
        res = 2 * np.pi * mc.EARTH / (512 * 2 ** float(zoom)) / max(float(dpr), 1.0)  # unidades de Web Mercator por píxel
        res = max(res, (xmax - xmin) / MAX_IMAGE_PX, (ymax - ymin) / MAX_IMAGE_PX)
        c = mc.cloud(lon, lat, values, edges, size_m, opacity, bounds=(xmin, ymin, xmax, ymax), res=res, cool=cool, reach=reach)
        from PIL import Image
        png = io.BytesIO()
        Image.fromarray(c['rgba'], 'RGBA').save(png, 'PNG')
        return {'image': 'data:image/png;base64,' + base64.b64encode(png.getvalue()).decode(), 'corners': c['corners']}

    def heat_zip(self, name, limits, bins=20, min_pct=5.0, size_m=1.0, opacity=0.95, cool=1.0, reach=2.5):
        """ZIP con la carpeta para QGIS: nube RGBA, valores por división, puntos y proyecto .qgz."""
        lon, lat, values, times, _ = self.heat_samples(name, limits)
        edges, _ = mc.adaptive_classes(values, bins, min_pct)
        base = re.sub(r'[^\w.-]+', '_', f'{self.name}_{name}').strip('_')
        buffer = io.BytesIO()
        with tempfile.TemporaryDirectory() as folder, zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in mc.export_cloud(folder, base, lon, lat, values, edges, size_m, opacity, times, f'{name} · {self.name}', cool, reach):
                archive.write(path, f'{base}/{path.name}')
        return base + '.zip', buffer.getvalue()

    def route(self, zone):
        if not (self.lat_col and self.lon_col):
            return None
        lat, lon = self.columns[self.lat_col], self.columns[self.lon_col]
        t, _ = self.local_ms(zone)
        valid = np.asarray(g.gps_valid(*(pd.Series(a) for a in (lat, lon))))
        cut = np.zeros(self.rows, dtype=bool)
        cut[1:] = (np.diff(t) > self.gap_ms) | ~valid[:-1]
        if self.session is not None:
            cut[1:] |= self.session[1:] != self.session[:-1]
        segment = np.cumsum(cut)
        idx = np.nonzero(valid)[0]
        if not len(idx):
            return None
        if len(idx) > MAX_ROUTE_POINTS:
            idx = idx[np.linspace(0, len(idx) - 1, MAX_ROUTE_POINTS).astype(int)]
        breaks = np.nonzero(np.diff(segment[idx]) != 0)[0] + 1
        pick = lambda a: as_list(np.insert(a[idx].astype(float), breaks, np.nan), 7)
        alt = self.columns.get(self.alt_col)
        return {'lat': pick(lat), 'lon': pick(lon), 't': pick(t), 'alt': pick(alt) if alt is not None else None,
                'lat0': float(np.nanmedian(lat[idx]))}


def parse_limits(text):
    """'{"co2_ppm": [300, null]}' -> {'co2_ppm': (300.0, None)}; mínimo mayor que máximo es un error."""
    limits = {}
    for name, pair in (json.loads(text) if text else {}).items():
        low, high = (None if v is None else float(v) for v in pair)
        if low is not None and high is not None and low > high:
            raise ValueError(f'En {name} el mínimo ({low:g}) es mayor que el máximo ({high:g}).')
        if low is not None or high is not None:
            limits[name] = (low, high)
    return limits


DATASETS: dict[str, Dataset] = {}


class Pages:
    """Páginas abiertas (cada una avisa con /api/ping y se despide con /api/bye); con --ventana el servidor se
    apaga cuando ya no queda ninguna, así la app de Windows se cierra al cerrar su ventana."""

    def __init__(self, now):
        self.seen = {}
        self.ever = False
        self.empty_since = now
        self.lock = threading.Lock()

    def ping(self, page, now):
        with self.lock:
            self.seen[page] = now
            self.ever = True

    def bye(self, page, now):
        with self.lock:
            if self.seen.pop(page, None) is not None and not self.seen:
                self.empty_since = now

    def closed(self, now):
        with self.lock:
            for page in [p for p, t in self.seen.items() if now - t > PAGE_TIMEOUT]:
                del self.seen[page]
                if not self.seen:
                    self.empty_since = now
            wait = CLOSE_GRACE if self.ever else FIRST_PAGE_TIMEOUT
            return not self.seen and now - self.empty_since >= wait


PAGES = Pages(time.monotonic())


def load(raw: bytes, name: str, sheet: str | None = None) -> tuple[str, Dataset]:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / (Path(name).name or 'datos.csv')
        path.write_bytes(raw)
        frame = g.load_csv(path, time_column='fecha_hora_utc', sheet=sheet)
    dataset = Dataset(frame, g.short_name(name))
    key = uuid.uuid4().hex
    DATASETS[key] = dataset
    for old in list(DATASETS)[:-KEEP_DATASETS]:
        DATASETS.pop(old)
    return key, dataset


class Handler(BaseHTTPRequestHandler):
    STATIC = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.png': 'image/png'}

    def reply(self, body, kind='application/json', status=200):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def fail(self, message, status=400):
        self.reply({'error': message}, status=status)

    def do_GET(self):
        url = urlparse(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == '/api/ping':
                PAGES.ping(query.get('page', ''), time.monotonic())
                return self.reply({})
            if url.path == '/api/zones':
                return self.reply(sorted(available_timezones()))
            if url.path in ('/api/series', '/api/route', '/api/heat', '/api/heat/image', '/api/heat.zip', '/api/terrain'):
                dataset = DATASETS.get(query.get('id', ''))
                if not dataset:
                    return self.fail('El archivo ya no está cargado; ábrelo de nuevo.', 404)
                zone = query.get('zone', g.DEFAULT_ZONE)
                ZoneInfo(zone)  # zona inválida -> error claro
                if url.path == '/api/route':
                    return self.reply(dataset.route(zone))
                number = lambda k: float(query[k]) if query.get(k) else None
                if url.path.startswith('/api/heat') or url.path == '/api/terrain':
                    scale = (query.get('var', ''), parse_limits(query.get('limits')), int(number('bins') or 20),
                             number('minpct') if number('minpct') is not None else 5.0)
                    look = (number('size') or 1.0, number('opacity') if number('opacity') is not None else 0.95,
                            number('cool') if number('cool') is not None else 1.0, number('reach') or 2.5)
                    if url.path == '/api/heat':
                        return self.reply(dataset.heat(*scale))
                    if url.path == '/api/terrain':
                        return self.reply(dataset.terrain(*scale))
                    if url.path == '/api/heat/image':
                        bbox = [float(v) for v in query.get('bbox', '').split(',')]
                        if len(bbox) != 4:
                            raise ValueError('Falta la zona visible (bbox).')
                        return self.reply(dataset.heat_image(*scale, *look, bbox, number('zoom') or 15, number('dpr') or 1))
                    options = (*scale, *look)
                    filename, body = dataset.heat_zip(*options)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/zip')
                    self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                names = [n for n in query.get('vars', '').split(',') if n]
                return self.reply(dataset.series(names, zone, number('start'), number('end'), number('width') or 1200,
                                                 parse_limits(query.get('limits')), query.get('original') == '1'))
            if url.path == '/plotly.min.js':
                import plotly
                return self.reply((Path(plotly.__file__).parent / 'package_data' / 'plotly.min.js').read_bytes(), self.STATIC['.js'])
            file = WEB_DIR / ('index.html' if url.path == '/' else url.path.lstrip('/'))
            if file.resolve().parent not in (WEB_DIR.resolve(), (WEB_DIR / 'vendor').resolve()) or not file.is_file() or file.suffix not in self.STATIC:
                return self.fail('No encontrado', 404)
            return self.reply(file.read_bytes(), self.STATIC[file.suffix])
        except (ValueError, KeyError) as exc:
            return self.fail(str(exc))

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == '/api/bye':
            PAGES.bye(parse_qs(url.query).get('page', [''])[-1], time.monotonic())
            return self.reply({})
        if url.path != '/api/upload':
            return self.fail('No encontrado', 404)
        size = int(self.headers.get('Content-Length') or 0)
        if not size or size > MAX_UPLOAD:
            return self.fail('El archivo está vacío o pesa más de 1 GB.')
        name = self.headers.get('X-Filename', 'datos.csv')
        try:
            sheet = self.headers.get('X-Sheet')  # hoja de Excel elegida en la página; sin ella, la de siempre
            key, dataset = load(self.rfile.read(size), unquote(name), unquote(sheet) if sheet else None)
        except ValueError as exc:
            return self.fail(str(exc))
        except Exception as exc:  # cualquier CSV raro: mostrar el motivo en la página en lugar de cortar la conexión
            return self.fail(f'No se pudo abrir el archivo: {exc}')
        return self.reply({'id': key, **dataset.info()})

    def log_message(self, *args):
        pass


def app_browser():
    """Edge o Chrome, que pueden mostrar la página como ventana propia (--app, sin pestañas ni barra de direcciones)."""
    for name in ('msedge', 'chrome', 'google-chrome', 'chromium', 'chromium-browser'):
        if path := shutil.which(name):
            return path
    for base in filter(None, (os.environ.get(v) for v in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA'))):
        for exe in (r'Microsoft\Edge\Application\msedge.exe', r'Google\Chrome\Application\chrome.exe'):
            if (path := Path(base, exe)).is_file():
                return str(path)
    return None


def open_window(url):
    browser = app_browser()
    if browser:
        try:
            subprocess.Popen([browser, f'--app={url}', '--window-size=1400,900'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    webbrowser.open(url)  # sin Edge ni Chrome: una pestaña del navegador predeterminado


def close_when_unused(server):
    while not PAGES.closed(time.monotonic()):
        time.sleep(1)
    server.shutdown()


def main():
    parser = argparse.ArgumentParser(description='GasLab 2.0 en el navegador.')
    parser.add_argument('--puerto', type=int, default=0, help='puerto local (0 = uno libre)')
    parser.add_argument('--sin-navegador', action='store_true', help='no abrir el navegador automáticamente')
    parser.add_argument('--ventana', action='store_true', default=getattr(sys, 'frozen', False),
                        help='abrir en una ventana propia (Edge o Chrome) y cerrar GasLab al cerrarla; siempre en el .exe')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.puerto), Handler)
    url = f'http://127.0.0.1:{server.server_address[1]}/'
    print(f'GasLab 2.0 en {url}  (Ctrl+C para cerrar)')
    if args.ventana:
        threading.Thread(target=close_when_unused, args=(server,), daemon=True).start()
    if not args.sin_navegador:
        threading.Timer(0.3, open_window if args.ventana else webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
