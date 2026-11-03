"""Altura del terreno (modelo de elevación) bajo cada muestra, para el paso 4 · Terreno 3D de GasLab 2.0.

Usa AWS Terrain Tiles (formato Terrarium, gratis y sin cuenta, https://registry.opendata.aws/terrain-tiles/): cada
pixel RGB codifica la altura sobre el nivel del mar como R·256 + G + B/256 - 32768 metros. Las teselas se guardan
en ~/.cache/gaslab_tiles/terrarium para no descargarlas otra vez. Es la misma fuente que dibuja el relieve en la
página, así que los puntos quedan a la altura correcta sobre el mismo terreno.
"""
from __future__ import annotations

import io
import urllib.request
from pathlib import Path

import numpy as np

URL = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'
CACHE = Path.home() / '.cache' / 'gaslab_tiles' / 'terrarium'
# ~15 m por pixel a latitudes medias (el dato de origen es de ~30 m en la mayor parte del mundo). Algunas teselas del
# zoom 14 vienen vacias (p. ej. sobre el cráter de Vulcano) mientras que las del 13 estan completas.
ZOOM = 13
VOID = -1000  # pixeles sin dato vienen como -32768
MAX_TILES = 64


def _tile(z, x, y):
    path = CACHE / str(z) / str(x) / f'{y}.png'
    if not path.exists():
        request = urllib.request.Request(URL.format(z=z, x=x, y=y), headers={'User-Agent': 'GasLab/2.0'})
        try:
            data = urllib.request.urlopen(request, timeout=20).read()
        except OSError as exc:
            raise ValueError('No se pudo descargar la altura del terreno (¿sin internet?). '
                             'El terreno 3D necesita conexión la primera vez que se abre una zona.') from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    from PIL import Image
    rgb = np.asarray(Image.open(io.BytesIO(path.read_bytes())).convert('RGB'), float)
    return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768


def elevation(lon, lat, zoom=ZOOM):
    """Altura del terreno (m sobre el nivel del mar) en cada lon/lat, con interpolación bilineal; NaN donde la
    fuente no tiene dato."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    n = 2 ** zoom
    # Posición en pixeles del mundo (teselas de 256) a ese zoom.
    px = (lon + 180) / 360 * n * 256 - 0.5
    py = (1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * n * 256 - 0.5
    x0, y0 = np.floor(px).astype(int), np.floor(py).astype(int)
    tiles = {(int(tx), int(ty)) for tx, ty in zip(np.r_[x0, x0 + 1] // 256, np.r_[y0, y0 + 1] // 256)}
    if len(tiles) > MAX_TILES:
        raise ValueError('La ruta es demasiado extensa para el terreno 3D.')
    cache = {key: np.where(t < VOID, np.nan, t) for key, t in ((key, _tile(zoom, key[0] % n, key[1])) for key in tiles)}

    def at(x, y):
        out = np.empty(len(x))
        for i, (xi, yi) in enumerate(zip(x, y)):
            out[i] = cache[(xi // 256, yi // 256)][yi % 256, xi % 256]
        return out

    fx, fy = px - x0, py - y0
    top = at(x0, y0) * (1 - fx) + at(x0 + 1, y0) * fx
    bottom = at(x0, y0 + 1) * (1 - fx) + at(x0 + 1, y0 + 1) * fx
    return top * (1 - fy) + bottom * fy
