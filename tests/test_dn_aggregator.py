import copy
import json
from pathlib import Path
import unittest

from microduck_connectome.dn_aggregator import (
    DNAggregatorError,
    DNActivityAggregator,
    dn_readout_config_sha256,
    load_dn_readout_config,
    validate_dn_readout_config,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "dn_readout_v1.json"
DNA02_PATH = ROOT / "docs" / "evidence" / "p2-02" / "dna02-v1.json"
DNP01_PATH = ROOT / "docs" / "evidence" / "p2-03" / "dnp01-report.json"


def body_ids(config):
    return tuple(sorted(
        body_id
        for spec in config["populations"].values()
        for body_id in spec["body_ids"]
    ))


def spikes(ids, active):
    active = set(active)
    return tuple(body_id in active for body_id in ids)


class DNAggregatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_dn_readout_config(CONFIG_PATH)
        cls.ids = body_ids(cls.config)

    def new(self):
        return DNActivityAggregator(self.ids, self.config)

    def test_population_ids_match_phase2_evidence_exactly(self):
        dna02 = json.loads(DNA02_PATH.read_text(encoding="utf-8"))
        dnp01 = json.loads(DNP01_PATH.read_text(encoding="utf-8"))
        expected_dna = {row["side"]: row["body_id"] for row in dna02["readouts"]}
        expected_escape = sorted(row["bodyId"] for row in dnp01["readouts"])
        self.assertEqual(self.config["populations"]["steering_left"]["body_ids"], [expected_dna["left"]])
        self.assertEqual(self.config["populations"]["steering_right"]["body_ids"], [expected_dna["right"]])
        self.assertEqual(self.config["populations"]["escape"]["body_ids"], expected_escape)
        self.assertEqual(expected_escape, [10001, 10010])

    def test_left_right_balanced_and_escape_activity(self):
        agg = self.new()
        left = self.config["populations"]["steering_left"]["body_ids"][0]
        right = self.config["populations"]["steering_right"]["body_ids"][0]
        escape = self.config["populations"]["escape"]["body_ids"]
        result = None
        for i in range(5):
            result = agg.update(
                spikes(self.ids, [left, right, *escape]),
                timestamp_ns=(i + 1) * 20_000_000,
                sequence=i,
            )
        self.assertEqual(result["steering_left"], 1.0)
        self.assertEqual(result["steering_right"], 1.0)
        self.assertEqual(result["escape"], 1.0)

    def test_left_only_and_right_only_are_separate(self):
        left = self.config["populations"]["steering_left"]["body_ids"][0]
        right = self.config["populations"]["steering_right"]["body_ids"][0]
        a = self.new().update(spikes(self.ids, [left]), timestamp_ns=1, sequence=0)
        b = self.new().update(spikes(self.ids, [right]), timestamp_ns=1, sequence=0)
        self.assertEqual((a["steering_left"], a["steering_right"]), (0.2, 0.0))
        self.assertEqual((b["steering_left"], b["steering_right"]), (0.0, 0.2))

    def test_runtime_unhealthy_resets_window_and_emits_zero(self):
        left = self.config["populations"]["steering_left"]["body_ids"][0]
        agg = self.new()
        first = agg.update(spikes(self.ids, [left]), timestamp_ns=1, sequence=0)
        self.assertGreater(first["steering_left"], 0.0)
        unhealthy = agg.update((), timestamp_ns=2, sequence=1, runtime_healthy=False)
        self.assertEqual((unhealthy["steering_left"], unhealthy["steering_right"], unhealthy["escape"]), (0.0, 0.0, 0.0))
        self.assertFalse(unhealthy["runtime_healthy"])
        recovered = agg.update(spikes(self.ids, []), timestamp_ns=3, sequence=2)
        self.assertEqual(recovered["steering_left"], 0.0)

    def test_malformed_spikes_fail_without_advancing_metadata(self):
        agg = self.new()
        with self.assertRaises(DNAggregatorError):
            agg.update([False] * (len(self.ids) - 1) + [1], timestamp_ns=1, sequence=0)
        result = agg.update(spikes(self.ids, []), timestamp_ns=1, sequence=0)
        self.assertEqual(result["sequence"], 0)

    def test_timestamp_and_sequence_must_increase(self):
        agg = self.new()
        agg.update(spikes(self.ids, []), timestamp_ns=10, sequence=5)
        for timestamp, sequence in ((10, 6), (11, 5), (9, 6)):
            with self.subTest(timestamp=timestamp, sequence=sequence):
                with self.assertRaises(DNAggregatorError):
                    agg.update(spikes(self.ids, []), timestamp_ns=timestamp, sequence=sequence)

    def test_reset_clears_window_and_metadata(self):
        left = self.config["populations"]["steering_left"]["body_ids"][0]
        agg = self.new()
        agg.update(spikes(self.ids, [left]), timestamp_ns=10, sequence=5)
        agg.reset()
        result = agg.update(spikes(self.ids, []), timestamp_ns=1, sequence=0)
        self.assertEqual(result["steering_left"], 0.0)

    def test_invalid_population_config_is_rejected(self):
        for mutate in ("empty", "unknown", "wrong_type", "overlap"):
            bad = copy.deepcopy(self.config)
            if mutate == "empty":
                bad["populations"]["escape"]["body_ids"] = []
            elif mutate == "unknown":
                bad["populations"]["escape"]["body_ids"] = [999999999]
            elif mutate == "wrong_type":
                bad["populations"]["escape"]["source_type"] = "Invented"
            else:
                bad["populations"]["escape"]["body_ids"] = bad["populations"]["steering_right"]["body_ids"]
            with self.subTest(mutate=mutate):
                if mutate == "unknown":
                    # Range-valid IDs are rejected when the runtime does not contain them.
                    with self.assertRaises(DNAggregatorError):
                        DNActivityAggregator(self.ids, bad)
                else:
                    with self.assertRaises(DNAggregatorError):
                        validate_dn_readout_config(bad)

    def test_config_hash_and_replay_are_deterministic(self):
        original = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        reordered = dict(reversed(list(original.items())))
        self.assertEqual(dn_readout_config_sha256(original), dn_readout_config_sha256(reordered))
        trace = [
            spikes(self.ids, []),
            spikes(self.ids, [523769]),
            spikes(self.ids, [10360, 10001, 10010]),
        ]
        def run():
            agg = self.new()
            return [agg.update(sample, timestamp_ns=i + 1, sequence=i) for i, sample in enumerate(trace)]
        self.assertEqual(run(), run())


if __name__ == "__main__":
    unittest.main()
