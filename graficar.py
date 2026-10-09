#!/usr/bin/env python3
"""Graficador local de CSV MicroGas. Sin argumentos abre la interfaz gráfica."""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

TIME_COLUMNS = ('fecha_hora_utc', 'sen66_muestra_utc', 'received_at_ms', 'timestamp', 'time', 'datetime')
PALETTE = ('#007f86', '#d95f02', '#7570b3', '#e7298a', '#66a61e', '#e6ab02', '#a6761d', '#1f78b4', '#b2182b', '#8c564b')
DEFAULT_ZONE = 'America/Costa_Rica'


def documents_dir():
    """Carpeta Documentos (o Documents) del usuario; su carpeta personal si no existe."""
    home = Path.home()
    return next((str(d) for d in (home / 'Documents', home / 'Documentos') if d.is_dir()), str(home))
START_ICON, END_ICON = '🏠', '✈️'  # map markers for the first and last GPS point
ALTITUDE_COLUMNS = ('altitud_m', 'altura_m', 'altitud', 'altura', 'altitude', 'height')


def altitude_column(names):
    return next((c for c in ALTITUDE_COLUMNS if c in names), None)


def numeric(series):
    return pd.to_numeric(series.astype(str).str.replace(',', '.', regex=False), errors='coerce').replace([np.inf, -np.inf], np.nan)


def load_csv(path, only_new=False, time_column=None, unit='auto'):
    frame = pd.read_csv(path, sep=None, engine='python', encoding='utf-8-sig')
    frame.columns = frame.columns.str.strip()
    if frame.columns.duplicated().any():
        raise ValueError('El CSV tiene nombres de columnas repetidos.')
    if only_new and 'sen66_new_data' in frame:
        frame = frame[numeric(frame['sen66_new_data']) == 1]
    if frame.empty:
        raise ValueError('No hay muestras para graficar con este filtro.')
    frame = frame.reset_index(drop=True)
    if time_column in frame:
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


def gps_segments(frame):
    lat_col = next((c for c in ('latitud', 'latitude', 'lat') if c in frame), None)
    lon_col = next((c for c in ('longitud', 'longitude', 'lon', 'lng') if c in frame), None)
    if not lat_col or not lon_col:
        raise ValueError('El CSV no contiene columnas latitud/longitud (o latitude/longitude).')
    lat, lon = numeric(frame[lat_col]), numeric(frame[lon_col])
    valid = lat.between(-90, 90) & lon.between(-180, 180)
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
    segments, missing = gps_segments(frame)
    points = [point for segment in segments for point in segment]
    first, last = points[0], points[-1]
    # xyzservices supplies the provider URL and attribution through Folium.
    map_view = folium.Map(location=first[1:], zoom_start=17, tiles='OpenStreetMap', control_scale=True, prefer_canvas=True)
    folium.TileLayer('Esri.WorldImagery', name='Satélite').add_to(map_view)
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

    variables = numeric_columns(frame)
    gps_names = {'latitud', 'latitude', 'lat', 'longitud', 'longitude', 'lon', 'lng'}
    preferred = [c for c in (columns or ()) if c in variables] or [c for c in ('co2_ppm', 'temperatura_c', 'humedad_pct', 'pm2_5') if c in variables] \
        or [c for c in variables if c not in gps_names][:4] or variables[:1]
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
    try:
        segments, _ = gps_segments(frame)
        lat_col = next(c for c in ('latitud', 'latitude', 'lat') if c in frame)
        lon_col = next(c for c in ('longitud', 'longitude', 'lon', 'lng') if c in frame)
        lat, lon = numeric(frame[lat_col]), numeric(frame[lon_col])
        ok = lat.between(-90, 90) & lon.between(-180, 180)
        data['lat'] = [round(float(v), 7) if k else None for v, k in zip(lat, ok)]
        data['lon'] = [round(float(v), 7) if k else None for v, k in zip(lon, ok)]
        route_lat, route_lon = [], []
        for segment in segments:
            route_lat += [p[1] for p in segment] + [None]
            route_lon += [p[2] for p in segment] + [None]
        data['routeLat'], data['routeLon'] = route_lat, route_lon
        pad_lat = max((lat[ok].max() - lat[ok].min()) * .12, 0.0005)
        pad_lon = max((lon[ok].max() - lon[ok].min()) * .12, 0.0005)
        data['bounds'] = {'west': float(lon[ok].min() - pad_lon), 'east': float(lon[ok].max() + pad_lon),
                          'south': float(lat[ok].min() - pad_lat), 'north': float(lat[ok].max() + pad_lat)}
    except (ValueError, StopIteration):
        pass
    template = Path(__file__).with_name('visor_template.html').read_text(encoding='utf-8')
    payload = json.dumps(data, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    page = template.replace('__TITLE__', html.escape(title)).replace('__PLOTLY__', get_plotlyjs()).replace('__DATA__', payload)
    output = Path(output).resolve()
    output.write_text(page, encoding='utf-8')
    return output


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
            time_col.set(next((c for c in TIME_COLUMNS if c in frame), str(frame.columns[0])))
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
                webbrowser.open(output.as_uri())
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
    args = parser.parse_args()
    if args.csv is None:
        gui()
        return
    try:
        if args.web or args.mapa:
            frame = load_csv(args.csv, args.solo_nuevas, args.tiempo, args.unidad)
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
