"""Mapa de calor georreferenciado de una variable del CSV (CO2, PM, temperatura...) a partir de sus coordenadas.

Cada muestra se coloca en su latitud/longitud: se puede ver como puntos de color (uno por muestra) o dividir
el mapa en celdas cuadradas; cada celda toma el
promedio, el maximo o el percentil 95 de las muestras que caen en ella (o su cantidad). Con suavizado, el valor
se reparte con un nucleo gaussiano y solo se dibuja cerca de la ruta (no se inventan valores lejos de lo medido).

Salidas (sin GDAL ni QGIS, solo numpy y Pillow): GeoTIFF Float32 en Web Mercator (EPSG:3857), puntos en
GeoJSON y un proyecto de QGIS (.qgz) con los puntos y las celdas en colores sobre OpenStreetMap / Esri satelite. La escritura
del GeoTIFF y del proyecto sigue a ../termoreferencia/src/geotiff.py y proyecto_qgis.py.
"""
from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd

STATS = {'media': 'Promedio', 'maximo': 'Máximo', 'p95': 'Percentil 95', 'muestras': 'Muestras'}
# Escala de colores tipo 'jet' (azul -> cian -> verde -> amarillo -> naranja -> rojo), como el mapa de CO2 de referencia.
RAMP = ((0.0, (30, 60, 255)), (0.25, (0, 200, 255)), (0.5, (0, 200, 80)), (0.7, (255, 230, 0)), (0.85, (255, 140, 0)), (1.0, (220, 0, 0)))
# Capas extra (p. ej. mosaico termico): otra escala (tipo 'inferno') para no confundirlas con la variable.
EXTRA_RAMP = ((0.0, (0, 0, 4)), (0.25, (87, 16, 110)), (0.5, (188, 55, 84)), (0.75, (249, 142, 9)), (1.0, (252, 255, 164)))
NODATA = -9999.0
EARTH = 6378137.0
MAX_CELLS = 4_000_000


def ramp_colors(norm, ramp=RAMP):
    """Valores 0..1 -> colores RGB (uint8) de la escala `ramp`."""
    norm = np.clip(np.nan_to_num(np.asarray(norm, float)), 0, 1)
    stops = [s for s, _ in ramp]
    return np.stack([np.interp(norm, stops, [c[k] for _, c in ramp]) for k in range(3)], -1).astype(np.uint8)


def mercator(lon, lat):
    lat = np.clip(lat, -85.05, 85.05)
    return EARTH * np.radians(lon), EARTH * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def cell_units(meters, lat):
    """Lado de una celda de `meters` metros de terreno, en unidades de Web Mercator a la latitud `lat`."""
    return meters / math.cos(math.radians(lat))


def lag_positions(t, x, y, lag, max_gap=10.0):
    """Posicion donde se tomo el aire: lo registrado en t corresponde al punto por donde se paso en t - lag.

    El sensor (sobre todo CO2) tarda unos segundos en responder; sin corregirlo, los picos aparecen corridos
    hacia adelante en la ruta. Si t - lag cae en una pausa de mas de `max_gap` s entre muestras, queda sin posicion.
    """
    if not lag or t is None:
        return x, y
    ok = np.flatnonzero(np.isfinite(t) & np.isfinite(x) & np.isfinite(y))
    out_x, out_y = np.full_like(x, np.nan), np.full_like(y, np.nan)
    if len(ok) < 2:
        return out_x, out_y
    tt = t[ok]
    target = t - lag
    j = np.searchsorted(tt, target)
    inside = np.isfinite(target) & (j > 0) & (j < len(tt))
    jj = np.clip(j, 1, len(tt) - 1)
    inside &= (tt[jj] - tt[jj - 1]) <= max_gap
    inside |= np.isfinite(target) & np.isin(target, tt)  # coincide exactamente con una muestra
    out_x[inside] = np.interp(target[inside], tt, x[ok])
    out_y[inside] = np.interp(target[inside], tt, y[ok])
    return out_x, out_y


def _blur(a, sigma):
    """Suavizado gaussiano separable (sigma en celdas), sin scipy."""
    r = int(math.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        p = np.pad(a, pad)
        n = a.shape[axis]
        a = sum(w * (p[i:i + n] if axis == 0 else p[:, i:i + n]) for i, w in enumerate(k))
    return a, k


def grid(x, y, values, cell, stat='media', smooth=0.0):
    """Celdas de lado `cell` (unidades de x/y) con el estadistico de `values`.

    Devuelve (rejilla, cantidad de muestras por celda, x0, y0); la fila 0 es la del sur (y0) y las celdas sin
    dato son NaN. `smooth`: sigma del suavizado en celdas (0 = sin suavizar).
    """
    ok = np.isfinite(x) & np.isfinite(y) & (np.isfinite(values) if stat != 'muestras' else True)
    x, y, v = x[ok], y[ok], (values[ok] if stat != 'muestras' else np.ones(ok.sum()))
    if not len(x):
        raise ValueError('No hay muestras con posición y valor para el mapa de calor.')
    margin = int(math.ceil(3 * smooth)) * cell
    x0 = math.floor(x.min() / cell) * cell - margin
    y0 = math.floor(y.min() / cell) * cell - margin
    nx = int((x.max() + margin - x0) // cell) + 1
    ny = int((y.max() + margin - y0) // cell) + 1
    if nx * ny > MAX_CELLS:
        raise ValueError('Demasiadas celdas; elige una celda más grande.')
    col, row = ((x - x0) // cell).astype(int), ((y - y0) // cell).astype(int)
    counts = np.zeros((ny, nx))
    np.add.at(counts, (row, col), 1)
    if stat in ('media', 'muestras'):
        sums = np.zeros((ny, nx))
        np.add.at(sums, (row, col), v)
        weight = counts
        values_grid = sums / np.where(counts > 0, counts, 1) if stat == 'media' else counts
    else:
        flat = row * nx + col
        agg = pd.Series(v).groupby(flat).max() if stat == 'maximo' else pd.Series(v).groupby(flat).quantile(0.95)
        values_grid = np.zeros(ny * nx)
        values_grid[agg.index.to_numpy()] = agg.to_numpy()
        values_grid = values_grid.reshape(ny, nx)
        weight = (counts > 0).astype(float)
    if smooth > 0:
        if stat == 'muestras':
            out, k = _blur(counts, smooth)
        else:
            num, k = _blur(values_grid * weight, smooth)
            den, _ = _blur(weight, smooth)
            out = num / np.where(den > 0, den, 1)
        near, _ = _blur((counts > 0).astype(float), smooth)
        c = len(k) // 2
        reach = min(c, int(round(2 * smooth)))
        out[near < k[c] * k[c + reach] * 0.999] = np.nan  # solo hasta ~2 sigma de una celda con muestras
    else:
        out = np.where(counts > 0, values_grid, np.nan)
    return out, counts, x0, y0


def write_geotiff(path, data, x0, y_top, resolution, epsg=3857, nodata=NODATA):
    """GeoTIFF Float32 de una banda (filas de norte a sur) con la esquina superior izquierda en (x0, y_top)."""
    from PIL import Image, TiffImagePlugin
    ifd = TiffImagePlugin.ImageFileDirectory_v2()
    tags = {
        33550: ((float(resolution), float(resolution), 0.0), 12),  # ModelPixelScale
        33922: ((0.0, 0.0, 0.0, float(x0), float(y_top), 0.0), 12),  # ModelTiepoint
        # GeoKeys 1.1.0: modelo proyectado, pixel = area, EPSG proyectado, metros.
        34735: ((1, 1, 0, 4, 1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, int(epsg), 3076, 0, 1, 9001), 3),
        42113: (str(int(nodata)), 2),  # GDAL_NODATA
    }
    for tag, (value, kind) in tags.items():
        ifd[tag] = value
        ifd.tagtype[tag] = kind
    data = np.where(np.isfinite(data), data, nodata).astype(np.float32)
    Image.fromarray(np.ascontiguousarray(data), 'F').save(path, tiffinfo=ifd, compression='tiff_deflate')


def read_geotiff(path):
    """(datos, x0, y_top, dx, dy, epsg) de un GeoTIFF de una banda (por ejemplo el mosaico de TermoReferencia)."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    image = Image.open(path)
    data = np.asarray(image.getchannel(0) if image.mode in ('LA', 'RGBA', 'RGB') else image, np.float32)
    dx, dy = image.tag_v2[33550][:2]
    x0, y_top = image.tag_v2[33922][3:5]
    keys = image.tag[34735]
    epsg = next((keys[i + 3] for i in range(4, len(keys), 4) if keys[i] in (3072, 2048)), None)
    if epsg is None:
        raise ValueError(f'{Path(path).name} no declara su sistema de coordenadas (EPSG).')
    nodata = image.tag_v2.get(42113)
    if nodata not in (None, ''):
        data = np.where(data == float(nodata), np.nan, data)
    return data, x0, y_top, dx, dy, epsg


def _proj4(epsg):
    if epsg == 3857:
        return '+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +k=1 +units=m +nadgrids=@null +wktext +no_defs'
    if 32601 <= epsg <= 32660 or 32701 <= epsg <= 32760:  # UTM WGS84 (lo que produce TermoReferencia)
        return f'+proj=utm +zone={epsg % 100}{" +south" if epsg > 32700 else ""} +datum=WGS84 +units=m +no_defs'
    return ''


def _srs(epsg):
    # Sin pyproj: QGIS reconstruye el sistema con proj4 + authid (solo authid no basta para el CRS del proyecto).
    return f'<spatialrefsys><proj4>{_proj4(epsg)}</proj4><authid>EPSG:{epsg}</authid><srid>{epsg}</srid></spatialrefsys>'


def _pipe(lo, hi, opacity, ramp=RAMP, steps=12):
    items = ''.join(f'<item alpha="255" value="{lo + (hi - lo) * t:.6g}" label="{lo + (hi - lo) * t:.4g}" '
                    f'color="#{r:02x}{g:02x}{b:02x}"/>'
                    for t, (r, g, b) in zip(np.linspace(0, 1, steps), ramp_colors(np.linspace(0, 1, steps), ramp)))
    return f'''<pipe>
        <rasterrenderer type="singlebandpseudocolor" band="1" opacity="{opacity}" alphaBand="-1" classificationMin="{lo:.6g}" classificationMax="{hi:.6g}" nodataColor="">
          <rasterTransparency/>
          <minMaxOrigin><limits>None</limits><extent>WholeRaster</extent><statAccuracy>Estimated</statAccuracy>
            <cumulativeCutLower>0.02</cumulativeCutLower><cumulativeCutUpper>0.98</cumulativeCutUpper><stdDevFactor>2</stdDevFactor></minMaxOrigin>
          <rastershader>
            <colorrampshader colorRampType="INTERPOLATED" classificationMode="1" clip="0" minimumValue="{lo:.6g}" maximumValue="{hi:.6g}">{items}</colorrampshader>
          </rastershader>
        </rasterrenderer>
        <brightnesscontrast brightness="0" contrast="0" gamma="1"/>
        <huesaturation saturation="0" colorizeOn="0" grayscaleMode="0" colorizeStrength="100"/>
        <rasterresampler maxOversampling="2"/>
        <resamplingStage>resamplingFilter</resamplingStage>
      </pipe>'''


BASEMAPS = (
    ('OpenStreetMap_7d0f0b5a_3c2e_4e8a_9b1d_000000000001', 'OpenStreetMap', 'https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png', False),
    ('Esri_satelite_7d0f0b5a_3c2e_4e8a_9b1d_000000000002', 'Esri satelite',
     'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/%7Bz%7D/%7By%7D/%7Bx%7D', True),
)
WEB_LIMIT = 20037508.342789244


def _layer(layer_id, name, source, provider, epsg, pipe, extent):
    xmin, ymin, xmax, ymax = extent
    return f'''    <maplayer type="raster" hasScaleBasedVisibilityFlag="0" refreshOnNotifyEnabled="0" autoRefreshEnabled="0">
      <extent><xmin>{xmin}</xmin><ymin>{ymin}</ymin><xmax>{xmax}</xmax><ymax>{ymax}</ymax></extent>
      <id>{layer_id}</id>
      <datasource>{escape(source)}</datasource>
      <layername>{escape(name)}</layername>
      <srs>{_srs(epsg)}</srs>
      <provider>{provider}</provider>
      {pipe}
      <blendMode>0</blendMode>
    </maplayer>
'''


def _source(file, project):
    """Ruta relativa al proyecto si el archivo esta en su carpeta o debajo; si no, absoluta."""
    try:
        return './' + Path(file).resolve().relative_to(Path(project).resolve().parent).as_posix()
    except ValueError:
        return Path(file).resolve().as_posix()


def _points_layer(layer_id, name, source, field, lo, hi, extent, size_mm, classes=20):
    """Capa vectorial de puntos (GeoJSON, WGS84) coloreada por `field` en `classes` rangos de RAMP; los altos se dibujan encima."""
    edges = np.linspace(lo, hi, classes + 1)
    colors = ramp_colors((np.arange(classes) + 0.5) / classes)
    ranges = ''.join(f'<range symbol="{i}" lower="{edges[i] if i else lo - abs(lo) * 1e-9 - 1e-9:.10g}" upper="{edges[i + 1]:.10g}" '
                     f'label="{edges[i]:.4g} – {edges[i + 1]:.4g}" render="true"/>' for i in range(classes))
    symbols = ''.join(f'''<symbol alpha="1" name="{i}" clip_to_extent="1" type="marker" force_rhr="0">
            <layer class="SimpleMarker" enabled="1" locked="0" pass="0"><Option type="Map">
              <Option value="circle" name="name" type="QString"/>
              <Option value="{r},{g},{b},255" name="color" type="QString"/>
              <Option value="{size_mm}" name="size" type="QString"/>
              <Option value="MM" name="size_unit" type="QString"/>
              <Option value="no" name="outline_style" type="QString"/>
            </Option></layer>
          </symbol>''' for i, (r, g, b) in enumerate(colors))
    attr, order = escape(field, {'"': '&quot;'}), escape(f'"{field}"')
    xmin, ymin, xmax, ymax = extent
    return f'''    <maplayer type="vector" geometry="Point" wkbType="Point" hasScaleBasedVisibilityFlag="0" refreshOnNotifyEnabled="0" autoRefreshEnabled="0" readOnly="0">
      <extent><xmin>{xmin}</xmin><ymin>{ymin}</ymin><xmax>{xmax}</xmax><ymax>{ymax}</ymax></extent>
      <id>{layer_id}</id>
      <datasource>{escape(source)}</datasource>
      <layername>{escape(name)}</layername>
      <srs><spatialrefsys><proj4>+proj=longlat +datum=WGS84 +no_defs</proj4><authid>EPSG:4326</authid><srid>4326</srid></spatialrefsys></srs>
      <provider encoding="UTF-8">ogr</provider>
      <renderer-v2 type="graduatedSymbol" attr="{attr}" graduatedMethod="GraduatedColor" symbollevels="0" forceraster="0" enableorderby="1" referencescale="-1">
        <ranges>{ranges}</ranges>
        <symbols>{symbols}</symbols>
        <orderby><orderByClause asc="1" nullsFirst="1">{order}</orderByClause></orderby>
      </renderer-v2>
      <blendMode>0</blendMode>
    </maplayer>
'''


def write_qgis(path, layers, title='', points=None):
    """Proyecto QGIS (.qgz) con `layers` = [(tif, nombre, (min, max), opacidad, visible), ...] (la primera arriba) y mapas base.

    `points` = (geojson, nombre, campo, (min, max), tamano_mm, (xmin, ymin, xmax, ymax) en grados): capa de puntos
    encima de todo. Las capas se refieren con ruta relativa al proyecto si estan en su carpeta o debajo.
    """
    path = Path(path)
    tree, maps, view = [], [], None
    if points:
        geojson, name, field, (lo, hi), size_mm, extent = points
        layer_id = 'puntos_7d0f0b5a_3c2e_4e8a_9b1d_000000000099'
        tree.append(f'    <layer-tree-layer id="{layer_id}" name="{escape(name)}" source="{escape(_source(geojson, path))}" providerKey="ogr" checked="Qt::Checked" expanded="1"/>')
        maps.append(_points_layer(layer_id, name, _source(geojson, path), field, lo, hi, extent, size_mm))
    for order, (tif, name, (lo, hi), opacity, visible) in enumerate(layers):
        data, x0, y_top, dx, dy, epsg = read_geotiff(tif)
        extent = (x0, y_top - data.shape[0] * dy, x0 + data.shape[1] * dx, y_top)
        if order == 0:
            view = extent
        source = _source(tif, path)
        layer_id = f'capa_{order}_7d0f0b5a_3c2e_4e8a_9b1d_{order + 100:012d}'
        tree.append(f'    <layer-tree-layer id="{layer_id}" name="{escape(name)}" source="{escape(source)}" providerKey="gdal" checked="Qt::{"Checked" if visible else "Unchecked"}" expanded="1"/>')
        maps.append(_layer(layer_id, name, source, 'gdal', epsg, _pipe(lo, hi, opacity, RAMP if order == 0 else EXTRA_RAMP), extent))
    background = _pipe(0, 1, 1).replace('type="singlebandpseudocolor"', 'type="singlebandcolordata"')
    background = background[:background.index('<rastershader>')] + background[background.index('</rasterrenderer>'):]
    for layer_id, name, url, visible in BASEMAPS:
        source = f'type=xyz&url={url}&zmax=19&zmin=0'
        tree.append(f'    <layer-tree-layer id="{layer_id}" name="{name}" source="{escape(source)}" providerKey="wms" '
                    f'checked="Qt::{"Checked" if visible else "Unchecked"}" expanded="1"/>')
        maps.append(_layer(layer_id, name, source, 'wms', 3857, background, (-WEB_LIMIT, -WEB_LIMIT, WEB_LIMIT, WEB_LIMIT)))
    mx, my = (view[2] - view[0]) * 0.05, (view[3] - view[1]) * 0.05
    view = (view[0] - mx, view[1] - my, view[2] + mx, view[3] + my)
    title = title or path.stem
    xml = f'''<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.22.4" projectname="{escape(title)}">
  <homePath path=""/>
  <title>{escape(title)}</title>
  <projectCrs>{_srs(3857)}</projectCrs>
  <layer-tree-group>
{chr(10).join(tree)}
  </layer-tree-group>
  <mapcanvas name="theMapCanvas" annotationsVisible="1">
    <units>meters</units>
    <extent><xmin>{view[0]}</xmin><ymin>{view[1]}</ymin><xmax>{view[2]}</xmax><ymax>{view[3]}</ymax></extent>
    <rotation>0</rotation>
    <destinationsrs>{_srs(3857)}</destinationsrs>
  </mapcanvas>
  <projectlayers>
{"".join(maps)}  </projectlayers>
  <properties>
    <Paths><Absolute type="bool">false</Absolute></Paths>
    <SpatialRefSys><ProjectionsEnabled type="int">1</ProjectionsEnabled></SpatialRefSys>
  </properties>
  <ProjectViewSettings UseProjectScales="0">
    <Scales/>
    <DefaultViewExtent xmin="{view[0]}" ymin="{view[1]}" xmax="{view[2]}" ymax="{view[3]}">{_srs(3857)}</DefaultViewExtent>
  </ProjectViewSettings>
</qgis>
'''
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as qgz:
        qgz.writestr(path.stem + '.qgs', xml)
    return path


def write_points(path, lat, lon, values, name, times=None):
    """GeoJSON (WGS84) con una entidad por muestra: valor y, si hay, fecha UTC."""
    features = []
    keep = np.flatnonzero(np.isfinite(lat) & np.isfinite(lon) & np.isfinite(values))
    for i in keep[np.argsort(values[keep], kind='stable')]:  # de menor a mayor: los valores altos quedan encima
        props = {name: float(values[i])}
        if times is not None and times[i]:
            props['fecha_utc'] = str(times[i])
        features.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [round(float(lon[i]), 8), round(float(lat[i]), 8)]},
                         'properties': props})
    Path(path).write_text(json.dumps({'type': 'FeatureCollection', 'features': features}), encoding='utf-8')
    return len(features)


def export(base, lat, lon, values, name, cell_m=10, stat='media', smooth=1.0, t=None, lag=0.0, times=None,
           value_range=None, extra=(), lat_ref=None, mode='celdas', point_mm=1.6):
    """Escribe <base>.tif, <base>_puntos.geojson y <base>.qgz. Devuelve un resumen de texto.

    lat/lon en grados (arreglos alineados con `values`), t en segundos (para el desfase), value_range = (min, max)
    validos (los valores fuera se ignoran), extra = GeoTIFF adicionales para el proyecto (p. ej. mosaico termico),
    lat_ref = latitud para pasar `cell_m` a unidades de Web Mercator (por defecto, la mediana de las muestras),
    mode = 'puntos' o 'celdas': la capa que queda encendida en QGIS (siempre se escriben las dos), point_mm = tamano
    de los puntos en QGIS.
    """
    base = Path(base)
    base = base.with_suffix('') if base.suffix.lower() in ('.tif', '.tiff', '.qgz') else base
    values = np.asarray(values, float).copy()
    if value_range is not None:
        lo, hi = value_range
        values[(values < lo if lo is not None else False) | (values > hi if hi is not None else False)] = np.nan
    x, y = mercator(np.asarray(lon, float), np.asarray(lat, float))
    x, y = lag_positions(t, x, y, lag)
    ok = np.isfinite(x) & np.isfinite(y)
    if not ok.any():
        raise ValueError('No hay muestras con coordenadas válidas.')
    lat_ref = float(np.nanmedian(np.asarray(lat, float)[ok & np.isfinite(values)])) if lat_ref is None else lat_ref
    cell = cell_units(cell_m, lat_ref)
    data, counts, x0, y0 = grid(x, y, values, cell, stat, smooth)
    tif = base.with_suffix('.tif')
    write_geotiff(tif, np.flipud(data), x0, y0 + data.shape[0] * cell, cell)
    shown = data[np.isfinite(data)]
    lo, hi = float(np.nanmin(shown)), float(np.nanmax(shown))
    lat_used = np.degrees(2 * np.arctan(np.exp(y / EARTH)) - np.pi / 2)  # posiciones ya corregidas por el desfase
    lon_used = np.degrees(x / EARTH)
    geojson = base.parent / f'{base.name}_puntos.geojson'
    points = write_points(geojson, lat_used, lon_used, values, name, times)
    used = np.isfinite(lat_used) & np.isfinite(values)
    plo, phi = float(values[used].min()), float(values[used].max())
    point_layer = (geojson, f'{name} (puntos)', name, (plo, phi if phi > plo else plo + 1), point_mm,
                   (lon_used[used].min(), lat_used[used].min(), lon_used[used].max(), lat_used[used].max()))
    layers = [(tif, f'{name} ({STATS[stat].lower()}, celdas {cell_m:g} m)', (lo, hi if hi > lo else lo + 1), 0.85, mode != 'puntos')]
    for path in extra:
        other = read_geotiff(path)[0]
        p2, p98 = np.nanpercentile(other, [2, 98])
        layers.append((Path(path), Path(path).stem, (float(p2), float(p98)), 1.0, True))
    qgz = write_qgis(base.with_suffix('.qgz'), layers, f'{name} · {base.name}', point_layer)
    return (f'{points:,} puntos de {name} ({plo:.4g} → {phi:.4g}). '
            f'{STATS[stat]} en celdas de {cell_m:g} m'
            f'{f", suavizado {smooth:g} celdas" if smooth else ""}{f", desfase {lag:g} s" if lag else ""}: '
            f'{int((counts > 0).sum()):,} celdas con datos, {lo:.4g} → {hi:.4g}.\n'
            f'{tif}\n{qgz}\n{base.parent / (base.name + "_puntos.geojson")}')
