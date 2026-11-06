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

    def test_min_pct_0_is_linear_and_the_default(self):
        values = np.r_[np.full(900, 400.0) + np.linspace(0, 5, 900), np.linspace(405, 2000, 100)]
        edges, counts = mc.adaptive_classes(values, bins=20)  # sin % mínimo: no se une ninguna
        self.assertEqual(len(counts), 20)
        self.assertTrue(np.allclose(np.diff(edges), 80))
        exp, counts = mc.adaptive_classes(values, bins=20, spacing='exponencial')
        self.assertEqual((len(counts), counts.sum()), (20, 1000))
        widths = np.diff(exp)
        self.assertTrue(np.allclose(widths[1:] / widths[:-1], 10 ** (3 / 19)))  # cada una un factor fijo más ancha
        self.assertAlmostEqual(widths[-1] / widths[0], 1000)

    def test_original_is_the_old_scale(self):
        rng = np.random.default_rng(1)
        values = np.r_[rng.normal(420, 8, 900), rng.uniform(430, 1500, 100)]
        old_counts, old_edges = np.histogram(values, bins=20, range=(values.min(), values.max()))  # algoritmo de antes, 5 %
        edges, counts = list(old_edges), list(old_counts)
        while len(counts) > 1 and min(counts) < 50:
            i = int(np.argmin(counts))
            j = i + 1 if i == 0 else i - 1 if i == len(counts) - 1 else (i - 1 if counts[i - 1] <= counts[i + 1] else i + 1)
            a, b = min(i, j), max(i, j)
            counts[a:b + 1] = [counts[a] + counts[b]]
            del edges[b]
        e, c = mc.adaptive_classes(values, bins=20, min_pct=mc.ORIGINAL_MIN_PCT, spacing='original')  # 5 %: igual que antes
        self.assertTrue(np.array_equal(e, edges) and np.array_equal(c, counts))
        self.assertLess(len(c), 20)
        self.assertEqual(len(mc.adaptive_classes(values, bins=20, min_pct=0, spacing='original')[1]), 20)  # el % se puede cambiar

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
        flat = mc.cloud(lon, lat, np.array([100.0]), edges, size_m=2, opacity=1, reach=15)
        cool = mc.cloud(lon, lat, np.array([100.0]), edges, size_m=2, opacity=1, cool=2, reach=15)  # 30 m
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
        # Sin columna de altura: la página pega las muestras al terreno.
        _, flat = w.load(CSV.replace(b',altitud_m', b'').replace(b',100\n', b'\n').replace(b',101\n', b'\n').replace(b',150\n', b'\n'), 'plano.csv')
        with mock.patch.object(terreno, 'elevation', lambda lon, lat: np.full(len(lon), 120.0)):
            data = flat.terrain('co2_ppm', {})
        self.assertEqual((data['altitude'], data['points']['ground'], data['no_alt']), (None, [120.0, 120.0, 120.0], 3))

    def test_reach_only_extends_the_cloud_and_cooling_sets_the_heat_zone(self):
        lon, lat = np.array([-84.0, -84.0002]), np.array([10.0, 10.0])  # dos muestras a ~22 m
        edges = np.linspace(0, 100, 6)
        x, y = mc.mercator(np.array([-84.0006, -83.9996]), np.array([9.9995, 10.0005]))
        view = dict(bounds=(x[0], y[0], x[1], y[1]), res=(x[1] - x[0]) / 400)
        run = lambda **k: mc.cloud(lon, lat, np.array([90.0, 30.0]), edges, size_m=1, opacity=1, **{'cool': 1, 'reach': 20, **k}, **view)
        short, long = run(reach=20), run(reach=40)
        center = short['rgba'][..., 3] == 255  # la parte opaca con alcance 20 m
        self.assertTrue(center.sum() > 1000)
        np.testing.assert_array_equal(short['rgba'][center], long['rgba'][center])  # el alcance no cambia el centro
        self.assertGreater((long['rgba'][..., 3] > 0).sum(), (short['rgba'][..., 3] > 0).sum())  # solo llega más lejos
        hot = lambda c: (c['values'] > 60).sum()  # zona de calor: valores sobre 60
        self.assertGreater(hot(run(cool=0.5)), hot(run(cool=1)))
        self.assertGreater(hot(run(cool=1)), hot(run(cool=4)))  # más enfriamiento = zona de calor más chica

    def test_cloud_reach_up_to_30_m_with_a_small_size(self):
        edges = np.array([0.0, 50.0, 100.0])
        for reach_m in (10, 30):
            c = mc.cloud(np.array([-84.0]), np.array([10.0]), np.array([50.0]), edges, size_m=1, opacity=1, reach=reach_m, cool=2)
            radius = (c['rgba'][..., 3] > 0).any(axis=0).sum() * c['res'] * np.cos(np.radians(10)) / 2
            self.assertAlmostEqual(radius, reach_m, delta=0.05 * reach_m + 0.3)
            painted = c['rgba'][..., 3] > 0
            self.assertFalse(np.isnan(c['values'][painted]).any())  # la cola lejana tiene valor (no se corta por precisión)
        self.assertEqual(mc._fast_size(3070), 3072)

    def test_route_skips_invalid_gps(self):
        _, dataset = w.load(CSV, 'prueba.csv')
        route = dataset.route('UTC')
        self.assertEqual([v for v in route['lat'] if v is not None], [10.0, 10.0, 10.1])
        self.assertIn(None, route['lat'])

    def test_calibrated_columns_are_a_second_version_with_the_same_names(self):
        raw = (b'TIMESTAMP;Latitude;Longitude;CO2_Concentration_Avg;Sensor_2_ppm_Avg;Latitude_cal;Longitude_cal;CO2_Concentration_Avg_cal;Sensor_2_ppm_Avg_cal\n'
               b'2026-09-16 00:00:00;38,41;14,95;400;1,5;38,41;14,95;410;2,5\n'
               b'2026-09-16 00:00:01;38,42;14,96;401;1,6;38,42;14,96;411;2,6\n')
        key, original = w.load(raw, 'Flight_Data.csv')
        self.assertEqual(original.info()['cal_id'], key + '-cal')
        calibrated = w.DATASETS[key + '-cal']
        self.assertEqual(original.variables, calibrated.variables)
        self.assertNotIn('Sensor_2_ppm_Avg_cal', original.variables)
        self.assertEqual((original.lat_col, calibrated.lat_col), ('latitud', 'latitud'))  # 'Latitude_cal' va con 'latitud'
        self.assertEqual(original.values('CO2_Concentration_Avg').tolist(), [400, 401])
        self.assertEqual(calibrated.values('CO2_Concentration_Avg').tolist(), [410, 411])
        self.assertEqual(w.load(CSV, 'sin_cal.csv')[1].info()['cal_id'], None)
        both = calibrated.series(['CO2_Concentration_Avg'], 'UTC', other=original)['CO2_Concentration_Avg']
        self.assertEqual((both['y'], both['compare'], both['diff']), ([410, 411], [400, 401], {'mean': 10.0, 'max': 10.0}))
        self.assertNotIn('compare', calibrated.series(['CO2_Concentration_Avg'], 'UTC')['CO2_Concentration_Avg'])

    def test_drone_gps_is_a_second_source_for_the_maps(self):
        raw = (b'timestamp,co2_ppm,latitud,longitud,altitud_m,latitud_dron,longitud_dron,altitud_dron_m,altura_relativa_dron_m\n'
               b'2026-09-16T12:00:00Z,400,10.0,-84.0,100,10.0001,-84.0,130,30\n'
               b'2026-09-16T12:00:01Z,410,10.0,-84.0,100,,,,\n'
               b'2026-09-16T12:00:02Z,420,10.0,-84.0,100,10.0,-84.0,131,31\n')
        _, dataset = w.load(raw, 'dron.csv')
        drone = dataset.info()['drone']
        self.assertEqual((drone['lat'], drone['lon'], drone['alt'], drone['rows']), ('latitud_dron', 'longitud_dron', 'altitud_dron_m', 2))
        self.assertAlmostEqual(drone['gap']['max'], 11.1, delta=0.1)  # 0,0001° de latitud
        self.assertNotIn('latitud_dron', dataset.variables)
        self.assertIn('altura_relativa_dron_m', dataset.variables)
        self.assertEqual([v for v in dataset.route('UTC', 'dron')['lat'] if v is not None], [10.0001, 10.0])
        self.assertEqual(dataset.heat('co2_ppm', {}, gps='dron')['samples'], 2)  # la fila sin dron queda fuera
        with mock.patch.object(terreno, 'elevation', lambda lon, lat: np.full(len(lon), 100.0)):
            self.assertEqual(dataset.terrain('co2_ppm', {}, gps='dron')['altitude'], 'altitud_dron_m')
        self.assertIsNone(w.load(CSV, 'sin_dron.csv')[1].info()['drone'])
        with self.assertRaises(ValueError):
            w.load(CSV, 'sin_dron.csv')[1].route('UTC', 'dron')
        self.assertEqual(w.drone_columns(['Drone Lat', 'drone_lng', 'UAV height rel', 'UAV altitude'])['alt'], 'UAV altitude')

    def test_campbell_toa5_dat(self):
        dat = ('"TOA5","LOGGER","CR300","1","OS","CPU:x.cr300","1","Data_Results"\r\n'
               '"TIMESTAMP","RECORD","Sensor_SO2_ppm_Avg","CO2_Concentration_Avg","Latitude","Longitude","Altitude"\r\n'
               '"TS","RN","ppm","","grados","grados",""\r\n'
               '"","","Avg","Avg","Smp","Smp","Smp"\r\n'
               '"2025-05-28 20:11:48",1,0.5,"NAN",9.9396,-84.0424,1251.8\r\n'
               '"2025-05-28 20:11:47",0,0.2,410,9.9397,-84.0425,1251.0\r\n').encode()
        info = w.load(dat, 'vuelo.dat')[1].info()
        self.assertEqual((info['rows'], info['time_column'], info['gps']), (2, 'timestamp', True))
        self.assertIn('CO2_Concentration_Avg', info['variables'])
        self.assertIn('Sensor_SO2_ppm_Avg', info['defaults'])

    def test_excel_like_version_1_with_preview(self):
        import openpyxl
        _, dataset = w.load(CSV, 'prueba.csv')
        name, body = dataset.excel(['co2_ppm', 'SO2_ppm'], 'UTC')
        book = openpyxl.load_workbook(io.BytesIO(body))
        self.assertEqual((name, book.sheetnames), ('prueba.xlsx', ['Resumen', 'Datos', 'Gráficas', 'Ruta']))
        self.assertEqual([c.value for c in book['Datos'][1]], ['Fecha y hora (UTC)', 'Transcurrido (s)', 'co2_ppm', 'SO2_ppm', 'latitud', 'longitud', 'altitud_m'])
        self.assertEqual([r[2].value for r in book['Datos'].iter_rows(min_row=2)], [400, 405, 410, 500])  # en orden de tiempo
        preview = dataset.excel_preview(['co2_ppm', 'SO2_ppm'], 'UTC')
        self.assertEqual(preview['headers'], [c.value for c in book['Datos'][1]])
        self.assertEqual(preview['stats'][0], {'name': 'co2_ppm', 'min': 400, 'mean': 428.75, 'max': 500, 'count': 4})
        self.assertEqual(preview['first'][0][:3], ['16/09/2026 12:00:00', 0.0, 400])
        # Solo el tramo visible: de 12:00:00 a 12:00:01 (ms 'de reloj' de la zona).
        t, _ = dataset.local_ms('UTC')
        name, body = dataset.excel(['co2_ppm'], 'UTC', t[1], t[2])
        self.assertEqual((name, openpyxl.load_workbook(io.BytesIO(body))['Datos'].max_row), ('prueba_20260916_1200.xlsx', 3))
        with self.assertRaises(ValueError):
            dataset.excel([], 'UTC')

    def test_excel_uses_the_limits_of_step_2(self):
        import openpyxl
        _, dataset = w.load(CSV, 'prueba.csv')  # co2_ppm: 400, 405, 410, 500
        limits = {'co2_ppm': (402.0, 408.0)}
        _, body = dataset.excel(['co2_ppm', 'SO2_ppm'], 'UTC', limits=limits)
        book = openpyxl.load_workbook(io.BytesIO(body))
        self.assertEqual([r[2].value for r in book['Datos'].iter_rows(min_row=2)], [402, 405, 408, 408])
        self.assertIn('límites: co2_ppm mín 402 y máx 408', book['Resumen']['A1'].value)
        preview = dataset.excel_preview(['co2_ppm'], 'UTC', limits=limits)
        self.assertEqual((preview['stats'][0]['min'], preview['stats'][0]['max']), (402, 408))
        self.assertLessEqual(max(v for v in preview['charts']['co2_ppm']['y'] if v is not None), 408)
        self.assertEqual(dataset.columns['co2_ppm'].max(), 500)  # el dato original no cambia

    def test_tramos_like_version_1_limit_every_step(self):
        _, dataset = w.load(CSV, 'prueba.csv')  # 12:00:00, :01, :02 y 13:00:00 (una pausa de una hora)
        data = dataset.tramos('UTC', 1200)
        self.assertEqual([(t['rows'], t['seconds']) for t in data['tramos']], [(3, 2.0), (1, 0.0)])
        self.assertEqual(data['days'][0]['hours'], [12, 13])
        self.assertEqual(len(dataset.tramos('UTC', 7200)['tramos']), 1)
        first = data['tramos'][0]
        window = dataset.window('UTC', first['t0'], first['t1'])
        self.assertEqual(window, (0, 3))
        self.assertEqual(dataset.series(['co2_ppm'], 'UTC', window=window)['co2_ppm']['y'], [400, 405, 410])
        self.assertEqual(dataset.heat('co2_ppm', {}, window=window)['samples'], 2)  # la muestra 0,0 no tiene GPS
        self.assertEqual([v for v in dataset.route('UTC', window=window)['lat'] if v is not None], [10.0, 10.0])
        with self.assertRaises(ValueError):
            dataset.heat('co2_ppm', {}, window=dataset.window('UTC', first['t0'] + 500, first['t0'] + 900))  # sin muestras con GPS
        self.assertIsNone(dataset.window('UTC'))
        self.assertEqual(dataset.excel(['co2_ppm'], 'UTC', first['t0'], first['t1'], tag='tramo1')[0], 'prueba_tramo1_20260916_1200.xlsx')

    def test_kmz_for_google_earth(self):
        from xml.dom import minidom
        _, dataset = w.load(CSV, 'prueba.csv')
        read = lambda body: zipfile.ZipFile(io.BytesIO(body))
        name, body = dataset.kmz('route')
        kml = read(body).read('doc.kml').decode()
        minidom.parseString(kml)
        self.assertEqual(name, 'prueba_ruta.kmz')
        self.assertNotIn('<LineString>', kml)  # aquí no hay dos puntos seguidos con GPS: solo Inicio y Fin
        self.assertIn('2026-09-16T12:00:00Z', kml)  # Inicio con su hora
        _, line = w.load(b'timestamp,co2_ppm,latitud,longitud\n2026-09-16T12:00:00Z,1,10,-84\n2026-09-16T12:00:01Z,2,10.0001,-84\n', 'linea.csv')
        self.assertIn('<coordinates>-84.0000000,10.0000000 -84.0000000,10.0001000</coordinates></LineString>', read(line.kmz('route')[1]).read('doc.kml').decode())
        name, body = dataset.kmz('heat', 'co2_ppm', {}, look=(1.0, 0.95, 1.0, 30.0))
        archive = read(body)
        kml = archive.read('doc.kml').decode()
        minidom.parseString(kml)
        self.assertEqual(sorted(archive.namelist()), ['doc.kml', 'files/nube.png'])
        self.assertIn('<GroundOverlay>', kml)
        self.assertNotIn('<ScreenOverlay>', kml)  # Google Earth en el navegador la rechaza
        self.assertNotIn('<TimeStamp>', kml)  # también
        self.assertIn('<td style="background:', kml)  # leyenda también como tabla (Google Earth en el navegador)
        self.assertIn(w.kmz.ICON, kml)
        self.assertNotIn('<Polygon>', kml)  # en 2D solo la nube (con la leyenda y la ruta)
        name, body = dataset.kmz('bars', 'co2_ppm', {})
        bars = read(body).read('doc.kml').decode()
        self.assertEqual((name, bars.count('<Polygon>'), '<GroundOverlay>' in bars), ('prueba_co2_ppm_barras3d.kmz', 3, False))  # 3D: las barras
        north = float(kml.split('<north>')[1].split('<')[0])
        self.assertAlmostEqual(north, 10.1 + 31.5 / 111320, delta=0.0002)  # la nube llega ~30 m (+ medio tamaño) más allá
        _, body = dataset.kmz('terrain', 'co2_ppm', {}, offset=-10)
        kml = read(body).read('doc.kml').decode()
        self.assertIn('<altitudeMode>absolute</altitudeMode><coordinates>-84.0000000,10.0000000,90.00', kml)  # 100 m − 10 m
        _, body = dataset.kmz('terrain', 'co2_ppm', {}, mode='ground', offset=5)
        self.assertIn('<altitudeMode>relativeToGround</altitudeMode><coordinates>-84.0000000,10.0000000,5.00', read(body).read('doc.kml').decode())
        self.assertIn('ffbbggrr'.replace('bb', '86').replace('gg', '7f').replace('rr', '00'), w.kmz.kml_color('#007f86'))

    def test_old_files_leave_memory_together_with_their_calibrated_version(self):
        raw = b'TIMESTAMP;x;x_cal\n2026-09-16 00:00:00;1;2\n'
        with mock.patch.object(w, 'DATASETS', {}):
            keys = [w.load(raw, 'f.csv')[0] for _ in range(w.KEEP_DATASETS + 1)]
            self.assertEqual(set(w.DATASETS), {k + suffix for k in keys[1:] for suffix in ('', '-cal')})

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
            excel = urllib.request.urlopen(f"{base}/api/excel?id={info['id']}&zone=UTC&vars=co2_ppm")
            self.assertIn("filename*=UTF-8''medici%C3%B3n.xlsx", excel.headers['Content-Disposition'])
            self.assertEqual(excel.read()[:2], b'PK')
            preview = json.load(urllib.request.urlopen(f"{base}/api/excel/preview?id={info['id']}&zone=UTC&vars=co2_ppm"))
            for minpct, spacing in ((0, 'lineal'), (10, 'exponencial'), (0, 'original'), ('', 'original')):  # el handler pasa la escala a heat, terrain y kmz
                heat = json.load(urllib.request.urlopen(f"{base}/api/heat?id={info['id']}&var=co2_ppm&bins=4&minpct={minpct}&spacing={spacing}"))
                self.assertEqual(len(heat['classes']), 4 if minpct == 0 else len(heat['classes']))
                self.assertEqual(urllib.request.urlopen(f"{base}/api/kmz?id={info['id']}&kind=bars&var=co2_ppm&minpct={minpct}&spacing={spacing}").status, 200)
            self.assertEqual(preview['rows'], 4)
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
