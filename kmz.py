"""Exportación a KMZ (Google Earth) de lo que tiene mapa en GasLab 2.0: ruta, nube de calor, muestras, barras 3D y
puntos a su altura. Un KMZ es un ZIP con doc.kml y las imágenes que usa (nube y leyenda).

Google Earth en el navegador (earth.google.com, importar como "Map features") acepta como máximo 10 000 elementos y
rechaza el archivo entero si trae TimeStamp o ScreenOverlay (probado por el usuario). Por eso: las muestras se limitan
(MAX_FEATURES en gaslab_web.py), la hora va en la descripción de cada punto (no como TimeStamp), la leyenda es un
punto «Leyenda» con la tabla de colores (no una leyenda fija en pantalla) y el ícono es el círculo de Google, que se
tiñe con el color de cada división. Así el mismo archivo sirve en la web y en Google Earth Pro.

Alturas: 'absolute' en KML es sobre el nivel del mar del modelo de Google Earth (EGM96). Muchos GPS dan la altura
sobre el elipsoide WGS84, que puede diferir decenas de metros; el desfase del paso 4 sirve para corregirlo.
"""
from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

import numpy as np

import mapa_calor as mc

ROUTE_COLORS = {'sensor': '#007f86', 'dron': '#d95f02'}
ICON = 'https://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'  # blanco: Google Earth lo tiñe


def kml_color(hex_color, alpha=255):
    """'#rrggbb' -> 'aabbggrr' (el orden de KML)."""
    r, g, b = hex_color[1:3], hex_color[3:5], hex_color[5:7]
    return f'{alpha:02x}{b}{g}{r}'


def _png(image):
    buffer = io.BytesIO()
    image.save(buffer, 'PNG', optimize=True)
    return buffer.getvalue()


def _num(v):
    v = float(v)
    text = f'{v:,.1f}' if abs(v) >= 100 else f'{v:,.2f}' if abs(v) >= 1 else f'{v:,.4f}'
    return text.replace(',', ' ').replace('.', ',')


def overlay_png(rgba, corners):
    """La nube viene en Web Mercator; KML la estira en grados (latitud lineal). Se remuestrean las filas para que
    cada una caiga en su latitud. Devuelve (png, (norte, sur, este, oeste))."""
    from PIL import Image
    (west, north), _, (east, south), _ = corners
    h = rgba.shape[0]
    _, (y_n, y_s) = mc.mercator(np.array([west, west]), np.array([north, south]))
    lats = north - (np.arange(h) + 0.5) / h * (north - south)
    _, y = mc.mercator(np.full(h, west), lats)
    source = np.clip(((y_n - y) / (y_n - y_s) * h).astype(int), 0, h - 1)
    return _png(Image.fromarray(np.ascontiguousarray(rgba[source]), 'RGBA')), (north, south, east, west)


def _coord(lon, lat, alt=None):
    return f'{lon:.7f},{lat:.7f}' + (f',{alt:.2f}' if alt is not None and np.isfinite(alt) else '')


def route_kml(routes, visible=True):
    """routes = [(nombre, clave de color, segmentos)], cada segmento con listas lon, lat y when (UTC ISO). Una línea
    pegada al suelo por segmento (sin unir pausas) y los puntos de Inicio y Fin con su hora."""
    out = [f'<Folder><name>Ruta GPS</name><visibility>{int(visible)}</visibility>']
    for name, key, segments in routes:
        color = kml_color(ROUTE_COLORS.get(key, '#007f86'))
        out.append(f'<Folder><name>{escape(name)}</name>')
        for k, seg in enumerate(segments, 1):
            if len(seg['lon']) < 2:  # un punto suelto (entre huecos de GPS) no hace línea
                continue
            coords = ' '.join(_coord(x, y) for x, y in zip(seg['lon'], seg['lat']))
            out.append(f'<Placemark><name>Tramo {k}</name><Style><LineStyle><color>{color}</color><width>3</width></LineStyle></Style>'
                       f'<LineString><tessellate>1</tessellate><altitudeMode>clampToGround</altitudeMode><coordinates>{coords}</coordinates></LineString></Placemark>')
        if segments:
            first, last = segments[0], segments[-1]
            for label, seg, i in (('Inicio', first, 0), ('Fin', last, -1)):  # la hora va en la descripción (sin TimeStamp)
                when = f"<description>{seg['when'][i]}</description>" if seg.get('when') else ''
                out.append(f'<Placemark><name>{label} · {escape(name)}</name>{when}<Point><coordinates>{_coord(seg["lon"][i], seg["lat"][i])}</coordinates></Point></Placemark>')
        out.append('</Folder>')
    out.append('</Folder>')
    return ''.join(out)


def styles_kml(colors, scale=0.55):
    """Un estilo por división (s0, s1…): ícono teñido con su color, sin etiqueta; barra con el mismo color."""
    return ''.join(f'<Style id="s{k}"><IconStyle><color>{kml_color(c)}</color><scale>{scale}</scale><Icon><href>{ICON}</href></Icon></IconStyle>'
                   f'<LabelStyle><scale>0</scale></LabelStyle><LineStyle><color>{kml_color(c, 160)}</color><width>1</width></LineStyle>'
                   f'<PolyStyle><color>{kml_color(c, 235)}</color><outline>0</outline></PolyStyle></Style>' for k, c in enumerate(colors))


def points_kml(name, folder, lon, lat, values, klass, times, heights=None, mode='clampToGround', extrude=False, visible=True, notes=None):
    """Un punto por muestra con el estilo de su división; al hacer clic se ve el valor, la hora y la altura.
    heights: altura de cada punto según `mode` ('absolute' o 'relativeToGround'); NaN = no se dibuja."""
    out = [f'<Folder><name>{escape(folder)}</name><visibility>{int(visible)}</visibility>']
    for i in range(len(values)):
        h = None if heights is None else heights[i]
        if h is not None and not np.isfinite(h):
            continue
        extra = '' if notes is None else notes[i]
        # Orden del estándar KML: visibility, description, styleUrl, geometría. La hora va en la descripción.
        out.append(f'<Placemark><visibility>{int(visible)}</visibility>'
                   f'<description><![CDATA[<b>{_num(values[i])}</b> {escape(name)}<br>{times[i] if times is not None else ""}{extra}]]></description>'
                   f'<styleUrl>#s{klass[i]}</styleUrl><Point>{"<extrude>1</extrude>" if extrude else ""}<altitudeMode>{mode}</altitudeMode><coordinates>{_coord(lon[i], lat[i], h)}</coordinates></Point></Placemark>')
    out.append('</Folder>')
    return ''.join(out)


def bars_kml(name, lon, lat, values, klass, vmin, vmax, height=100.0, width=2.0, visible=False):
    """Barras 3D como en la app: un prisma por muestra, de alto proporcional al valor, desde el suelo."""
    span = (vmax - vmin) or 1.0
    half = width / 2
    out = [f'<Folder><name>Barras 3D</name><visibility>{int(visible)}</visibility>']
    for i in range(len(values)):
        h = 0.5 + (values[i] - vmin) / span * height
        dy, dx = half / 111320, half / (111320 * np.cos(np.radians(lat[i])))
        ring = [(lon[i] - dx, lat[i] - dy), (lon[i] + dx, lat[i] - dy), (lon[i] + dx, lat[i] + dy), (lon[i] - dx, lat[i] + dy), (lon[i] - dx, lat[i] - dy)]
        coords = ' '.join(_coord(x, y, h) for x, y in ring)
        out.append(f'<Placemark><visibility>{int(visible)}</visibility><styleUrl>#s{klass[i]}</styleUrl>'
                   f'<description><![CDATA[<b>{_num(values[i])}</b> {escape(name)}]]></description>'
                   f'<Polygon><extrude>1</extrude><altitudeMode>relativeToGround</altitudeMode><outerBoundaryIs><LinearRing><coordinates>{coords}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>')
    out.append('</Folder>')
    return ''.join(out)


def overlay_kml(bounds, opacity_note=''):
    north, south, east, west = bounds
    return (f'<GroundOverlay><name>Nube de calor{escape(opacity_note)}</name><Icon><href>files/nube.png</href></Icon>'
            f'<LatLonBox><north>{north:.8f}</north><south>{south:.8f}</south><east>{east:.8f}</east><west>{west:.8f}</west></LatLonBox></GroundOverlay>')


def legend_kml(name, classes, lon, lat):
    """Punto «Leyenda» en (lon, lat), junto a los datos: al hacer clic muestra la tabla de colores. No es una leyenda
    fija en pantalla (ScreenOverlay) porque Google Earth en el navegador rechaza el archivo si la trae."""
    pct = lambda c: f'{c["pct"]:.1f} %'.replace('.', ',')
    rows = ''.join(f'<tr><td style="background:{c["color"]};width:16px"></td><td>{_num(c["lo"])} a {_num(c["hi"])}</td>'
                   f'<td style="text-align:right">{pct(c)}</td></tr>' for c in reversed(classes))
    table = f'<b>{escape(name)}</b><table cellpadding="3">{rows}</table>'
    return (f'<Placemark><name>Leyenda · {escape(name)}</name><description><![CDATA[{table}]]></description>'
            f'<Point><coordinates>{_coord(lon, lat)}</coordinates></Point></Placemark>')


def build(title, parts, files, styles=''):
    """KMZ (bytes) con doc.kml y `files` = {'files/x.png': bytes}."""
    kml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2"><Document>'
           f'<name>{escape(title)}</name><open>1</open>{styles}{"".join(parts)}</Document></kml>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('doc.kml', kml)  # Google Earth abre el primer .kml del ZIP
        for path, data in files.items():
            archive.writestr(path, data)
    return buffer.getvalue()
