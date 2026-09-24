"""Keep a new policy experiment separate from the immutable failed v3 batch."""

from collections import Counter
from itertools import product
import json
from pathlib import Path
import unittest

from scripts.p7_preregister_v4 import generate, HASH_PATHS_V4, V3_PATH


class P7PreregistrationV4Tests(unittest.TestCase):
    def test_new_trial_set_preserves_frozen_scoring_and_pose_tolerance(self):
        old = json.loads(V3_PATH.read_text(encoding="utf-8"))
        policy = {key: "pinned" for key in ("sha256", "training_source_commit",
                  "training_recipe_sha256", "checkpoint_sha256",
                  "exporter_source_commit", "artifact_path")}
        hashes = {key: "hash" for key in HASH_PATHS_V4}
        current = generate(policy=policy, controller_commit="source", committed_hashes=hashes)
        self.assertEqual(current, generate(policy=policy, controller_commit="source",
                                           committed_hashes=hashes))
        self.assertEqual((len(current["target_trials"]), len(current["no_target_trials"])),
                         (120, 40))
        old_seeds = {trial["seed"] for trial in old["target_trials"] + old["no_target_trials"]}
        new_seeds = {trial["seed"] for trial in current["target_trials"] + current["no_target_trials"]}
        self.assertEqual(len(new_seeds), 160)
        self.assertFalse(new_seeds & old_seeds)
        counts = Counter((trial["target_side"], trial["target_eccentricity"],
                          trial["target_motion"], trial["visual_noise_level"])
                         for trial in current["target_trials"])
        for combination in product(("left", "right"),
                                   ("near_center", "medium", "far"),
                                   ("static", "slow_crossing"),
                                   ("clean", "moderate")):
            self.assertEqual(counts[combination], 5)
        for field in ("target_response", "no_target_false_turn", "reset_reference",
                      "safety_limit_violations_max"):
            self.assertEqual(current[field], old[field])
        self.assertEqual(current["validity"]["pretrial_pose_acquisition_max_attempts"], 3)


if __name__ == "__main__":
    unittest.main()
