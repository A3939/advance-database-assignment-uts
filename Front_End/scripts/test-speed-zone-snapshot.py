"""Targeted classification boundary checks; no raw file writes."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('speed_builder', Path(__file__).with_name('build-speed-zone-snapshot.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SpeedBands(unittest.TestCase):
    def test_whole_published_ranges(self):
        for source, values in [('QLD', ['0 - 50 km/h', '60 km/h', '70 km/h', '80 - 90 km/h', '100 - 110 km/h']),
                               ('NSW', ['40 km/h', '60 km/h', '70 km/h', '90 km/h', '110 km/h']),
                               ('VIC', ['050', '060', '070', '080', '100'])]:
            self.assertEqual([module.band(source, value) for value in values], [b[0] for b in module.BANDS])

    def test_unknown_and_nonmatching_limits_are_not_inferred(self):
        for source, values in [('VIC', ['075', '777', '888', '999', '', '0']), ('NSW', ['Unknown', '', '75 km/h']), ('QLD', ['0 - 60 km/h', 'Unknown'])]:
            for value in values:
                self.assertIsNone(module.band(source, value), (source, value))


if __name__ == '__main__':
    unittest.main()
