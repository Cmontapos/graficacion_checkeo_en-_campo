import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import zipfile

import mapa_calor

from graficar import load_csv, numeric, numeric_columns, normalize_columns, find_time_column, gps_valid, time_axis, gps_segments, make_map, make_viewer, make_excel

# Synthetic data: 7 rows 1 s apart across local midnight (UTC-6), no GPS on row 3.
SAMPLE = '\n'.join(['fecha_hora_utc,co2_ppm,temperatura_c,latitud,longitud,session'] + [
    f'2026-09-28T05:59:{57 + k:02d}.000Z,{420 + 30 * k},24.{k},' + ('' if k == 3 else f'9.93{50 + k},-84.0{900 - k}') + ',demo' if k < 3 else
    f'2026-09-28T06:00:{k - 3:02d}.000Z,{420 + 30 * k},24.{k},' + ('' if k == 3 else f'9.93{50 + k},-84.0{900 - k}') + ',demo' for k in range(7)]) + '\n'


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'sample.csv'
        self.path.write_text(SAMPLE)
        self.frame = load_csv(self.path)

    def test_timezone_midnight_and_elapsed(self):
        x, _, _ = time_axis(self.frame, 'hora', 'fecha_hora_utc', 'America/Costa_Rica')
        self.assertEqual((x.iloc[0].day, x.iloc[0].hour), (27, 23))
        self.assertEqual((x.iloc[-1].day, x.iloc[-1].hour), (28, 0))
        elapsed, _, _ = time_axis(self.frame, 'transcurrido', 'fecha_hora_utc')
        self.assertEqual(elapsed.tolist(), list(range(7)))

    def test_unix_seconds_and_milliseconds(self):
        for unit, multiplier in [('s', 1), ('ms', 1000), ('us', 1000000), ('ns', 1000000000)]:
            frame = pd.DataFrame({'t': [1700000000 * multiplier, 1700000001 * multiplier]})
            x, _, _ = time_axis(frame, 'timestamp', 't')
            self.assertEqual(x.tolist(), [1700000000, 1700000001])

    def test_gps_gaps_and_sessions(self):
        segments, missing = gps_segments(self.frame)
        self.assertEqual([len(s) for s in segments], [3, 3])
        self.assertEqual(missing, 1)
        self.frame.loc[5:, 'session'] = 'another'
        self.assertEqual([len(s) for s in gps_segments(self.frame)[0]], [3, 1, 2])
        self.frame['latitud'] = 100
        with self.assertRaises(ValueError):
            gps_segments(self.frame)

    def test_delimiter_decimal_and_new_samples(self):
        p = Path(self.directory.name) / 'data.csv'
        p.write_text('co2_ppm;sen66_new_data;vacio\n420,5;1;\n420,5;0;\n')
        frame = load_csv(p, only_new=True)
        self.assertEqual(len(frame), 1)
        self.assertIn('co2_ppm', numeric_columns(frame))
        self.assertNotIn('vacio', numeric_columns(frame))

    def test_campbell_column_names(self):
        p = Path(self.directory.name) / 'flight.csv'
        p.write_text('TIMESTAMP;Sensor_2_ppm_Avg;Zero_ad;Latitude;Longitude;Altitude\n'
                     '2026-09-16 00:01:19;1,402;-2147483648;38,41645;14,95981;25\n2026-09-16 00:01:18;1,412;-2147483648;38,41644;14,95982;25,1\n')
        frame = load_csv(p, time_column='TIMESTAMP')
        self.assertEqual(list(frame.columns), ['timestamp', 'Sensor_2_ppm_Avg', 'Zero_ad', 'latitud', 'longitud', 'altitud_m'])
        self.assertEqual(find_time_column(frame, 'TIMESTAMP'), 'timestamp')
        self.assertEqual(frame['Sensor_2_ppm_Avg'].tolist(), ['1,412', '1,402'])  # ordenado por tiempo
        self.assertNotIn('Zero_ad', numeric_columns(frame))
        self.assertEqual([len(s) for s in gps_segments(frame)[0]], [2])
        elapsed, _, _ = time_axis(frame, 'transcurrido', 'timestamp')
        self.assertEqual(elapsed.tolist(), [0, 1])
        self.assertIn('"routeLat":[38.41644', make_viewer(frame, Path(self.directory.name) / 'f.html', time_column='timestamp').read_text())

    def test_alternative_column_names(self):
        frame = normalize_columns(pd.DataFrame(columns=['Fecha Hora', 'GPS_Lat', 'Longitud', 'Elevación', 'CO2 (ppm)', 'Temperature (°C)', 'RH (%)', 'latitud_dron']))
        self.assertEqual(list(frame.columns), ['timestamp', 'latitud', 'longitud', 'altitud_m', 'co2_ppm', 'temperatura_c', 'humedad_pct', 'latitud_dron'])
        both = normalize_columns(pd.DataFrame(columns=['latitud', 'Latitude']))
        self.assertEqual(list(both.columns), ['latitud', 'Latitude'])  # no pisa una columna existente
        lat, lon = pd.Series([0.0, 9.9]), pd.Series([0.0, -84.0])
        self.assertEqual(gps_valid(lat, lon).tolist(), [False, True])  # 0,0 = GPS sin señal

    def test_shuffled_rows_are_sorted_by_time(self):
        lines = SAMPLE.splitlines()
        p = Path(self.directory.name) / 'shuffled.csv'
        p.write_text('\n'.join([lines[0]] + lines[1:][::-1]) + '\n')
        frame = load_csv(p, time_column='fecha_hora_utc')
        self.assertEqual(frame['co2_ppm'].tolist(), self.frame['co2_ppm'].tolist())
        self.assertEqual([len(s) for s in gps_segments(frame)[0]], [3, 3])

    def test_map_and_interactive_viewer(self):
        text = make_map(self.frame, Path(self.directory.name) / 'map.html').read_text()
        self.assertIn('Latitud:', text)
        self.assertIn('World_Imagery', text)
        page = make_viewer(self.frame, Path(self.directory.name) / 'viewer.html', ['co2_ppm']).read_text()
        self.assertIn('"co2_ppm"', page)
        self.assertIn('routeLat', page)
        self.assertIn('grid-template-columns:repeat(3,minmax(0,1fr))', page)
        self.assertIn('overflow-y:auto', page)

    def test_excel_only_contains_the_given_rows(self):
        path = make_excel(self.frame.iloc[2:5], Path(self.directory.name) / 'tramo.xlsx', ['co2_ppm', 'temperatura_c'])
        with zipfile.ZipFile(path) as book:
            names = book.namelist()
            sheet = book.read('xl/worksheets/sheet2.xml').decode()
            workbook = book.read('xl/workbook.xml').decode()
        for name in ('Resumen', 'Datos', 'Gráficas', 'Ruta'):
            self.assertIn(f'name="{name}"', workbook)
        self.assertEqual(sum(n.startswith('xl/charts/chart') for n in names), 3)  # 2 variables + ruta
        self.assertIn('<dimension ref="A1:F4"/>', sheet)  # encabezado + 3 filas del tramo

    def test_excel_opens_like_the_csv(self):
        path = Path(self.directory.name) / 'sample.xlsx'
        pd.read_csv(self.path).to_excel(path, sheet_name='Hoja1', index=False)
        frame = load_csv(path)
        self.assertEqual(list(frame.columns), list(self.frame.columns))
        self.assertEqual(numeric(frame['co2_ppm']).tolist(), numeric(self.frame['co2_ppm']).tolist())
        x, _, _ = time_axis(frame, 'hora', 'fecha_hora_utc', 'America/Costa_Rica')
        self.assertEqual((x.iloc[0].day, x.iloc[0].hour), (27, 23))

    def test_excel_exported_by_gaslab_goes_back_to_utc(self):
        path = make_excel(self.frame, Path(self.directory.name) / 'exportado.xlsx', ['co2_ppm'], zone='America/Costa_Rica')
        frame = load_csv(path)  # hoja Datos, con 'Fecha y hora (America/Costa_Rica)' en hora local
        self.assertNotIn('Transcurrido (s)', frame)
        self.assertEqual(time_axis(frame, 'fecha', 'fecha_hora_utc')[2].tolist(), time_axis(self.frame, 'fecha', 'fecha_hora_utc')[2].tolist())
        self.assertEqual(numeric(frame['co2_ppm']).tolist(), numeric(self.frame['co2_ppm']).tolist())

    def test_excel_sheet_default_and_choice(self):
        path = Path(self.directory.name) / 'hojas.xlsx'
        with pd.ExcelWriter(path) as book:
            pd.DataFrame({'nota': ['vacía']}).head(0).to_excel(book, sheet_name='Vacía', index=False)
            pd.read_csv(self.path).to_excel(book, sheet_name='Grande', index=False)
            pd.DataFrame({'fecha_hora_utc': ['2026-10-28T05:00:00Z'], 'so2_ppm': [0.4]}).to_excel(book, sheet_name='Aparte', index=False)
        frame = load_csv(path)
        self.assertEqual((frame.attrs['sheet'], frame.attrs['sheets']), ('Grande', ['Grande', 'Aparte']))
        other = load_csv(path, sheet='Aparte')
        self.assertEqual((other.attrs['sheet'], numeric(other['so2_ppm']).tolist()), ('Aparte', [0.4]))
        with self.assertRaisesRegex(ValueError, 'Vacía'):
            load_csv(path, sheet='Vacía')

    def test_old_xls_gives_a_clear_error(self):
        path = Path(self.directory.name) / 'viejo.xls'
        path.write_bytes(b'\xd0\xcf\x11\xe0')
        with self.assertRaisesRegex(ValueError, 'guárdalo como .xlsx'):
            load_csv(path)


class HeatMapTests(unittest.TestCase):
    """mapa_calor.py con datos sinteticos (coordenadas en metros, celdas de 10)."""

    def test_cell_statistics(self):
        x, y = np.array([1.0, 2.0, 3.0, 15.0]), np.array([1.0, 2.0, 3.0, 1.0])
        values = np.array([10.0, 20.0, 60.0, 5.0])
        mean, counts, x0, y0 = mapa_calor.grid(x, y, values, 10, 'media')
        self.assertEqual((x0, y0, mean.shape), (0, 0, (1, 2)))
        self.assertEqual(counts.tolist(), [[3, 1]])
        self.assertEqual(mean.tolist(), [[30, 5]])
        self.assertEqual(mapa_calor.grid(x, y, values, 10, 'maximo')[0].tolist(), [[60, 5]])

    def test_smoothing_stays_near_the_route(self):
        x, y = np.array([500.0]), np.array([500.0])
        smooth, _, x0, _ = mapa_calor.grid(x, y, np.array([7.0]), 10, 'media', smooth=1)
        self.assertTrue(np.allclose(smooth[np.isfinite(smooth)], 7))  # el promedio ponderado no cambia un valor unico
        self.assertLessEqual(np.isfinite(smooth).sum(), 25)  # solo ~2 celdas alrededor

    def test_lag_moves_values_back_along_the_route(self):
        t = np.array([0.0, 1, 2, 3, 100, 101])
        x = np.array([0.0, 10, 20, 30, 500, 510])
        lx, _ = mapa_calor.lag_positions(t, x, np.zeros(6), 1.5)
        self.assertEqual(lx[[2, 3]].tolist(), [5, 15])  # 2 - 1,5 = 0,5 s -> a mitad entre 0 y 10 m
        self.assertTrue(np.isnan(lx[[0, 1, 4, 5]]).all())  # antes del inicio o dentro de la pausa de 97 s

    def test_export_writes_geotiff_points_and_qgis(self):
        with tempfile.TemporaryDirectory() as folder:
            lat, lon = np.array([9.9351, 9.9352, 9.9353]), np.array([-84.09, -84.0901, -84.0902])
            mapa_calor.export(Path(folder) / 'co2.tif', lat, lon, np.array([420.0, 450.0, 9000.0]), 'co2_ppm', 5,
                              value_range=(None, 5000))
            data, x0, y_top, dx, dy, epsg = mapa_calor.read_geotiff(Path(folder) / 'co2.tif')
            self.assertEqual(epsg, 3857)
            self.assertAlmostEqual(np.nanmax(data), 450, places=3)  # 9000 queda fuera del rango valido
            points = json.loads((Path(folder) / 'co2_puntos.geojson').read_text())
            self.assertEqual(len(points['features']), 2)
            with zipfile.ZipFile(Path(folder) / 'co2.qgz') as project:
                xml = project.read('co2.qgs').decode()
            self.assertIn('<datasource>./co2.tif</datasource>', xml)
            self.assertIn('EPSG:3857', xml)
            self.assertIn('<datasource>./co2_puntos.geojson</datasource>', xml)
            self.assertIn('type="graduatedSymbol" attr="co2_ppm"', xml)
            values = [f['properties']['co2_ppm'] for f in points['features']]
            self.assertEqual(values, sorted(values))  # los altos al final: se dibujan encima

    def test_points_mode_turns_cells_off_in_qgis(self):
        with tempfile.TemporaryDirectory() as folder:
            lat, lon = np.array([9.9351, 9.9352]), np.array([-84.09, -84.0901])
            mapa_calor.export(Path(folder) / 'c.tif', lat, lon, np.array([1.0, 2.0]), 'v', 1, mode='puntos')
            with zipfile.ZipFile(Path(folder) / 'c.qgz') as project:
                xml = project.read('c.qgs').decode()
            self.assertIn('providerKey="ogr" checked="Qt::Checked"', xml)
            self.assertIn('providerKey="gdal" checked="Qt::Unchecked"', xml)


if __name__ == '__main__':
    unittest.main()
