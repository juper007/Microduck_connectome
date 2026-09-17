import math
import unittest

from microduck_connectome.stimulus import StimulusConfigError, StimulusInputError, StimulusInjector


class StimulusTests(unittest.TestCase):
    def setUp(self):
        self.injector = StimulusInjector(
            (1, 2, 3, 4),
            {
                "left": {"body_ids": [1, 2], "side": "L", "max_amplitude": 0.8},
                "right": {"body_ids": [3], "side": "R", "max_amplitude": 1.0},
                "mid": {"body_ids": [4], "side": "M", "max_amplitude": 0.5},
            },
        )

    def test_maps_and_caps(self):
        self.assertEqual(
            self.injector.build_external({"left": 1.0, "right": 0.25}),
            {1: 0.8, 2: 0.8, 3: 0.25},
        )

    def test_stale_or_invalid_observation_injects_zero(self):
        self.assertEqual(self.injector.build_external({"left": 0.7}, stale=True), {})
        self.assertEqual(self.injector.build_external({"left": 0.7}, valid=False), {})

    def test_zero_amplitude_is_omitted(self):
        self.assertEqual(self.injector.build_external({"left": 0.0}), {})

    def test_rejects_bad_amplitude(self):
        for value in (-0.1, 1.1, math.nan, True):
            with self.subTest(value=value):
                with self.assertRaises(StimulusInputError):
                    self.injector.build_external({"left": value})

    def test_rejects_unknown_population(self):
        with self.assertRaises(StimulusInputError):
            self.injector.build_external({"unknown": 0.2})

    def test_rejects_nonexplicit_side(self):
        with self.assertRaises(StimulusConfigError):
            StimulusInjector((1,), {"p": {"body_ids": [1], "side": "left", "max_amplitude": 1.0}})

    def test_rejects_overlapping_populations(self):
        with self.assertRaises(StimulusConfigError):
            StimulusInjector(
                (1, 2),
                {
                    "a": {"body_ids": [1], "side": "L", "max_amplitude": 1.0},
                    "b": {"body_ids": [1, 2], "side": "R", "max_amplitude": 1.0},
                },
            )

    def test_rejects_unknown_body_id(self):
        with self.assertRaises(StimulusConfigError):
            StimulusInjector((1,), {"p": {"body_ids": [2], "side": "L", "max_amplitude": 1.0}})

    def test_returned_mapping_is_detached(self):
        external = self.injector.build_external({"left": 0.2})
        external[1] = 9.0
        self.assertEqual(self.injector.build_external({"left": 0.2})[1], 0.2)


if __name__ == "__main__":
    unittest.main()
