"""Coordinate contract tests; reference numbers originate in coordtransform."""
import unittest
from checkin import configured_payload
from core import normalize_location

SNAPSHOT = {'user_agent': 'Synthetic coordinate test'}


class Coordinates(unittest.TestCase):
    def test_reference_wgs84_point_matches_forward_transform(self):
        point = normalize_location({'latitude': 30.757413, 'longitude': 103.930739,
                                    'coordinate_system': 'wgs84'})
        self.assertAlmostEqual(point['gcj02']['latitude'], 30.75470828983461, places=11)
        self.assertAlmostEqual(point['gcj02']['longitude'], 103.93284383329953, places=11)

    def test_saved_map_point_and_submission_are_identical_without_double_conversion(self):
        for lat, lng in [(30.6752, 104.0975), (30.7528, 103.9313)]:
            point = normalize_location({'latitude': lat, 'longitude': lng, 'coordinate_system': 'wgs84'})
            payload = configured_payload(SNAPSHOT, point)
            self.assertEqual(payload['latitude'], point['gcj02']['latitude'])
            self.assertEqual(payload['longitude'], point['gcj02']['longitude'])
            self.assertEqual(payload['coordinateSystemCode'], 'gcj02')

    def test_gcj02_is_not_shifted_again(self):
        point = normalize_location({'latitude': 30.75470828983461, 'longitude': 103.93284383329953,
                                    'coordinate_system': 'gcj02'})
        payload = configured_payload(SNAPSHOT, point)
        self.assertEqual(payload['latitude'], point['latitude'])
        self.assertEqual(payload['longitude'], point['longitude'])
