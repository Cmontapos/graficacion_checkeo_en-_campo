#!/usr/bin/env python3
"""Graficador local de CSV MicroGas. Sin argumentos abre la interfaz gráfica."""
from __future__ import annotations

import argparse
import csv
import html
import io
import re
import sys
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

TIME_COLUMNS = ('fecha_hora_utc', 'sen66_muestra_utc', 'received_at_ms', 'timestamp', 'time', 'datetime')
LAT_COLUMNS = ('latitud', 'latitude', 'lat')
LON_COLUMNS = ('longitud', 'longitude', 'lon', 'lng')
GPS_NAMES = set(LAT_COLUMNS + LON_COLUMNS)
PALETTE = ('#007f86', '#d95f02', '#7570b3', '#e7298a', '#66a61e', '#e6ab02', '#a6761d', '#1f78b4', '#b2182b', '#8c564b')
DEFAULT_ZONE = 'UTC'
DRONE_GPS = ('latitud_dron', 'longitud_dron')  # columnas opcionales con el GPS del dron
# Nombres alternativos de otros equipos (Campbell, GPS, exportaciones de hojas de cálculo) -> nombre que usa la app.
# Se comparan simplificados: minúsculas, sin acentos y '_' en lugar de espacios o símbolos ('CO2 (ppm)' -> 'co2_ppm').
COLUMN_ALIASES = {
    'timestamp': ('timestamp', 'time_stamp', 'date_time', 'fecha_hora', 'fecha_y_hora'),
    'latitud': ('latitud', 'latitude', 'lat', 'latitude_deg', 'gps_lat', 'gps_latitude'),
    'longitud': ('longitud', 'longitude', 'lon', 'lng', 'long', 'longitude_deg', 'gps_lon', 'gps_lng', 'gps_longitude'),
    'altitud_m': ('altitude', 'alt', 'altitude_m', 'elevation', 'elevacion', 'gps_alt', 'gps_altitude'),
    'co2_ppm': ('co2', 'co2_ppm', 'co2ppm'),
    'temperatura_c': ('temperatura', 'temperature', 'temp', 'temp_c', 'temperature_c'),
    'humedad_pct': ('humedad', 'humidity', 'rh', 'humidity_pct', 'rh_pct'),
}
MISSING_VALUES = (-2147483648, 2147483647, -9999, -99999)  # marcadores de 'sin dato' (registradores Campbell y otros)


def documents_dir():
    """Carpeta Documentos (o Documents) del usuario; su carpeta personal si no existe."""
    home = Path.home()
    return next((str(d) for d in (home / 'Documents', home / 'Documentos') if d.is_dir()), str(home))
START_ICON, END_ICON = '🏠', '✈️'  # map markers for the first and last GPS point
ALTITUDE_COLUMNS = ('altitud_m', 'altura_m', 'altitud', 'altura', 'altitude', 'height')


def altitude_column(names):
    return next((c for c in ALTITUDE_COLUMNS if c in names), None)


def numeric(series):
    values = pd.to_numeric(series.astype(str).str.replace(',', '.', regex=False), errors='coerce')
    return values.replace([np.inf, -np.inf, *MISSING_VALUES], np.nan)


def canonical_name(name):
    """Nombre que usa la app para una columna con nombre alternativo ('Latitude' -> 'latitud'); None si no lo reconoce."""
    plain = unicodedata.normalize('NFKD', str(name)).encode('ascii', 'ignore').decode().lower()
    plain = re.sub(r'[^a-z0-9]+', '_', plain).strip('_')
    return next((target for target, aliases in COLUMN_ALIASES.items() if plain in aliases), None)


def normalize_columns(frame):
    """Renombra las columnas reconocidas en COLUMN_ALIASES; no pisa una columna que ya tenga ese nombre."""
    renames, taken = {}, set(frame.columns)
    for column in frame.columns:
        target = canonical_name(column)
        if target and target not in taken:
            renames[column] = target
            taken.add(target)
    return frame.rename(columns=renames)


def find_time_column(frame, preferred=None):
    """La columna de tiempo pedida (aunque venga con su nombre original, p. ej. TIMESTAMP) o la primera conocida."""
    for column in (preferred, canonical_name(preferred) if preferred else None, *TIME_COLUMNS):
        if column and column in frame:
            return column
    return None


def gps_valid(lat, lon):
    """Coordenadas dentro de rango; 0,0 es lo que escriben muchos GPS sin señal."""
    return lat.between(-90, 90) & lon.between(-180, 180) & ~((lat == 0) & (lon == 0))


def load_csv(path, only_new=False, time_column=None, unit='auto'):
    if Path(path).stat().st_size == 0:
        raise ValueError(f'El archivo {Path(path).name} está vacío (0 bytes): no tiene encabezado ni datos.')
    source = path
    raw = Path(path).read_bytes()
    if b'\x00' in raw:
        # Escritura interrumpida (SD/USB): bloques de bytes nulos. Se quitan y se descartan las filas
        # que quedaron truncadas (con distinta cantidad de campos que el encabezado).
        lines = raw.replace(b'\x00', b'').decode('utf-8-sig', errors='replace').splitlines()
        lines = [line for line in lines if line.strip()]
        if not lines:
            raise ValueError(f'El archivo {Path(path).name} solo contiene bytes nulos: no hay datos.')
        sep = max((',', ';', '\t'), key=lines[0].count)
        width = lines[0].count(sep)
        good = [lines[0]] + [line for line in lines[1:] if line.count(sep) == width]
        source = io.StringIO('\n'.join(good))
    try:
        frame = pd.read_csv(source, sep=None, engine='python', encoding='utf-8-sig')
    except (pd.errors.EmptyDataError, pd.errors.ParserError, csv.Error) as exc:
        raise ValueError(f'No se pudo leer {Path(path).name} como CSV: {exc}') from exc
    frame.columns = frame.columns.str.strip()
    if frame.columns.duplicated().any():
        raise ValueError('El CSV tiene nombres de columnas repetidos.')
    frame = normalize_columns(frame)
    if only_new and 'sen66_new_data' in frame:
        frame = frame[numeric(frame['sen66_new_data']) == 1]
    if frame.empty:
        raise ValueError('No hay muestras para graficar con este filtro.')
    frame = frame.reset_index(drop=True)
    time_column = find_time_column(frame, time_column) if time_column else None
    if time_column:
        # Rows may arrive in any order: sort chronologically (stable; rows without a valid date go last).
        try:
            order = parse_time(frame, time_column, unit).sort_values(kind='stable', na_position='last').index
            frame = frame.loc[order].reset_index(drop=True)
        except ValueError:
            pass
    return frame


def numeric_columns(frame):
    return [c for c in frame if numeric(frame[c]).notna().any()]


def parse_time(frame, column, unit='auto'):
    if column not in frame:
        raise ValueError('Selecciona una columna de tiempo válida o usa el eje indice.')
    raw = frame[column]
    numbers = numeric(raw)
    if numbers.notna().sum() == raw.notna().sum() and numbers.notna().any():
        if unit == 'auto':
            magnitude = numbers.abs().median()
            unit = 'ns' if magnitude >= 1e17 else 'us' if magnitude >= 1e14 else 'ms' if magnitude >= 1e11 else 's'
        dates = pd.to_datetime(numbers, unit=unit, utc=True, errors='coerce')
    else:
        dates = pd.to_datetime(raw, format='mixed', utc=True, errors='coerce')
    if not dates.notna().any():
        raise ValueError(f'No se pudieron leer fechas de {column}. Usa ISO 8601 o Unix s/ms/us/ns.')
    return dates


def time_axis(frame, mode, column, zone=DEFAULT_ZONE, unit='auto'):
    if mode == 'indice':
        return pd.Series(np.arange(1, len(frame) + 1)), 'Número de muestra', None
    dates = parse_time(frame, column, unit)
    local = dates.dt.tz_convert(ZoneInfo(zone))
    if mode in ('fecha', 'hora'):
        return local, f'{"Fecha y hora" if mode == "fecha" else "Hora del día"} ({zone})', dates
    if mode == 'timestamp':
        seconds = dates.map(lambda t: t.timestamp() if pd.notna(t) else np.nan)
        return seconds, 'Timestamp Unix (segundos UTC)', dates
    return (dates - dates.dropna().iloc[0]).dt.total_seconds(), 'Tiempo transcurrido (s)', dates


def short_name(path):
    """File name without extension, trailing hash and milliseconds (long export names are mostly noise)."""
    name = Path(path).stem
    name = re.sub(r'[_-][0-9a-f]{8,}$', '', name)
    return re.sub(r'\.\d+Z$', '', name)


def _mercator(lon, lat):
    radius = 6378137.0
    lat = np.clip(lat, -85.05, 85.05)
    return radius * np.radians(lon), radius * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def use_drone_gps(frame):
    """Si el CSV trae latitud_dron/longitud_dron, el mapa usa solo esas posiciones (las filas sin dato del dron quedan sin punto)."""
    if not all(c in frame for c in DRONE_GPS):
        return frame
    frame = frame.copy()
    for own, drone in zip(('latitud', 'longitud'), DRONE_GPS):
        frame[own] = numeric(frame[drone])
    return frame


def gps_segments(frame):
    lat_col = next((c for c in LAT_COLUMNS if c in frame), None)
    lon_col = next((c for c in LON_COLUMNS if c in frame), None)
    if not lat_col or not lon_col:
        raise ValueError('El CSV no contiene columnas latitud/longitud (o latitude/longitude).')
    lat, lon = numeric(frame[lat_col]), numeric(frame[lon_col])
    valid = gps_valid(lat, lon)
    segments, segment = [], []
    previous_session = None
    for i in range(len(frame)):
        session = str(frame.iloc[i].get('session', ''))
        if not valid.iloc[i] or (previous_session is not None and session != previous_session):
            if segment:
                segments.append(segment)
                segment = []
        if valid.iloc[i]:
            segment.append((i, float(lat.iloc[i]), float(lon.iloc[i])))
        previous_session = session
    if segment:
        segments.append(segment)
    if not segments:
        raise ValueError('No hay coordenadas GPS válidas. Los CSV simulados pueden no incluir GPS.')
    return segments, int((~valid).sum())


def make_map(frame, output, time_column='fecha_hora_utc', zone=DEFAULT_ZONE, unit='auto'):
    try:
        import folium
    except ImportError as exc:
        raise ValueError('Para el mapa instala las dependencias: pip install -r requirements.txt') from exc
    gps_frame = use_drone_gps(frame)
    segments, missing = gps_segments(gps_frame)
    points = [point for segment in segments for point in segment]
    first, last = points[0], points[-1]
    # xyzservices supplies the provider URL and attribution through Folium.
    map_view = folium.Map(location=first[1:], zoom_start=17, tiles='OpenStreetMap', control_scale=True, prefer_canvas=True)
    folium.TileLayer('Esri.WorldImagery', name='Satélite', max_native_zoom=18, max_zoom=21).add_to(map_view)
    for segment in segments:
        if len(segment) > 1:
            folium.PolyLine([p[1:] for p in segment], color='#00ffff', weight=3).add_to(map_view)
    dates = None
    if time_column in frame:
        try:
            dates = parse_time(frame, time_column, unit).dt.tz_convert(ZoneInfo(zone))
        except ValueError:
            pass
    # Keep the entire route; limit only clickable markers for large 10 Hz CSV files.
    step = max(1, int(np.ceil(len(points) / 2000)))
    markers = points[::step]
    if markers[-1] != last:
        markers.append(last)
    for i, lat, lon in markers:
        stamp = str(dates.iloc[i]) if dates is not None and pd.notna(dates.iloc[i]) else 'No disponible'
        co2 = frame.iloc[i].get('co2_ppm', 'No disponible')
        detail = f'Muestra: {i + 1}<br>Hora: {html.escape(stamp)}<br>CO₂: {html.escape(str(co2))} ppm<br>Latitud: {lat:.6f}<br>Longitud: {lon:.6f}'
        folium.CircleMarker((lat, lon), radius=3, color='#ffff00', fill=True, popup=folium.Popup(detail, max_width=330)).add_to(map_view)
    for point, label, emoji in ((first, 'Inicio', START_ICON), (last, 'Fin', END_ICON)):
        badge = f'<div style="font-size:22px;line-height:30px;text-align:center;width:32px;height:32px;background:rgba(255,255,255,.9);border:2px solid #333;border-radius:50%">{emoji}</div>'
        folium.Marker(point[1:], tooltip=label, icon=folium.DivIcon(html=badge, icon_size=(32, 32), icon_anchor=(16, 16))).add_to(map_view)
    map_view.fit_bounds([p[1:] for p in points], max_zoom=18)
    folium.LayerControl().add_to(map_view)
    banner = f'<div style="position:fixed;bottom:25px;left:10px;z-index:9999;background:white;padding:8px;color:black">Ruta GPS · {missing} filas sin GPS · {len(markers)} puntos consultables / {len(points)} válidos</div>'
    map_view.get_root().html.add_child(folium.Element(banner))
    output = Path(output).resolve()
    map_view.save(str(output))
    return output


def make_viewer(frame, output, columns=None, time_column='fecha_hora_utc', zone=DEFAULT_ZONE, unit='auto', title='MicroGas'):
    """Self-contained interactive HTML (Plotly, WebGL): route map on the left, linked plots on the right.
    Only the map tiles need internet; the data and plotly.js are embedded."""
    import json
    from plotly.offline import get_plotlyjs

    def clean(series, digits=6):
        values = numeric(series)
        return [None if pd.isna(v) else round(float(v), digits) for v in values]

    variables = [c for c in numeric_columns(frame) if c not in DRONE_GPS]
    preferred = [c for c in (columns or ()) if c in variables] or [c for c in ('co2_ppm', 'temperatura_c', 'humedad_pct', 'pm2_5') if c in variables] \
        or [c for c in variables if c not in GPS_NAMES][:4] or variables[:1]
    data = {'title': title, 'n': len(frame), 'vars': variables, 'defaultVars': preferred, 'palette': list(PALETTE), 'startIcon': START_ICON, 'endIcon': END_ICON,
            'y': {c: clean(frame[c]) for c in variables}, 'x': {}, 'utc': None, 'lat': None, 'lon': None}
    try:
        local, _, dates = time_axis(frame, 'fecha', time_column, zone, unit)
        wall = (local.dt.tz_localize(None) - pd.Timestamp('1970-01-01')).dt.total_seconds() * 1000
        data['x']['fecha'] = [None if pd.isna(v) else float(v) for v in wall]
        elapsed, _, _ = time_axis(frame, 'transcurrido', time_column, zone, unit)
        data['x']['transcurrido'] = [None if pd.isna(v) else round(float(v), 3) for v in elapsed]
        stamps = dates.dt.strftime('%Y-%m-%d %H:%M:%S.%f').str[:-3] + ' UTC'
        data['utc'] = [None if pd.isna(d) else t for d, t in zip(dates, stamps)]
    except ValueError:
        pass
    data['x']['indice'] = list(range(1, len(frame) + 1))
    data['xmodes'] = [m for m in ('fecha', 'transcurrido', 'indice') if m in data['x']]
    data['defaultColor'] = preferred[0] if 'co2_ppm' not in variables else 'co2_ppm'
    def gps_payload(source):
        segments, _ = gps_segments(source)
        lat_col = next(c for c in LAT_COLUMNS if c in source)
        lon_col = next(c for c in LON_COLUMNS if c in source)
        lat, lon = numeric(source[lat_col]), numeric(source[lon_col])
        ok = gps_valid(lat, lon)
        route_lat, route_lon = [], []
        for segment in segments:
            route_lat += [p[1] for p in segment] + [None]
            route_lon += [p[2] for p in segment] + [None]
        pad_lat = max((lat[ok].max() - lat[ok].min()) * .12, 0.0005)
        pad_lon = max((lon[ok].max() - lon[ok].min()) * .12, 0.0005)
        return {'lat': [round(float(v), 7) if k else None for v, k in zip(lat, ok)],
                'lon': [round(float(v), 7) if k else None for v, k in zip(lon, ok)],
                'routeLat': route_lat, 'routeLon': route_lon,
                'bounds': {'west': float(lon[ok].min() - pad_lon), 'east': float(lon[ok].max() + pad_lon),
                           'south': float(lat[ok].min() - pad_lat), 'north': float(lat[ok].max() + pad_lat)}}

    try:
        data.update(gps_payload(frame))
        if all(c in frame for c in DRONE_GPS):  # selector Datos / Dron en la barra
            data['gps'] = {'datos': {k: data[k] for k in ('lat', 'lon', 'routeLat', 'routeLon', 'bounds')}, 'dron': gps_payload(use_drone_gps(frame))}
            data['gpsSource'] = 'datos'
    except (ValueError, StopIteration):
        pass
    template = Path(__file__).with_name('visor_template.html').read_text(encoding='utf-8')
    payload = json.dumps(data, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    page = template.replace('__TITLE__', html.escape(title)).replace('__PLOTLY__', get_plotlyjs()).replace('__DATA__', payload)
    output = Path(output).resolve()
    output.write_text(page, encoding='utf-8')
    return output


def default_variables(variables, columns=None):
    return [c for c in (columns or ()) if c in variables] or [c for c in ('co2_ppm', 'temperatura_c', 'humedad_pct', 'pm2_5') if c in variables] \
        or [c for c in variables if c not in GPS_NAMES][:4] or variables[:1]


def make_excel(frame, output, columns=None, time_column='fecha_hora_utc', zone=DEFAULT_ZONE, unit='auto', title='MicroGas'):
    """Libro Excel con lo que llega en `frame` (el visor pasa solo el tramo elegido): hojas Resumen, Datos,
    Gráficas (un gráfico nativo de Excel por variable) y Ruta (latitud/longitud, si hay GPS)."""
    import datetime
    try:
        import xlsxwriter
        from xlsxwriter.utility import xl_range_abs
    except ImportError as exc:
        raise ValueError('Para exportar a Excel instala las dependencias: pip install -r requirements.txt') from exc
    if frame.empty:
        raise ValueError('No hay muestras para exportar.')
    variables = numeric_columns(frame)
    chosen = default_variables(variables, columns)
    lat_col = next((c for c in LAT_COLUMNS if c in frame), None)
    lon_col = next((c for c in LON_COLUMNS if c in frame), None)
    extra = [c for c in (lat_col, lon_col, altitude_column(frame.columns)) if c and c not in chosen]
    local = None
    try:
        local, _, dates = time_axis(frame, 'fecha', time_column, zone, unit)
        local = local.dt.tz_localize(None)
        elapsed = (dates - dates.dropna().iloc[0]).dt.total_seconds()
    except ValueError:
        pass
    multi_day = local is not None and local.dropna().dt.date.nunique() > 1
    date_format = 'dd/mm/yyyy hh:mm:ss'

    book = xlsxwriter.Workbook(str(output))
    bold = book.add_format({'bold': True})
    head = book.add_format({'bold': True, 'bg_color': '#dfeeee', 'border': 1, 'text_wrap': True, 'valign': 'top'})
    when = book.add_format({'num_format': date_format})
    number = book.add_format({'num_format': '0.000'})
    summary, sheet, plots = book.add_worksheet('Resumen'), book.add_worksheet('Datos'), book.add_worksheet('Gráficas')

    # Datos: tiempo + variables elegidas + GPS/altitud
    headers, series = [], []
    if local is not None:
        headers += [f'Fecha y hora ({zone})', 'Transcurrido (s)']
        series += [list(local), list(elapsed)]
    else:
        headers.append('Muestra')
        series.append(list(range(1, len(frame) + 1)))
    data_cols = chosen + extra
    headers += data_cols
    series += [list(numeric(frame[c])) for c in data_cols]
    n = len(frame)
    sheet.write_row(0, 0, headers, head)
    for col, values in enumerate(series):
        fmt_cell = when if local is not None and col == 0 else None
        for row, value in enumerate(values, 1):
            if value is None or pd.isna(value):
                continue
            if fmt_cell:
                sheet.write_datetime(row, col, value.to_pydatetime(), fmt_cell)
            else:
                sheet.write_number(row, col, float(value))
    sheet.set_column(0, 0, 21 if local is not None else 9)
    sheet.set_column(1, len(headers) - 1, 14)
    sheet.freeze_panes(1, 1)
    sheet.autofilter(0, 0, n, len(headers) - 1)
    column_of = {name: headers.index(name) for name in data_cols}
    x_ref = ['Datos', 1, 0, n, 0]

    # Resumen
    summary.write(0, 0, title, book.add_format({'bold': True, 'font_size': 14}))
    info = [('Muestras', n)]
    if local is not None and local.notna().any():
        first, last = local.dropna().iloc[0], local.dropna().iloc[-1]
        secs = int((last - first).total_seconds())
        info = [('Desde', first.to_pydatetime()), ('Hasta', last.to_pydatetime()),
                ('Duración', f'{secs // 3600} h {secs % 3600 // 60:02d} min {secs % 60:02d} s'), ('Zona horaria', zone)] + info
    for row, (label, value) in enumerate(info, 2):
        summary.write(row, 0, label, bold)
        if isinstance(value, datetime.datetime):
            summary.write_datetime(row, 1, value, when)
        else:
            summary.write(row, 1, value)
    top = len(info) + 3
    summary.write_row(top, 0, ['Variable', 'Mínimo', 'Promedio', 'Máximo', 'Muestras válidas'], head)
    for row, name in enumerate(chosen, top + 1):
        values = numeric(frame[name]).dropna()
        ref = 'Datos!' + xl_range_abs(1, column_of[name], n, column_of[name])
        summary.write(row, 0, name)
        if len(values):
            for col, (func, cached) in enumerate((('MIN', values.min()), ('AVERAGE', values.mean()), ('MAX', values.max())), 1):
                summary.write_formula(row, col, f'={func}({ref})', number, float(cached))
        summary.write_formula(row, 4, f'=COUNT({ref})', None, len(values))
    summary.set_column(0, 0, 22)
    summary.set_column(1, 1, 20)
    summary.set_column(2, 4, 16)

    # Gráficas: cuadrícula de 3 columnas, un gráfico por variable
    width, height = 620, 320
    for k, name in enumerate(chosen):
        chart = book.add_chart({'type': 'scatter', 'subtype': 'straight'})
        col = column_of[name]
        chart.add_series({'name': name, 'categories': x_ref, 'values': ['Datos', 1, col, n, col],
                          'line': {'color': PALETTE[variables.index(name) % len(PALETTE)], 'width': 1.25}})
        x_axis = {'name': 'Fecha y hora' if local is not None else 'Muestra', 'major_gridlines': {'visible': True, 'line': {'color': '#e3e3e3'}}}
        if local is not None:
            x_axis['num_format'] = 'dd/mm hh:mm' if multi_day else 'hh:mm:ss'
            valid = local.dropna()
            if len(valid) > 1:
                serial = lambda t: (t - pd.Timestamp('1899-12-30')).total_seconds() / 86400
                x_axis['min'], x_axis['max'] = serial(valid.iloc[0]), serial(valid.iloc[-1])
        chart.set_title({'name': name, 'name_font': {'size': 12}})
        chart.set_x_axis(x_axis)
        chart.set_y_axis({'name': name, 'major_gridlines': {'visible': True, 'line': {'color': '#e3e3e3'}}})
        chart.set_legend({'none': True})
        chart.set_size({'width': width, 'height': height})
        plots.insert_chart(0, 0, chart, {'x_offset': 10 + (k % 3) * (width + 10), 'y_offset': 10 + (k // 3) * (height + 10)})

    # Ruta: longitud (X) contra latitud (Y); Excel no tiene fondo de mapa
    if lat_col and lon_col and numeric(frame[lat_col]).between(-90, 90).any():
        route = book.add_worksheet('Ruta')
        column_of.update({c: headers.index(c) for c in (lat_col, lon_col)})
        chart = book.add_chart({'type': 'scatter', 'subtype': 'straight_with_markers'})
        chart.add_series({'name': 'Ruta GPS', 'categories': ['Datos', 1, column_of[lon_col], n, column_of[lon_col]],
                          'values': ['Datos', 1, column_of[lat_col], n, column_of[lat_col]],
                          'line': {'color': '#007f86', 'width': 1.5}, 'marker': {'type': 'circle', 'size': 3, 'fill': {'color': '#007f86'}, 'border': {'none': True}}})
        lat, lon = numeric(frame[lat_col]).dropna(), numeric(frame[lon_col]).dropna()
        pad_lat, pad_lon = max((lat.max() - lat.min()) * 0.05, 1e-5), max((lon.max() - lon.min()) * 0.05, 1e-5)
        chart.set_title({'name': 'Ruta GPS (sin fondo de mapa)'})
        chart.set_x_axis({'name': 'Longitud', 'min': lon.min() - pad_lon, 'max': lon.max() + pad_lon, 'num_format': '0.0000'})
        chart.set_y_axis({'name': 'Latitud', 'min': lat.min() - pad_lat, 'max': lat.max() + pad_lat, 'num_format': '0.0000'})
        chart.set_legend({'none': True})
        chart.set_size({'width': 800, 'height': 800})
        route.insert_chart(0, 0, chart, {'x_offset': 10, 'y_offset': 10})
    summary.activate()
    book.close()
    return Path(output).resolve()


def launch_qt(path, columns=None, time_column=None, zone=DEFAULT_ZONE, unit='auto', only_new=False):
    """Open the pyqtgraph viewer (visor_qt.py) in its own process; Qt and Tk must not share one."""
    import subprocess
    if getattr(sys, 'frozen', False):
        # Ejecutable empaquetado: el mismo .exe se relanza en modo visor (ver main).
        command = [sys.executable, '--visor-qt', str(path), '--zona', zone, '--unidad', unit]
    else:
        command = [sys.executable, str(Path(__file__).with_name('visor_qt.py')), str(path), '--zona', zone, '--unidad', unit]
    if time_column:
        command += ['--tiempo', time_column]
    if only_new:
        command.append('--solo-nuevas')
    if columns:
        command += ['--y', *columns]
    return subprocess.Popen(command)


def serve_local(path):
    """Sirve un HTML en http://127.0.0.1 y devuelve su URL.

    OpenStreetMap bloquea los tiles pedidos sin Referer, y una pagina abierta como file:// no envia ninguno;
    desde http://127.0.0.1 el navegador si lo envia. El hilo es daemon: vive mientras viva la aplicacion."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    body = Path(path).read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            ok = self.path.split('?')[0] == '/'
            self.send_response(200 if ok else 404)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body) if ok else 0))
            self.end_headers()
            if ok:
                self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f'http://127.0.0.1:{server.server_address[1]}/'


def gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import tempfile
    import webbrowser
    root = tk.Tk()
    root.title('GasLab · Graficación CSV')
    root.geometry('720x610')
    panel = ttk.Frame(root, padding=16)
    panel.pack(fill='both', expand=True)
    source = tk.StringVar()
    shown = tk.StringVar()
    time_col, zone, unit = (tk.StringVar(value=v) for v in ('fecha_hora_utc', DEFAULT_ZONE, 'auto'))
    only_new = tk.BooleanVar(value=False)
    status = tk.StringVar(value='Abre un CSV de Receptor, DJI o Simulado.')
    ttk.Label(panel, text='Archivo CSV').pack(anchor='w')
    ttk.Entry(panel, textvariable=shown, state='readonly').pack(fill='x')
    variables = tk.Listbox(panel, selectmode='extended', exportselection=False, height=9)
    time_box = None

    def open_csv():
        path = filedialog.askopenfilename(initialdir=documents_dir(), filetypes=[('CSV', '*.csv')])
        if not path:
            return
        try:
            frame = load_csv(path)
            source.set(path)
            shown.set(short_name(path))
            variables.delete(0, 'end')
            for column in numeric_columns(frame):
                variables.insert('end', column)
            available = list(variables.get(0, 'end'))
            if available:
                variables.selection_set(available.index('co2_ppm') if 'co2_ppm' in available else 0)
            time_box['values'] = list(frame.columns)
            time_col.set(find_time_column(frame) or str(frame.columns[0]))
            status.set(f'{len(frame):,} filas cargadas. Selecciona variables con Ctrl o Shift.')
        except Exception as exc:
            messagebox.showerror('No se pudo cargar', str(exc))

    ttk.Button(panel, text='Abrir CSV…', command=open_csv).pack(anchor='w', pady=8)
    ttk.Label(panel, text='Variables (Ctrl o Shift para seleccionar varias)').pack(anchor='w')
    variables.pack(fill='x')
    ttk.Button(panel, text='Seleccionar todas las variables', command=lambda: variables.selection_set(0, 'end')).pack(anchor='w', pady=4)
    for label, variable, choices in [('Columna de tiempo', time_col, ()), ('Unidad Unix (si la fecha es numérica)', unit, ('auto', 's', 'ms', 'us', 'ns'))]:
        row = ttk.Frame(panel)
        row.pack(fill='x', pady=4)
        ttk.Label(row, text=label, width=35).pack(side='left')
        box = ttk.Combobox(row, textvariable=variable, values=choices, state='readonly')
        box.pack(side='left', fill='x', expand=True)
        if variable is time_col:
            time_box = box
    row = ttk.Frame(panel)
    row.pack(fill='x', pady=4)
    ttk.Label(row, text='Zona horaria', width=35).pack(side='left')
    ttk.Entry(row, textvariable=zone).pack(side='left', fill='x', expand=True)
    ttk.Checkbutton(panel, text='Solo muestras nuevas SEN66 (CSV DJI; elimina filas retenidas)', variable=only_new).pack(anchor='w', pady=6)

    def run(action):
        try:
            if not source.get():
                raise ValueError('Primero abre un CSV.')
            frame = load_csv(source.get(), only_new.get(), time_col.get(), unit.get())
            if action == 'qt':
                launch_qt(source.get(), [variables.get(i) for i in variables.curselection()], time_col.get(), zone.get(), unit.get(), only_new.get())
                status.set('Visor rápido abierto en otra ventana.')
            elif action == 'web':
                chosen = [variables.get(i) for i in variables.curselection()]
                output = make_viewer(frame, Path(tempfile.gettempdir()) / f'gaslab_{short_name(source.get())}.html', chosen, time_col.get(), zone.get(), unit.get(), short_name(source.get()))
                webbrowser.open(serve_local(output))
                status.set(f'Vista interactiva abierta en el navegador ({output.name}).')
            elif action == 'mapa':
                destination = filedialog.asksaveasfilename(defaultextension='.html', initialfile=short_name(source.get()) + '_ruta.html', filetypes=[('Mapa HTML', '*.html')])
                if not destination:
                    return
                output = make_map(frame, destination, time_col.get(), zone.get(), unit.get())
                webbrowser.open(output.as_uri())
                status.set(f'Mapa guardado: {output.name}. El fondo necesita internet.')
        except Exception as exc:
            messagebox.showerror('No se pudo generar', str(exc))

    buttons = ttk.Frame(panel)
    buttons.pack(fill='x', pady=12)
    for label, action in [('Visor rápido (ventana)', 'qt'), ('Vista interactiva (navegador)', 'web'), ('Mapa GPS…', 'mapa')]:
        ttk.Button(buttons, text=label, command=lambda a=action: run(a)).pack(side='left', padx=4)
    ttk.Label(panel, textvariable=status, wraplength=670).pack(anchor='w')
    root.mainloop()


def make_heatmap(args):
    """--calor: mapa de calor georreferenciado de una variable (mapa_calor.export)."""
    import mapa_calor
    frame = load_csv(args.csv, args.solo_nuevas, args.tiempo, args.unidad)
    for given, own in ((args.lat, 'latitud'), (args.lon, 'longitud')):
        if given:
            if given not in frame:
                raise ValueError(f'No existe la columna {given!r}.')
            frame[own] = numeric(frame[given])
    if args.gps_dron:
        frame = use_drone_gps(frame)
    lat_col = next((c for c in LAT_COLUMNS if c in frame), None)
    lon_col = next((c for c in LON_COLUMNS if c in frame), None)
    if not lat_col or not lon_col:
        raise ValueError('No se encontraron columnas de GPS; indícalas con --lat y --lon.')
    if args.calor not in frame:
        raise ValueError(f'No existe la columna {args.calor!r}. Columnas numéricas: {", ".join(numeric_columns(frame))}')
    lat, lon = numeric(frame[lat_col]), numeric(frame[lon_col])
    ok = gps_valid(lat, lon)
    seconds, times = None, None
    column = find_time_column(frame, args.tiempo)
    if column:
        try:
            dates = parse_time(frame, column, args.unidad)
            seconds = (dates - pd.Timestamp('1970-01-01', tz='UTC')).dt.total_seconds().to_numpy(dtype=float)
            times = dates.dt.strftime('%Y-%m-%d %H:%M:%S').fillna('').to_numpy()
        except ValueError:
            pass
    if args.desfase and seconds is None:
        raise ValueError('El desfase necesita una columna de tiempo válida (--tiempo).')
    output = args.calor_salida or args.csv.with_name(f'{short_name(args.csv)}_{args.calor}.tif')
    return mapa_calor.export(output, lat.where(ok).to_numpy(dtype=float), lon.where(ok).to_numpy(dtype=float),
                             numeric(frame[args.calor]).to_numpy(dtype=float), args.calor, args.celda, args.estadistico,
                             args.suavizado, seconds, args.desfase, times, (args.min, args.max), args.capa,
                             mode='celdas' if args.celdas else 'puntos', point_mm=args.tam_punto)


def main():
    if getattr(sys, 'frozen', False) and len(sys.argv) > 1 and sys.argv[1] == '--visor-qt':
        import visor_qt
        visor_qt.main(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', nargs='?', type=Path)
    parser.add_argument('--y', nargs='+', default=['co2_ppm'], help='Variables iniciales')
    parser.add_argument('--tiempo', default='fecha_hora_utc', help='Columna que contiene fecha o timestamp')
    parser.add_argument('--zona', default=DEFAULT_ZONE)
    parser.add_argument('--unidad', choices=['auto', 's', 'ms', 'us', 'ns'], default='auto')
    parser.add_argument('--solo-nuevas', action='store_true')
    parser.add_argument('--qt', action='store_true', help='Abrir el visor rápido (pyqtgraph) con este CSV; es lo que ocurre si no se pide otra salida')
    parser.add_argument('--web', type=Path, help='Guardar la vista interactiva (HTML con Plotly): mapa a la izquierda, gráficas enlazadas a la derecha')
    parser.add_argument('--mapa', type=Path, help='Guardar mapa satelital HTML')
    heat = parser.add_argument_group('mapa de calor georreferenciado (GeoTIFF + GeoJSON + proyecto QGIS, ver mapa_calor.py)')
    heat.add_argument('--calor', metavar='VARIABLE', help='Variable a georreferenciar (nombre de columna, p. ej. co2_ppm)')
    heat.add_argument('--calor-salida', type=Path, help='GeoTIFF de salida (por defecto <csv>_<variable>.tif junto al CSV)')
    heat.add_argument('--celda', type=float, default=10, help='Lado de la celda en metros, desde 0.5 (10)')
    heat.add_argument('--celdas', action='store_true', help='Abrir el proyecto QGIS con las celdas encendidas en lugar de los puntos')
    heat.add_argument('--tam-punto', type=float, default=1.8, help='Tamaño de los puntos en QGIS, en mm (1.8)')
    heat.add_argument('--estadistico', choices=['media', 'maximo', 'p95', 'muestras'], default='media')
    heat.add_argument('--suavizado', type=float, default=1, help='Sigma del suavizado en celdas; 0 = sin suavizar (1)')
    heat.add_argument('--desfase', type=float, default=0, help='Retraso del sensor en segundos (0)')
    heat.add_argument('--min', type=float, help='Valor mínimo válido (los menores se ignoran)')
    heat.add_argument('--max', type=float, help='Valor máximo válido (los mayores se ignoran)')
    heat.add_argument('--capa', type=Path, action='append', default=[], help='GeoTIFF extra para el proyecto QGIS (p. ej. mosaico térmico); repetible')
    heat.add_argument('--lat', help='Columna de latitud, si el CSV usa un nombre no reconocido')
    heat.add_argument('--lon', help='Columna de longitud, si el CSV usa un nombre no reconocido')
    heat.add_argument('--gps-dron', action='store_true', help='Usar latitud_dron/longitud_dron si el CSV las trae')
    args = parser.parse_args()
    if args.csv is None:
        gui()
        return
    try:
        if args.calor:
            print(make_heatmap(args))
            return
        if args.web or args.mapa:
            frame = load_csv(args.csv, args.solo_nuevas, args.tiempo, args.unidad)
            args.tiempo = find_time_column(frame, args.tiempo) or args.tiempo
            if args.web:
                print(f'Vista interactiva: {make_viewer(frame, args.web, args.y if "--y" in sys.argv else None, args.tiempo, args.zona, args.unidad, short_name(args.csv))}')
            if args.mapa:
                print(f'Mapa: {make_map(frame, args.mapa, args.tiempo, args.zona, args.unidad)}')
        if args.qt or not (args.web or args.mapa):
            launch_qt(args.csv, args.y if '--y' in sys.argv else None, args.tiempo, args.zona, args.unidad, args.solo_nuevas).wait()
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
