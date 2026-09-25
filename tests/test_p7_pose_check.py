"""Frozen P7 pose tolerance and explicit measurement coverage."""

import unittest

from scripts.p7_pose_check import evaluate_pose


REFERENCE = {"heading_rad": 0.11884765359676912,
             "trunk_z_m": 0.1158945287893718,
             "heading_tolerance_rad": 0.02,
             "trunk_z_tolerance_m": 0.01}


class PoseCheckTests(unittest.TestCase):
    def test_frozen_reference_accepts_boundary(self):
        result = evaluate_pose({"heading_rad": REFERENCE["heading_rad"] + .019,
                                "trunk_z": REFERENCE["trunk_z_m"] + .009}, REFERENCE)
        self.assertTrue(result["accepted"])
        self.assertAlmostEqual(result["heading_error_rad"], .019)

    def test_measured_thor_reset_error_is_recorded_and_rejected(self):
        result = evaluate_pose({"heading_rad": 0.07920046,
                                "trunk_z": REFERENCE["trunk_z_m"]}, REFERENCE)
        self.assertFalse(result["accepted"])
        self.assertAlmostEqual(result["heading_error_rad"], -.03964719359676912)
        self.assertEqual(result["heading_tolerance_rad"], .02)


if __name__ == "__main__":
    unittest.main()
