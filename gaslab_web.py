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
from urllib.parse import parse_qs, quote, unquote, urlparse
from zoneinfo import ZoneInfo, available_timezones

import numpy as np
import pandas as pd

import graficar as g
import kmz
import mapa_calor as mc
import terreno

WEB_DIR = Path(__file__).with_name('web')
DEFAULT_GASES = ('co2', 'so2', 'h2s')
SKIP_IN_DEFAULTS = ('temp', 'raw', 'mv', 'volt', 'current')  # p. ej. Sensor_CO2_Internal_Temp_Avg no es la concentración
MAX_ROUTE_POINTS = 20000
MAX_IMAGE_PX = 2600  # lado máximo de la imagen de la nube que se manda a la página
MAX_HEAT_POINTS = 15000  # muestras que se mandan para las barras 3D y para ver el valor con el mouse
MAX_FEATURES = 9000  # elementos por KMZ: Google Earth en el navegador importa como máximo 10 000
MAX_UPLOAD = 1 << 30
KEEP_DATASETS = 4  # archivos abiertos que se conservan en memoria (cada uno con su versión calibrada, si la tiene)
CAL_SUFFIX = '_cal'  # Flight_Data: 'Sensor_2_ppm_Avg_cal' es la versión calibrada de 'Sensor_2_ppm_Avg'
DRONE_WORDS = ('dron', 'drone', 'uav', 'dji')  # 'latitud_dron', 'drone_lat', 'UAV Longitude'...
LAT_WORDS, LON_WORDS = ('lat', 'latitud', 'latitude'), ('lon', 'lng', 'long', 'longitud', 'longitude')
ALT_WORDS = ('alt', 'altitud', 'altitude', 'altura', 'height')
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


def drone_columns(columns):
    """{'lat', 'lon', 'alt'} con las columnas del GPS del dron, o None si no están latitud y longitud. Para la altura
    se prefiere la absoluta ('altitud_dron_m') a la relativa al despegue ('altura_relativa_dron_m')."""
    words = {c: re.split(r'[^a-z0-9]+', c.lower()) for c in columns}
    drone = [c for c, w in words.items() if any(x in DRONE_WORDS for x in w)]
    find = lambda options, avoid=(): next((c for c in drone if any(x in options for x in words[c]) and not any(x in avoid for x in words[c])), None)
    found = {'lat': find(LAT_WORDS), 'lon': find(LON_WORDS), 'alt': find(ALT_WORDS, ('relativa', 'relative', 'rel')) or find(ALT_WORDS)}
    return found if found['lat'] and found['lon'] else None


def distance_m(lat1, lon1, lat2, lon2):
    """Distancia aproximada en metros (plano local; sobra para separaciones de metros a kilómetros)."""
    k = np.pi / 180 * 6371000
    return np.hypot((lat2 - lat1) * k, (lon2 - lon1) * k * np.cos(np.radians((lat1 + lat2) / 2)))


def attachment(filename):
    """Content-Disposition que aguanta acentos en el nombre."""
    plain = filename.encode('ascii', 'replace').decode().replace('?', '_').replace('"', '')
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(filename)}"


def as_list(values, digits=6):
    """Lista JSON con None en lugar de NaN."""
    values = np.round(np.asarray(values, dtype=float), digits)
    return [None if v != v else v for v in values.tolist()]


class Dataset:
    def __init__(self, frame, name):
        self.name = name
        self.cal_id, self.calibrated, self.cal_vars = None, False, set()  # load() los llena si hay columnas '_cal'
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
        self.drone = drone_columns(frame.columns)  # GPS del dron, si el archivo lo trae
        hidden = {self.time_column, self.lat_col, self.lon_col, *((self.drone['lat'], self.drone['lon']) if self.drone else ())}
        self.columns = {c: g.numeric(frame[c]).to_numpy(dtype=float) for c in g.numeric_columns(frame)}
        if self.drone and not (self.drone['lat'] in self.columns and self.drone['lon'] in self.columns):
            self.drone = None  # columnas del dron vacías
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

    def window(self, zone, w0=None, w1=None):
        """(primera fila, fila final exclusiva) del tramo elegido; w0/w1 en ms 'de reloj' de la zona. None = todo."""
        if w0 is None and w1 is None:
            return None
        _, sorted_t = self.local_ms(zone)
        lo = int(np.searchsorted(sorted_t, w0, 'left')) if w0 is not None else 0
        hi = int(np.searchsorted(sorted_t, w1, 'right')) if w1 is not None else self.rows
        if hi <= lo:
            raise ValueError('No hay muestras en el tramo elegido.')
        return lo, hi

    def tramos(self, zone, gap_s=1200):
        """Como la versión 1: tramos continuos (una pausa mayor a gap_s segundos abre uno nuevo) y los días con sus
        horas con mediciones, para elegir 'Día de … a …'. Tiempos en ms 'de reloj' de la zona."""
        t, _ = self.local_ms(zone)
        utc = self.dates.to_numpy(dtype='datetime64[ms]').astype(np.int64)
        cuts = np.flatnonzero(np.diff(utc) > float(gap_s) * 1000) + 1
        starts, ends = np.concatenate(([0], cuts)), np.concatenate((cuts, [self.rows]))
        tramos = [{'t0': float(t[a]), 't1': float(t[b - 1]), 'rows': int(b - a), 'seconds': float((utc[b - 1] - utc[a]) / 1000)}
                  for a, b in zip(starts.tolist(), ends.tolist())]
        hours = np.unique((t // 3600000).astype(np.int64))
        days = {}
        for h in hours.tolist():
            days.setdefault(h // 24, []).append(h % 24)
        return {'tramos': tramos, 'days': [{'t0': float(d * 86400000), 'hours': hs} for d, hs in days.items()]}

    def info(self):
        found = [find_gas(self.variables, gas) for gas in DEFAULT_GASES]
        return {'name': self.name, 'rows': self.rows, 'time_column': self.time_column, 'variables': self.variables,
                'defaults': [c for c in found if c], 'missing_gases': [gas.upper() for gas, c in zip(DEFAULT_GASES, found) if not c],
                'altitude': self.alt_col, 'gps': bool(self.lat_col and self.lon_col),
                'sheet': self.sheet, 'sheets': self.sheets, 'cal_id': self.cal_id, 'drone': self.drone_info()}

    def gps_columns(self, gps='sensor'):
        """(latitud, longitud, altura) de la fuente elegida: 'sensor' (latitud/longitud del archivo) o 'dron'.
        Si el dron no trae altura se usa la del archivo."""
        if gps == 'dron':
            if not self.drone:
                raise ValueError('Este archivo no tiene columnas con el GPS del dron.')
            return self.drone['lat'], self.drone['lon'], self.drone['alt'] or self.alt_col
        if gps != 'sensor':
            raise ValueError(f'Fuente de GPS desconocida: {gps}.')
        return self.lat_col, self.lon_col, self.alt_col

    def drone_info(self):
        """Columnas del dron, cuántas filas tienen posición y la distancia al GPS del sensor donde están los dos."""
        if not self.drone:
            return None
        valid = lambda lat, lon: np.asarray(g.gps_valid(pd.Series(self.columns[lat]), pd.Series(self.columns[lon])))
        ok = valid(self.drone['lat'], self.drone['lon'])
        gap = None
        if self.lat_col and self.lon_col:
            both = ok & valid(self.lat_col, self.lon_col)
            if both.any():
                d = distance_m(*(self.columns[c][both] for c in (self.lat_col, self.lon_col, self.drone['lat'], self.drone['lon'])))
                gap = {'mean': float(d.mean()), 'median': float(np.median(d)), 'max': float(d.max()), 'rows': int(both.sum())}
        return {**self.drone, 'rows': int(ok.sum()), 'gap': gap}

    def values(self, name, limits=None):
        """Columna con los límites de saturación aplicados: lo que pasa del máximo queda en el máximo y lo que
        baja del mínimo queda en el mínimo (no se descarta ninguna muestra). limits = {nombre: (mínimo, máximo)},
        None en un lado = sin límite."""
        low, high = (limits or {}).get(name, (None, None))
        y = self.columns[name]
        if low is None and high is None:
            return y
        return np.clip(y, -np.inf if low is None else low, np.inf if high is None else high)

    def series(self, names, zone, start=None, end=None, width=1200, limits=None, original=False, other=None, window=None):
        """Series reducidas al ancho de la gráfica. other: la otra versión del mismo archivo (original o calibrada);
        para las variables que tienen '_cal' se agrega 'compare' con sus valores en las mismas muestras y 'diff'
        con la diferencia esta − otra en el tramo visible."""
        t, sorted_t = self.local_ms(zone)
        i0 = int(np.searchsorted(sorted_t, start, 'left')) if start is not None else 0
        i1 = int(np.searchsorted(sorted_t, end, 'right')) if end is not None else len(t)
        # Un punto a cada lado del tramo para que la línea llegue a los bordes al hacer zoom.
        i0, i1 = max(i0 - 1, 0), min(i1 + 1, len(t))
        if window:  # tramo elegido: las curvas solo tienen sus muestras
            i0, i1 = max(i0, window[0]), min(i1, window[1])
            i1 = max(i1, i0)
        limits = limits or {}
        out = {}
        for name in names:
            if name not in self.columns:
                continue
            raw = self.columns[name]
            paired = other is not None and name in self.cal_vars and name in other.columns
            # Recortar no cambia qué muestra es la mínima o la máxima de cada grupo: se eligen sobre los datos originales.
            keep = minmax(raw, i0, i1, max(int(width), 50))
            if paired:  # también los extremos de la otra versión, para que ninguna de las dos pierda picos
                keep = np.union1d(keep, minmax(other.columns[name], i0, i1, max(int(width), 50)))
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
            if paired:
                out[name]['compare'] = line(other.values(name, limits))
                diff = (raw - other.columns[name])[i0:i1]
                diff = diff[np.isfinite(diff)]
                out[name]['diff'] = {'mean': float(diff.mean()), 'max': float(diff[np.abs(diff).argmax()])} if len(diff) else None
        return out

    def heat_samples(self, name, limits, gps='sensor', window=None):
        """(lon, lat, valor ajustado, hora UTC, altura o None) de las muestras con GPS válido y valor."""
        lat_col, lon_col, alt_col = self.gps_columns(gps)
        if not (lat_col and lon_col):
            raise ValueError('Este archivo no tiene columnas de latitud/longitud: no se puede hacer el mapa de calor.')
        if name not in self.columns:
            raise ValueError(f'No existe la variable {name}.')
        lat, lon, values = self.columns[lat_col], self.columns[lon_col], self.values(name, limits)
        ok = np.asarray(g.gps_valid(pd.Series(lat), pd.Series(lon))) & np.isfinite(values)
        if window:
            ok[:window[0]] = ok[window[1]:] = False
        if not ok.any():
            raise ValueError(f'{name} no tiene muestras con GPS {"del dron " if gps == "dron" else ""}válido{" en este tramo" if window else ""}.')
        alt = self.columns[alt_col][ok] if alt_col in self.columns else None
        return lon[ok], lat[ok], values[ok], self.dates[ok].dt.strftime('%Y-%m-%dT%H:%M:%SZ').to_numpy(), alt

    def heat(self, name, limits, bins=20, min_pct=0.0, spacing='original', gps='sensor', window=None):
        """Escala por divisiones, tabla de porcentajes y muestras (para el 3D y para leer valores con el mouse)."""
        lon, lat, values, *_ = self.heat_samples(name, limits, gps, window)
        edges, counts = mc.adaptive_classes(values, bins, min_pct, spacing)
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

    def terrain(self, name, limits, bins=20, min_pct=0.0, spacing='original', gps='sensor', window=None):
        """Lo mismo que heat() (escala y tabla) más, por muestra, la altura medida, la del terreno debajo (AWS Terrain
        Tiles, la misma fuente del relieve en la página) y la altura sobre el terreno, para dibujarla en el aire. Sin
        columna de altura, 'altitude' es None y la página pega las muestras al terreno. El desfase de altura y el modo
        pegado se aplican en la página."""
        alt_col = self.gps_columns(gps)[2]
        lon, lat, values, _, alt = self.heat_samples(name, limits, gps, window)
        data = self.heat(name, limits, bins, min_pct, spacing, gps, window)
        pick = np.arange(len(values))
        if len(pick) > MAX_HEAT_POINTS:
            pick = pick[np.linspace(0, len(pick) - 1, MAX_HEAT_POINTS).astype(int)]
        ground = terreno.elevation(lon[pick], lat[pick])
        alt = alt[pick] if alt is not None else np.full(len(pick), np.nan)
        above = alt - ground
        under = above < 0
        data['points'].update(alt=as_list(alt, 2), ground=as_list(ground, 1), above=as_list(np.maximum(above, 0), 2))
        data['altitude'] = alt_col if alt_col in self.columns else None
        data['under'] = {'count': int(under.sum()), 'max': float(-np.nanmin(above)) if under.any() else 0.0}
        data['no_alt'] = int(np.isnan(alt).sum())
        return data

    def heat_image(self, name, limits, bins=20, min_pct=0.0, spacing='original', size_m=1.0, opacity=0.95, cool=1.0, reach=2.5, bbox=None, zoom=15.0, dpr=1.0, gps='sensor', window=None):
        """PNG de la nube solo para la zona visible (bbox = oeste, sur, este, norte en grados) con la resolución de la
        pantalla: con nubes de 0,1–2 m se ve nítida con cualquier zoom."""
        lon, lat, values, *_ = self.heat_samples(name, limits, gps, window)
        edges, _ = mc.adaptive_classes(values, bins, min_pct, spacing)
        west, south, east, north = bbox
        (xmin, xmax), (ymin, ymax) = (np.sort(a) for a in mc.mercator(np.array([west, east]), np.array([south, north])))
        res = 2 * np.pi * mc.EARTH / (512 * 2 ** float(zoom)) / max(float(dpr), 1.0)  # unidades de Web Mercator por píxel
        res = max(res, (xmax - xmin) / MAX_IMAGE_PX, (ymax - ymin) / MAX_IMAGE_PX)
        c = mc.cloud(lon, lat, values, edges, size_m, opacity, bounds=(xmin, ymin, xmax, ymax), res=res, cool=cool, reach=reach)
        from PIL import Image
        png = io.BytesIO()
        Image.fromarray(c['rgba'], 'RGBA').save(png, 'PNG')
        return {'image': 'data:image/png;base64,' + base64.b64encode(png.getvalue()).decode(), 'corners': c['corners']}

    def heat_zip(self, name, limits, bins=20, min_pct=0.0, spacing='original', size_m=1.0, opacity=0.95, cool=1.0, reach=2.5, gps='sensor', window=None):
        """ZIP con la carpeta para QGIS: nube RGBA, valores por división, puntos y proyecto .qgz."""
        lon, lat, values, times, _ = self.heat_samples(name, limits, gps, window)
        edges, _ = mc.adaptive_classes(values, bins, min_pct, spacing)
        base = re.sub(r'[^\w.-]+', '_', f'{self.name}_{name}').strip('_')
        buffer = io.BytesIO()
        with tempfile.TemporaryDirectory() as folder, zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in mc.export_cloud(folder, base, lon, lat, values, edges, size_m, opacity, times, f'{name} · {self.name}', cool, reach):
                archive.write(path, f'{base}/{path.name}')
        return base + '.zip', buffer.getvalue()

    def route(self, zone, gps='sensor', window=None):
        lat_col, lon_col, alt_col = self.gps_columns(gps)
        if not (lat_col and lon_col):
            return None
        lat, lon = self.columns[lat_col], self.columns[lon_col]
        t, _ = self.local_ms(zone)
        valid = np.asarray(g.gps_valid(*(pd.Series(a) for a in (lat, lon))))
        cut = np.zeros(self.rows, dtype=bool)
        cut[1:] = (np.diff(t) > self.gap_ms) | ~valid[:-1]
        if self.session is not None:
            cut[1:] |= self.session[1:] != self.session[:-1]
        segment = np.cumsum(cut)
        idx = np.nonzero(valid)[0]
        if window:
            idx = idx[(idx >= window[0]) & (idx < window[1])]
        if not len(idx):
            return None
        if len(idx) > MAX_ROUTE_POINTS:
            idx = idx[np.linspace(0, len(idx) - 1, MAX_ROUTE_POINTS).astype(int)]
        breaks = np.nonzero(np.diff(segment[idx]) != 0)[0] + 1
        pick = lambda a: as_list(np.insert(a[idx].astype(float), breaks, np.nan), 7)
        alt = self.columns.get(alt_col)
        return {'lat': pick(lat), 'lon': pick(lon), 't': pick(t), 'alt': pick(alt) if alt is not None else None,
                'lat0': float(np.nanmedian(lat[idx]))}

    def route_segments(self, gps='sensor', window=None):
        """Ruta para el KMZ: segmentos sin pausas ni huecos de GPS, con lon, lat y hora UTC (ISO)."""
        lat_col, lon_col, _ = self.gps_columns(gps)
        if not (lat_col and lon_col):
            return []
        lat, lon = self.columns[lat_col], self.columns[lon_col]
        utc = self.dates.to_numpy(dtype='datetime64[ms]').astype(np.int64)
        valid = np.asarray(g.gps_valid(pd.Series(lat), pd.Series(lon)))
        cut = np.zeros(self.rows, dtype=bool)
        cut[1:] = (np.diff(utc) > self.gap_ms) | ~valid[:-1]
        if self.session is not None:
            cut[1:] |= self.session[1:] != self.session[:-1]
        segment = np.cumsum(cut)
        idx = np.nonzero(valid)[0]
        if window:
            idx = idx[(idx >= window[0]) & (idx < window[1])]
        if len(idx) > MAX_ROUTE_POINTS:
            idx = idx[np.linspace(0, len(idx) - 1, MAX_ROUTE_POINTS).astype(int)]
        when = self.dates.dt.strftime('%Y-%m-%dT%H:%M:%SZ').to_numpy()
        out = []
        for part in np.split(idx, np.nonzero(np.diff(segment[idx]))[0] + 1):
            if len(part):
                out.append({'lon': lon[part].tolist(), 'lat': lat[part].tolist(), 'when': when[part].tolist()})
        return out

    def kmz_routes(self, gps, window):
        """[(nombre, clave de color, segmentos)]: la del GPS elegido, o las dos con 'ambos'."""
        sources = ('dron', 'sensor') if gps == 'ambos' else (gps,)
        names = {'sensor': 'GPS del sensor', 'dron': 'GPS del dron'}
        return [(names[s], s, self.route_segments(s, window)) for s in sources]

    def kmz(self, kind, name=None, limits=None, bins=20, min_pct=0.0, spacing='original', look=(1.0, 0.95, 1.0, 2.5), gps='sensor', window=None,
            bars=(100.0, 2.0), mode='measured', offset=0.0, tag=''):
        """(nombre, bytes) del KMZ para Google Earth.
        kind 'route': la ruta (paso 1). Paso 3, según la vista: 'heat' (2D) = nube, leyenda y ruta; 'bars' (3D) = barras,
        leyenda y ruta. 'terrain': puntos a su altura (mode 'measured' = medida + offset, 'ground' = pegados al terreno, offset sobre
        él), leyenda y ruta (paso 4). gps: 'sensor', 'dron' o 'ambos' (solo cambia la ruta; los mapas usan el dron)."""
        suffix = {'route': '', 'heat': '', 'bars': 'barras3d', 'terrain': '3d'}[kind]
        base = re.sub(r'[^\w.-]+', '_', '_'.join(filter(None, (self.name, name if kind != 'route' else 'ruta', suffix, tag)))).strip('_')
        title = f'{self.name} · ' + ({'route': 'ruta GPS', 'heat': f'mapa de calor de {name}', 'bars': f'barras 3D de {name}',
                                      'terrain': f'{name} en 3D'}[kind])
        routes = self.kmz_routes(gps, window)
        if kind == 'route':
            if not any(segs for _, _, segs in routes):
                raise ValueError('No hay posiciones GPS válidas para exportar la ruta.')
            return base + '.kmz', kmz.build(title, [kmz.route_kml(routes)], {})
        source = 'dron' if gps in ('dron', 'ambos') else 'sensor'
        lon, lat, values, times, alt = self.heat_samples(name, limits, source, window)
        edges, counts = mc.adaptive_classes(values, bins, min_pct, spacing)
        colors = ['#%02x%02x%02x' % tuple(int(k) for k in c) for c in mc.class_colors(len(counts))]
        total = int(counts.sum())
        classes = [{'lo': float(edges[i]), 'hi': float(edges[i + 1]), 'pct': 100 * n / total, 'color': colors[i]} for i, n in enumerate(counts)]
        klass = mc.class_of(values, edges)
        # Muestras (o barras) repartidas a lo largo del tramo hasta quedar bajo el límite de Google Earth en el navegador.
        limit = MAX_FEATURES
        pick = np.arange(len(values))
        if len(pick) > limit:
            pick = pick[np.linspace(0, len(pick) - 1, limit).astype(int)]
        files = {}
        parts = [kmz.legend_kml(name, classes, float(lon.min()), float(lat.max()))]  # esquina noroeste de los datos
        sample = lambda a: a[pick] if a is not None else None
        if kind == 'heat':
            size_m, opacity, cool, reach = look
            cloud = mc.cloud(lon, lat, values, edges, size_m, opacity, cool=cool, reach=reach)
            files['files/nube.png'], bounds = kmz.overlay_png(cloud['rgba'], cloud['corners'])
            parts.append(kmz.overlay_kml(bounds))
        elif kind == 'bars':
            parts.append(kmz.bars_kml(name, sample(lon), sample(lat), sample(values), sample(klass), float(edges[0]), float(edges[-1]), *bars, visible=True))
        else:
            if mode == 'ground' or alt is None:
                heights, how, extrude = np.full(len(pick), max(offset, 0.0)), 'relativeToGround', offset > 0
                notes = [f'<br>Pegada al terreno{f", {offset:g} m sobre él" if offset > 0 else ""}'] * len(pick)
            else:
                heights, how, extrude = alt[pick] + offset, 'absolute', True
                notes = [f'<br>Altura: {h:.1f} m' + (f' (medida {a:.1f} m, desfase {offset:+g} m)' if offset else '') for h, a in zip(heights, alt[pick])]
            parts.append(kmz.points_kml(name, 'Muestras en 3D', sample(lon), sample(lat), sample(values), sample(klass), sample(times),
                                        heights, how, extrude, notes=notes))
        parts.append(kmz.route_kml(routes))
        return base + '.kmz', kmz.build(title, parts, files, kmz.styles_kml(colors))

    def excel_parts(self, names, zone, start=None, end=None, gps='sensor', tag='', limits=None):
        """Lo que va al libro Excel: variables elegidas, tramo visible (start/end en ms 'de reloj' de la zona) y GPS.
        gps: 'sensor', 'dron' o 'ambos' (las dos posiciones en Datos; la hoja Ruta usa la del dron).
        limits: los del paso 2 ({nombre: (mínimo, máximo)}); las variables van ya ajustadas, como en los mapas."""
        names = [n for n in names if n in self.columns]
        if not names:
            raise ValueError('Marca al menos una variable para exportar (paso 1).')
        _, sorted_t = self.local_ms(zone)
        i0 = int(np.searchsorted(sorted_t, start, 'left')) if start is not None else 0
        i1 = int(np.searchsorted(sorted_t, end, 'right')) if end is not None else self.rows
        if i1 <= i0:
            raise ValueError('No hay muestras en el tramo elegido.')
        route = self.gps_columns('dron' if gps == 'ambos' else gps)
        place = [c for c in (*route, *(self.gps_columns('sensor') if gps == 'ambos' else ())) if c in self.columns and c not in names]
        frame = pd.DataFrame({'fecha_hora_utc': self.dates.iloc[i0:i1].reset_index(drop=True),
                              **{c: (self.values(c, limits) if c in names else self.columns[c])[i0:i1] for c in dict.fromkeys(names + place)}})
        stamp = ('_' + tag if tag else '') + ('' if start is None and end is None else '_' + self.dates.iloc[i0].tz_convert(ZoneInfo(zone)).strftime('%Y%m%d_%H%M'))
        filename = re.sub(r'[^\w.-]+', '_', self.name + ('_calibrado' if self.calibrated else '') + stamp).strip('_') + '.xlsx'
        used = {n: limits[n] for n in names if n in (limits or {})}
        bounds = ', '.join(f'{n} ' + ' y '.join(t for t in (low is not None and f'mín {low:g}', high is not None and f'máx {high:g}') if t)
                           for n, (low, high) in used.items())
        options = dict(columns=names, time_column='fecha_hora_utc', zone=zone,
                       title=self.name + (' · calibrado' if self.calibrated else '') + (f' · límites: {bounds}' if bounds else ''),
                       gps=route[:2] if route[0] and route[1] and route[0] in self.columns else None, also=place,
                       route_name='Ruta GPS del dron' if gps in ('dron', 'ambos') else 'Ruta GPS')
        return frame, filename, options, (i0, i1)

    def excel(self, names, zone, start=None, end=None, gps='sensor', tag='', limits=None):
        """(nombre, bytes) del libro Excel de la versión 1: Resumen, Datos, Gráficas (una por variable) y Ruta."""
        frame, filename, options, _ = self.excel_parts(names, zone, start, end, gps, tag, limits)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'datos.xlsx'
            g.make_excel(frame, path, **options)
            return filename, path.read_bytes()

    def excel_preview(self, names, zone, start=None, end=None, gps='sensor', tag='', limits=None, rows=30):
        """Lo mismo que tendrá el Excel, para verlo en la página antes de descargarlo: el Resumen completo, las
        primeras filas de Datos, las gráficas (reducidas al ancho) y la ruta."""
        frame, filename, options, (i0, i1) = self.excel_parts(names, zone, start, end, gps, tag, limits)
        names = options['columns']
        local = frame['fecha_hora_utc'].dt.tz_convert(ZoneInfo(zone))
        elapsed = (frame['fecha_hora_utc'] - frame['fecha_hora_utc'].iloc[0]).dt.total_seconds()
        lat_col, lon_col = options['gps'] or (None, None)
        alt = g.altitude_column(frame.columns)
        data_cols = names + list(dict.fromkeys(c for c in (lat_col, lon_col, *options['also'], alt) if c and c in frame and c not in names))
        head = lambda k: [local.iloc[k].strftime('%d/%m/%Y %H:%M:%S'), round(float(elapsed.iloc[k]), 3), *as_list([frame[c].iloc[k] for c in data_cols])]
        stats = []
        for name in names:
            v = frame[name].to_numpy(dtype=float)
            v = v[np.isfinite(v)]
            stats.append({'name': name, 'min': float(v.min()) if len(v) else None, 'mean': float(v.mean()) if len(v) else None,
                          'max': float(v.max()) if len(v) else None, 'count': int(len(v))})
        secs = int((frame['fecha_hora_utc'].iloc[-1] - frame['fecha_hora_utc'].iloc[0]).total_seconds())
        route = None
        if lat_col:
            lat, lon = frame[lat_col].to_numpy(dtype=float), frame[lon_col].to_numpy(dtype=float)
            ok = np.nonzero(np.asarray(g.gps_valid(pd.Series(lat), pd.Series(lon))))[0]
            if len(ok):
                ok = ok[np.linspace(0, len(ok) - 1, min(len(ok), 3000)).astype(int)]
                route = {'name': options['route_name'], 'lat': as_list(lat[ok], 7), 'lon': as_list(lon[ok], 7)}
        t, _ = self.local_ms(zone)
        series = self.series(names, zone, t[i0], t[i1 - 1], 600, limits=limits)
        return {'filename': filename, 'title': options['title'], 'zone': zone, 'rows': len(frame),
                'from': local.iloc[0].strftime('%d/%m/%Y %H:%M:%S'), 'to': local.iloc[-1].strftime('%d/%m/%Y %H:%M:%S'),
                'duration': f'{secs // 3600} h {secs % 3600 // 60:02d} min {secs % 60:02d} s', 'stats': stats,
                'headers': [f'Fecha y hora ({zone})', 'Transcurrido (s)', *data_cols],
                'first': [head(k) for k in range(min(rows, len(frame)))],
                'last': [head(k) for k in range(max(rows, len(frame) - 3), len(frame))],
                'charts': {n: {'x': series[n]['x'], 'y': series[n]['y']} for n in names if n in series}, 'route': route}


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


def calibration_pairs(frame):
    """{columna: columna_cal} de las columnas que vienen también calibradas. El nombre original pudo haberse
    normalizado al cargar ('Latitude' -> 'latitud') mientras que 'Latitude_cal' queda igual."""
    pairs = {}
    for column in frame.columns:
        if column.lower().endswith(CAL_SUFFIX):
            base = column[:-len(CAL_SUFFIX)]
            base = base if base in frame else g.canonical_name(base)
            if base in frame and base not in pairs:
                pairs[base] = column
    return pairs


def with_calibration(frame, pairs, calibrated):
    """El archivo con un solo juego de columnas y los nombres sin '_cal': las calibradas o las originales."""
    attrs = dict(frame.attrs)
    if calibrated:
        frame = frame.assign(**{base: frame[cal] for base, cal in pairs.items()})
    frame = frame.drop(columns=list(pairs.values()))
    frame.attrs.update(attrs)
    return frame


def load(raw: bytes, name: str, sheet: str | None = None) -> tuple[str, Dataset]:
    """Abre el archivo; si trae columnas '_cal' guarda también la versión calibrada, con su propio id (dataset.cal_id)
    y los mismos nombres de variables, para que la página cambie de una a otra sin perder la selección."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / (Path(name).name or 'datos.csv')
        path.write_bytes(raw)
        frame = g.load_csv(path, time_column='fecha_hora_utc', sheet=sheet)
    pairs = calibration_pairs(frame)
    dataset = Dataset(with_calibration(frame, pairs, False), g.short_name(name))
    key = uuid.uuid4().hex
    DATASETS[key] = dataset
    if pairs:
        calibrated = Dataset(with_calibration(frame, pairs, True), g.short_name(name))
        calibrated.calibrated = True
        dataset.cal_vars = calibrated.cal_vars = set(pairs)
        dataset.cal_id = calibrated.cal_id = key + '-cal'
        DATASETS[key + '-cal'] = calibrated
    files = list(dict.fromkeys(k.split('-')[0] for k in DATASETS))
    for old in files[:-KEEP_DATASETS]:
        DATASETS.pop(old, None)
        DATASETS.pop(old + '-cal', None)
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

    def download(self, filename, body, kind):
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Disposition', attachment(filename))
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
            if url.path in ('/api/series', '/api/route', '/api/heat', '/api/heat/image', '/api/heat.zip', '/api/terrain', '/api/excel', '/api/excel/preview', '/api/tramos', '/api/kmz'):
                dataset = DATASETS.get(query.get('id', ''))
                if not dataset:
                    return self.fail('El archivo ya no está cargado; ábrelo de nuevo.', 404)
                zone = query.get('zone', g.DEFAULT_ZONE)
                ZoneInfo(zone)  # zona inválida -> error claro
                gps = query.get('gps', 'sensor')  # posiciones de los mapas: 'sensor' o 'dron'
                number = lambda k: float(query[k]) if query.get(k) else None
                window = dataset.window(zone, number('w0'), number('w1'))  # tramo elegido (w0/w1), o None
                spacing = query.get('spacing') if query.get('spacing') in mc.SPACINGS else 'original'  # divisiones de la escala
                # % mínimo por división: sin valor, el de cada escala (5 % en Original, como antes; 0 % en las demás)
                min_pct = number('minpct') if number('minpct') is not None else mc.ORIGINAL_MIN_PCT if spacing == 'original' else 0.0
                if url.path == '/api/tramos':
                    return self.reply(dataset.tramos(zone, number('gap') or 1200))
                if url.path == '/api/route':
                    return self.reply(dataset.route(zone, gps, window))
                if url.path.startswith('/api/excel'):
                    tag = re.sub(r'[^\w-]+', '', query.get('tag', ''))[:20]
                    excel = ([n for n in query.get('vars', '').split(',') if n], zone, number('start'), number('end'), gps, tag,
                             parse_limits(query.get('limits')))
                    if url.path == '/api/excel/preview':
                        return self.reply(dataset.excel_preview(*excel))
                    filename, body = dataset.excel(*excel)
                    return self.download(filename, body, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                if url.path == '/api/kmz':
                    kind = query.get('kind', 'heat')
                    if kind not in ('route', 'heat', 'bars', 'terrain'):
                        raise ValueError(f'Exportación KMZ desconocida: {kind}.')
                    look = (number('size') or 1.0, number('opacity') if number('opacity') is not None else 0.95,
                            number('cool') if number('cool') is not None else 1.0, number('reach') or 2.5)
                    filename, body = dataset.kmz(kind, query.get('var'), parse_limits(query.get('limits')), int(number('bins') or 20),
                                                 min_pct, spacing, look, gps, window,
                                                 (number('barh') or 100.0, number('barw') or 2.0), query.get('mode', 'measured'),
                                                 number('offset') or 0.0, re.sub(r'[^\w-]+', '', query.get('tag', ''))[:20])
                    return self.download(filename, body, 'application/vnd.google-earth.kmz')
                if url.path.startswith('/api/heat') or url.path == '/api/terrain':
                    scale = (query.get('var', ''), parse_limits(query.get('limits')), int(number('bins') or 20),
                             min_pct, spacing)
                    look = (number('size') or 1.0, number('opacity') if number('opacity') is not None else 0.95,
                            number('cool') if number('cool') is not None else 1.0, number('reach') or 2.5)
                    if url.path == '/api/heat':
                        return self.reply(dataset.heat(*scale, gps=gps, window=window))
                    if url.path == '/api/terrain':
                        return self.reply(dataset.terrain(*scale, gps=gps, window=window))
                    if url.path == '/api/heat/image':
                        bbox = [float(v) for v in query.get('bbox', '').split(',')]
                        if len(bbox) != 4:
                            raise ValueError('Falta la zona visible (bbox).')
                        return self.reply(dataset.heat_image(*scale, *look, bbox, number('zoom') or 15, number('dpr') or 1, gps=gps, window=window))
                    filename, body = dataset.heat_zip(*scale, *look, gps=gps, window=window)
                    return self.download(filename, body, 'application/zip')
                names = [n for n in query.get('vars', '').split(',') if n]
                other = DATASETS.get(query.get('compare', ''))  # modo Comparación: la otra versión del archivo
                return self.reply(dataset.series(names, zone, number('start'), number('end'), number('width') or 1200,
                                                 parse_limits(query.get('limits')), query.get('original') == '1', other, window))
            if url.path == '/plotly.min.js':
                bundled = WEB_DIR / 'vendor' / 'plotly.min.js'  # la APK de Android lo trae aquí, sin el paquete plotly
                if bundled.is_file():
                    return self.reply(bundled.read_bytes(), self.STATIC['.js'])
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
