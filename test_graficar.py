import tempfile
import unittest
from pathlib import Path

import pandas as pd
from graficar import load_csv, numeric_columns, time_axis, gps_segments, make_map, make_viewer

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
        x, _, _ = time_axis(self.frame, 'hora', 'fecha_hora_utc')
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


if __name__ == '__main__':
    unittest.main()
