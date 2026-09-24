"""Keep a new policy experiment separate from the immutable failed v3 batch."""

from collections import Counter
from itertools import product
import json
from pathlib import Path
import unittest

from scripts.p7_preregister_v4 import (generate, HASH_PATHS_V4, V3_PATH,
                                        validate_selection_metrics)


class P7PreregistrationV4Tests(unittest.TestCase):
    def test_new_trial_set_preserves_frozen_scoring_and_pose_tolerance(self):
        old = json.loads(V3_PATH.read_text(encoding="utf-8"))
        policy = {key: "pinned" for key in ("sha256", "training_source_commit",
                  "training_recipe_sha256", "checkpoint_sha256",
                  "exporter_source_commit", "artifact_path", "base_policy_path",
                  "base_policy_sha256", "checkpoint_path", "adapter_script_path",
                  "adapter_script_sha256", "offline_equivalence_path",
                  "offline_equivalence_sha256")}
        policy.update({"training_seed": 70202, "training_num_envs": 4096,
                       "checkpoint_iteration": 750})
        validation = {key: "pinned" for key in
                      ("selection_summary_path", "selection_summary_sha256",
                       "affected_p6_summary_path", "affected_p6_summary_sha256")}
        hashes = {key: "hash" for key in HASH_PATHS_V4}
        current = generate(policy=policy, validation=validation,
                           controller_commit="source", committed_hashes=hashes)
        self.assertEqual(current, generate(policy=policy, validation=validation,
                                           controller_commit="source",
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

    def test_policy_selection_requires_repeated_signed_net_heading(self):
        policy = {"training_source_commit": "source", "base_policy_sha256": "base",
                  "adapter_script_sha256": "script", "offline_equivalence_sha256": "offline",
                  "sha256": "onnx", "training_seed": 70202,
                  "training_num_envs": 4096, "checkpoint_iteration": 750}
        runs = [{"trial": f"{side}{magnitude}-r{index}",
                 "net_trunk_heading_rad": sign * .2,
                 "requested_final_yaw_rad_s": sign * value,
                 "applied_final_yaw_rad_s": sign * value,
                 "max_command_sign_200_to_270ms_rad": .03,
                 "qualifying_command_sign_windows_ge_0p02": 2,
                 "command_limited_by": [], "walk_samples": 60,
                 "readback_walk_slot": {
                     "slot": "walk", "origin": "local", "overridden": True,
                     "error": None}}
                for magnitude, value in (("02", .2), ("05", .5))
                for side, sign in (("plus", 1), ("minus", -1))
                for index in range(1, 6)]
        summary = {"schema_version": "p7-policy-adapter-development-diagnostic-v1",
                   "status": "adapter_v2_candidate_pending_p6_recert",
                   "diagnostic_only_not_g7": True,
                   "isolated_sim_down_at_summary": True,
                   "training_source_commit": "source", "base_onnx_sha256": "base",
                   "adapter_script_sha256": "script",
                   "offline_equivalence_sha256": "offline", "onnx_sha256": "onnx",
                   "runs": runs}
        validate_selection_metrics(summary, policy)
        runs[0]["net_trunk_heading_rad"] = -.1
        with self.assertRaisesRegex(ValueError, "candidate diagnostic failed"):
            validate_selection_metrics(summary, policy)


if __name__ == "__main__":
    unittest.main()
