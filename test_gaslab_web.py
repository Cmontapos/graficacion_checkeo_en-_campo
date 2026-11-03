import base64
import io
import json
import threading
import unittest
import urllib.request
import zipfile
from unittest import mock
from http.server import ThreadingHTTPServer

import numpy as np
from PIL import Image

import gaslab_web as w
import mapa_calor as mc
import terreno

CSV = b"""fecha_hora_utc,CO2 (ppm),SO2_ppm,Sensor_CO2_Internal_Temp,latitud,longitud,altitud_m
2026-09-16T12:00:02Z,410,0.1,30,10.0,-84.0,100
2026-09-16T12:00:00Z,400,0.0,30,10.0,-84.0,100
2026-09-16T12:00:01Z,405,,30,0,0,101
2026-09-16T13:00:00Z,500,0.5,31,10.1,-84.1,150
"""


class GasLabWebTests(unittest.TestCase):
    def test_default_gases_skip_temperatures_and_report_missing(self):
        _, dataset = w.load(CSV, 'prueba.csv')
        info = dataset.info()
        self.assertEqual(info['defaults'], ['co2_ppm', 'SO2_ppm'])
        self.assertEqual(info['missing_gases'], ['H2S'])
        self.assertNotIn('latitud', info['variables'])

    def test_minmax_keeps_extremes_of_each_bucket(self):
        y = np.zeros(10000)
        y[1234], y[8765] = 99, -99
        keep = w.minmax(y, 0, len(y), 100)
        self.assertLessEqual(len(keep), 200)
        self.assertIn(1234, keep)
        self.assertIn(8765, keep)
        np.testing.assert_array_equal(w.minmax(y, 10, 20, 100), np.arange(10, 20))

    def test_series_sorted_in_local_time_with_gap_break(self):
        _, dataset = w.load(CSV, 'prueba.csv')
        series = dataset.series(['co2_ppm'], 'America/Costa_Rica')['co2_ppm']
        start = np.datetime64('2026-09-16T06:00:00', 'ms').astype(np.int64)  # 12:00 UTC = 06:00 en Costa Rica
        self.assertEqual(series['x'][:3], [start, start + 1000, start + 2000])
        self.assertEqual(series['y'], [400, 405, 410, None, 500])  # la pausa de una hora corta la línea

    def test_limits_saturate_without_dropping_samples(self):
        _, dataset = w.load(CSV, 'prueba.csv')
        limits = w.parse_limits('{"co2_ppm": [402, 450], "SO2_ppm": [null, null]}')
        self.assertEqual(limits, {'co2_ppm': (402.0, 450.0)})  # una fila sin límites no se aplica
        series = dataset.series(['co2_ppm', 'SO2_ppm'], 'UTC', limits=limits, original=True)
        co2 = series['co2_ppm']
        self.assertEqual(co2['y'], [402, 405, 410, None, 450])
        self.assertEqual(co2['original'], [400, 405, 410, None, 500])
        self.assertEqual((co2['below'], co2['above'], co2['valid']), (1, 1, 4))
        self.assertNotIn('limits', series['SO2_ppm'])
        self.assertEqual(w.parse_limits('{"co2_ppm": [300, null]}'), {'co2_ppm': (300.0, None)})
        with self.assertRaises(ValueError):
            w.parse_limits('{"co2_ppm": [500, 400]}')

    def test_adaptive_classes_give_more_divisions_where_samples_concentrate(self):
        values = np.r_[np.linspace(0, 50, 100), np.linspace(50, 100, 900)]  # 90 % de las muestras en la mitad alta
        edges, counts = mc.adaptive_classes(values, bins=10, min_pct=5)
        self.assertEqual(counts.sum(), 1000)
        self.assertTrue((counts >= 50).all())  # ninguna división queda bajo el 5 %
        self.assertEqual((edges[0], edges[-1]), (0, 100))
        self.assertGreater((edges[1:] > 50).sum(), (edges[1:] <= 50).sum())

    def test_cloud_is_saturated_at_samples_and_empty_far_away(self):
        lon, lat = np.array([-84.0, -84.001]), np.array([10.0, 10.0])
        edges = np.array([0.0, 50.0, 100.0])
        result = mc.cloud(lon, lat, np.array([10.0, 90.0]), edges, size_m=2, opacity=1)
        alpha = result['rgba'][..., 3]
        self.assertEqual(alpha.max(), 255)
        self.assertEqual(alpha[0, 0], 0)  # esquina: a ~3 tamaños de la muestra no se pinta nada
        colors = {tuple(c) for c in result['rgba'][alpha == 255][:, :3]}
        self.assertEqual(colors, {tuple(c) for c in mc.class_colors(2)})

    def test_cloud_cools_toward_the_sides(self):
        lon, lat = np.array([-84.0]), np.array([10.0])
        edges = np.array([0.0, 25.0, 50.0, 75.0, 100.0])
        flat = mc.cloud(lon, lat, np.array([100.0]), edges, size_m=2, opacity=1)
        cool = mc.cloud(lon, lat, np.array([100.0]), edges, size_m=2, opacity=1, cool=2)
        row = cool['values'][np.nanargmax(cool['values']) // cool['values'].shape[1]]
        center = int(np.nanargmax(row))
        self.assertAlmostEqual(row[center], 100, delta=1)  # en la muestra, el valor medido
        side = row[center:][np.isfinite(row[center:])]
        self.assertTrue((np.diff(side) <= 1e-9).all())  # baja hacia los lados...
        self.assertLess(side[-1], 25)  # ...hasta la división más baja en el borde
        self.assertTrue(np.allclose(flat['values'][np.isfinite(flat['values'])], 100))  # sin enfriamiento: mismo valor

    def test_cloud_reach_sets_how_far_it_is_painted(self):
        lon, lat = np.array([-84.0]), np.array([10.0])
        edges = np.array([0.0, 100.0])
        meters = {}
        for reach in (1.5, 2.5, 4.0):
            c = mc.cloud(lon, lat, np.array([50.0]), edges, size_m=1, opacity=1, reach=reach)
            painted = (c['rgba'][..., 3] > 0).any(axis=0).sum()  # ancho pintado, en píxeles
            meters[reach] = painted * c['res'] * np.cos(np.radians(10)) / 2  # radio en metros de terreno
        for reach, radius in meters.items():
            self.assertAlmostEqual(radius, reach, delta=0.15)

    def test_heat_and_qgis_zip(self):
        _, dataset = w.load(CSV, 'prueba.csv')
        heat = dataset.heat('co2_ppm', {'co2_ppm': (None, 450.0)}, bins=4, min_pct=0)
        self.assertEqual((heat['min'], heat['max'], heat['samples']), (400, 450, 3))  # la muestra sin GPS no cuenta
        self.assertAlmostEqual(sum(c['pct'] for c in heat['classes']), 100)
        # Imagen solo de la zona visible, con la resolución de la pantalla (zoom 20: ~0,1 m por píxel).
        image = dataset.heat_image('co2_ppm', {}, size_m=1, bbox=(-84.0002, 9.9998, -83.9998, 10.0002), zoom=20)
        png = Image.open(io.BytesIO(base64.b64decode(image['image'].split(',')[1])))
        self.assertAlmostEqual(png.size[1] / png.size[0], 1 / np.cos(np.radians(10)), places=2)  # grados -> Web Mercator
        self.assertGreater(png.size[0], 300)
        self.assertGreater(np.asarray(png)[..., 3].max(), 200)  # la muestra en (-84, 10) se ve saturada
        name, body = dataset.heat_zip('co2_ppm', {}, size_m=1)
        names = zipfile.ZipFile(io.BytesIO(body)).namelist()
        self.assertEqual(sorted(n.rsplit('_', 1)[-1] for n in names), ['nube.tif', 'ppm.qgz', 'puntos.geojson', 'valores.tif'])

    def test_terrain_elevation_interpolates_and_marks_voids(self):
        # Teselas simuladas (sin internet): la altura crece 1 m por pixel hacia el este; la tesela de al lado está vacía.
        ramp = np.tile(np.arange(256, dtype=float), (256, 1))
        with mock.patch.object(terreno, '_tile', lambda z, x, y: ramp + 256 * (x % 2) if x % 4 < 2 else np.full((256, 256), -32768.0)):
            n = 2 ** 13
            lon = lambda px: px / (n * 256) * 360 - 180  # longitud del centro del pixel px (columna global)
            heights = terreno.elevation(np.array([lon(4 * 256 + 10.5), lon(4 * 256 + 10.75)]), np.array([0.0, 0.0]))
            np.testing.assert_allclose(heights, [10, 10.25], atol=1e-6)
            self.assertTrue(np.isnan(terreno.elevation(np.array([lon(2 * 256 + 5.5)]), np.array([0.0])))[0])

    def test_terrain_puts_each_sample_above_ground(self):
        _, dataset = w.load(CSV, 'prueba.csv')
        with mock.patch.object(terreno, 'elevation', lambda lon, lat: np.full(len(lon), 120.0)):
            data = dataset.terrain('co2_ppm', {})
        self.assertEqual(data['altitude'], 'altitud_m')
        self.assertEqual(data['points']['ground'], [120.0, 120.0, 120.0])
        self.assertEqual(data['points']['above'], [0.0, 0.0, 30.0])  # 100 m y 150 m medidos sobre un terreno de 120 m
        self.assertEqual(data['under'], {'count': 2, 'max': 20.0})

    def test_route_skips_invalid_gps(self):
        _, dataset = w.load(CSV, 'prueba.csv')
        route = dataset.route('UTC')
        self.assertEqual([v for v in route['lat'] if v is not None], [10.0, 10.0, 10.1])
        self.assertIn(None, route['lat'])

    def test_pages_close_after_last_window_but_not_on_reload(self):
        pages = w.Pages(0)
        self.assertFalse(pages.closed(w.FIRST_PAGE_TIMEOUT - 1))  # todavía esperando la primera ventana
        pages.ping('a', 10)
        pages.bye('a', 20)
        pages.ping('b', 21)  # recarga: la página nueva avisa antes de que pase el margen
        self.assertFalse(pages.closed(20 + w.CLOSE_GRACE))
        pages.bye('b', 30)
        self.assertFalse(pages.closed(30 + w.CLOSE_GRACE - 1))
        self.assertTrue(pages.closed(30 + w.CLOSE_GRACE))
        silent = w.Pages(0)
        silent.ping('c', 0)  # página que dejó de avisar sin despedirse
        self.assertFalse(silent.closed(w.PAGE_TIMEOUT))
        self.assertFalse(silent.closed(w.PAGE_TIMEOUT + 1))  # se da por cerrada y empieza el margen
        self.assertTrue(silent.closed(w.PAGE_TIMEOUT + 1 + w.CLOSE_GRACE))
        self.assertTrue(w.Pages(0).closed(w.FIRST_PAGE_TIMEOUT))

    def test_upload_and_series_over_http(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), w.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_address[1]}'
        try:
            request = urllib.request.Request(base + '/api/upload', data=CSV, headers={'X-Filename': 'medici%C3%B3n.csv'})
            info = json.load(urllib.request.urlopen(request))
            self.assertEqual(info['name'], 'medición')
            data = json.load(urllib.request.urlopen(f"{base}/api/series?id={info['id']}&zone=UTC&vars=co2_ppm,altitud_m"))
            self.assertEqual(set(data), {'co2_ppm', 'altitud_m'})
            bad = urllib.request.Request(base + '/api/upload', data=b'', headers={'X-Filename': 'x.csv'})
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(bad)
            self.assertEqual((info['sheet'], info['sheets']), (None, []))  # un CSV no tiene hojas
            book = io.BytesIO()
            with w.pd.ExcelWriter(book) as excel:
                w.pd.DataFrame({'x': [1]}).to_excel(excel, sheet_name='Notas', index=False)
                w.pd.read_csv(io.BytesIO(CSV)).to_excel(excel, sheet_name='Medición', index=False)
            upload = lambda sheet=None: json.load(urllib.request.urlopen(urllib.request.Request(base + '/api/upload', data=book.getvalue(),
                headers={'X-Filename': 'libro.xlsx', **({'X-Sheet': urllib.parse.quote(sheet)} if sheet else {})})))
            info = upload()
            self.assertEqual((info['sheet'], info['sheets'], info['rows']), ('Medición', ['Notas', 'Medición'], 4))
            with self.assertRaises(urllib.error.HTTPError):  # 'Notas' no tiene columna de tiempo
                upload('Notas')
            with mock.patch.object(w, 'PAGES', w.Pages(0)) as pages:
                urllib.request.urlopen(base + '/api/ping?page=x')
                self.assertIn('x', pages.seen)
                urllib.request.urlopen(urllib.request.Request(base + '/api/bye?page=x', data=b''))
                self.assertEqual(pages.seen, {})
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
