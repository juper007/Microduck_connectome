import unittest

from microduck_connectome.readout import PopulationReadout, PopulationReadoutError


class StubGraph:
    body_ids = (1, 2, 3, 4)

    def select_type(self, cell_type):
        return {"A": (1, 2), "B": (3,)}.get(cell_type, ())


class PopulationReadoutTests(unittest.TestCase):
    def test_window_aggregation_and_rollover(self):
        readout = PopulationReadout((1, 2, 3), {"pair": [1, 2]}, timestep_ms=20, window_ms=60)
        self.assertEqual(readout.update((True, False, False))["pair"], 0.5)
        self.assertEqual(readout.update((True, True, False))["pair"], 1.5)
        self.assertEqual(readout.update((False, True, False))["pair"], 2.0)
        self.assertEqual(readout.update((False, False, False))["pair"], 1.5)

    def test_empty_history_is_zero(self):
        self.assertEqual(PopulationReadout((1,), {"p": [1]}).values()["p"], 0.0)

    def test_reset_clears_history(self):
        readout = PopulationReadout((1,), {"p": [1]})
        readout.update((True,))
        readout.reset()
        self.assertEqual(readout.samples, 0)
        self.assertEqual(readout.values()["p"], 0.0)

    def test_exact_type_constructor(self):
        readout = PopulationReadout.from_graph_types(StubGraph(), ["A", "B"])
        self.assertEqual(readout.population_specs(), {"A": [1, 2], "B": [3]})

    def test_unknown_or_duplicate_type_is_rejected(self):
        with self.assertRaises(PopulationReadoutError):
            PopulationReadout.from_graph_types(StubGraph(), ["X"])
        with self.assertRaises(PopulationReadoutError):
            PopulationReadout.from_graph_types(StubGraph(), ["A", "A"])

    def test_misaligned_or_nonbool_spikes_are_rejected(self):
        readout = PopulationReadout((1, 2), {"p": [1]})
        for spikes in ((True,), (1, False), "xx"):
            with self.subTest(spikes=spikes):
                with self.assertRaises(PopulationReadoutError):
                    readout.update(spikes)

    def test_window_must_align_to_timestep(self):
        with self.assertRaises(PopulationReadoutError):
            PopulationReadout((1,), {"p": [1]}, timestep_ms=20, window_ms=25)

    def test_unknown_population_member_is_rejected(self):
        with self.assertRaises(PopulationReadoutError):
            PopulationReadout((1,), {"p": [2]})

    def test_invalid_body_ids_are_rejected(self):
        for body_ids, populations in ((("1",), {"p": ["1"]}), ((True,), {"p": [True]}), ((0,), {"p": [0]})):
            with self.subTest(body_ids=body_ids):
                with self.assertRaises(PopulationReadoutError):
                    PopulationReadout(body_ids, populations)

    def test_population_specs_are_detached(self):
        readout = PopulationReadout((1, 2), {"p": [1, 2]})
        specs = readout.population_specs()
        specs["p"].clear()
        self.assertEqual(readout.population_specs()["p"], [1, 2])


if __name__ == "__main__":
    unittest.main()
