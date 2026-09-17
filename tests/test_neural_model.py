import json
import math
from pathlib import Path
import tempfile
import unittest

from microduck_connectome.neural_model import (
    MODEL_SPEC_VERSION,
    SCHEMA_VERSION,
    NeuralModelConfigError,
    load_model_config,
    model_config_sha256,
    validate_model_config,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "neural_model_v1.json"


class NeuralModelConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def test_committed_defaults_match_frozen_spec(self):
        config = load_model_config(CONFIG_PATH)
        self.assertEqual(config["schema_version"], SCHEMA_VERSION)
        self.assertEqual(config["model_spec_version"], MODEL_SPEC_VERSION)
        self.assertEqual(config["timestep_ms"], 20)
        self.assertEqual(config["alpha"], 0.9)
        self.assertEqual(config["threshold"], 1.0)
        self.assertEqual(config["reset_value"], 0.0)
        self.assertEqual(config["recurrent_gain"], 1.0)
        self.assertTrue(config["deterministic"])
        self.assertFalse(config["plasticity"])

    def test_hash_is_order_independent(self):
        reversed_config = dict(reversed(list(self.config.items())))
        self.assertEqual(model_config_sha256(self.config), model_config_sha256(reversed_config))

    def test_hash_changes_when_valid_parameter_changes(self):
        changed = dict(self.config, alpha=0.8)
        self.assertNotEqual(model_config_sha256(self.config), model_config_sha256(changed))

    def test_rejects_missing_or_extra_fields(self):
        missing = dict(self.config)
        missing.pop("alpha")
        with self.assertRaises(NeuralModelConfigError):
            validate_model_config(missing)
        with self.assertRaises(NeuralModelConfigError):
            validate_model_config(dict(self.config, surprise=True))

    def test_rejects_invalid_numeric_types_and_nonfinite_values(self):
        for key, value in (("timestep_ms", True), ("alpha", True), ("alpha", math.nan),
                           ("threshold", math.inf), ("reset_value", -math.inf)):
            with self.subTest(key=key, value=value):
                with self.assertRaises(NeuralModelConfigError):
                    validate_model_config(dict(self.config, **{key: value}))

    def test_rejects_invalid_ranges(self):
        for key, value in (("timestep_ms", 0), ("alpha", -0.01), ("alpha", 1.01),
                           ("recurrent_gain", -0.01)):
            with self.subTest(key=key, value=value):
                with self.assertRaises(NeuralModelConfigError):
                    validate_model_config(dict(self.config, **{key: value}))

    def test_rejects_mvp_invariant_changes(self):
        changes = {
            "deterministic": False,
            "plasticity": True,
            "recurrent_weight_mode": "signed",
            "normalization_scope": "runtime_subgraph",
            "update_semantics": "asynchronous",
            "recurrent_spike_source": "same_step",
            "initial_state": "random",
            "state_dtype": "float64",
        }
        for key, value in changes.items():
            with self.subTest(key=key):
                with self.assertRaises(NeuralModelConfigError):
                    validate_model_config(dict(self.config, **{key: value}))

    def test_numeric_values_are_canonicalized_to_float(self):
        config = dict(self.config, threshold=1, reset_value=0, recurrent_gain=1)
        validated = validate_model_config(config)
        self.assertIs(type(validated["threshold"]), float)
        self.assertIs(type(validated["reset_value"]), float)
        self.assertIs(type(validated["recurrent_gain"]), float)

    def test_load_rejects_malformed_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(NeuralModelConfigError):
                load_model_config(path)


if __name__ == "__main__":
    unittest.main()
