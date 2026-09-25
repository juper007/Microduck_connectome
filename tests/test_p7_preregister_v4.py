"""Keep a new policy experiment separate from the immutable failed v3 batch."""

from collections import Counter
from itertools import product
import json
from pathlib import Path
import unittest

from scripts.p7_preregister_v4 import (generate, HASH_PATHS_V4, V3_PATH,
                                        validate_development_smoke,
                                        validate_selection_metrics)


class P7PreregistrationV4Tests(unittest.TestCase):
    def test_new_trial_set_preserves_frozen_scoring_and_pose_tolerance(self):
        old = json.loads(V3_PATH.read_text(encoding="utf-8"))
        policy = {key: "pinned" for key in ("sha256", "training_source_commit",
                  "training_recipe_sha256", "checkpoint_sha256",
                  "exporter_source_commit", "artifact_path", "checkpoint_path",
                  "training_resume_manifest_path", "training_resume_manifest_sha256",
                  "diagnostic_summary_path", "diagnostic_summary_sha256",
                  "p7_development_smoke_summary_path",
                  "p7_development_smoke_summary_sha256",
                  "p6_recert_summary_path", "p6_recert_summary_sha256")}
        policy.update({"training_seed": 70202, "training_num_envs": 4096,
                       "checkpoint_iteration": 1250})
        validation = {key: "pinned" for key in
                      ("selection_summary_path", "selection_summary_sha256",
                       "development_smoke_summary_path",
                       "development_smoke_summary_sha256",
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
        policy = {"sha256": "onnx", "checkpoint_sha256": "checkpoint",
                  "training_seed": 70202, "training_num_envs": 4096,
                  "checkpoint_iteration": 1250}
        runs = [{"trial": f"{side}05-r{index}",
                 "net_trunk_heading_rad": sign * .2,
                 "external_yaw_rad_s": sign * .5,
                 "first_qualifying_200ms": {"start_s": .3, "duration_s": .2,
                                             "heading_delta_rad": sign * .03},
                 "loaded_policy_sha256": "onnx", "fault_or_fall": False}
                for side, sign in (("plus", 1), ("minus", -1))
                for index in range(1, 6)]
        summary = {"schema_version": "p7-02-model1250-policy-selection-v1",
                   "status": "preliminary_candidate_pending_full_p6_recert",
                   "diagnostic_only_not_g7": True,
                   "checkpoint_sha256": "checkpoint", "onnx_sha256": "onnx",
                   "runs": runs}
        validate_selection_metrics(summary, policy)
        runs[0]["first_qualifying_200ms"]["heading_delta_rad"] = -.03
        with self.assertRaisesRegex(ValueError, "candidate diagnostic failed"):
            validate_selection_metrics(summary, policy)

    def test_full_chain_smoke_checks_all_target_classes_and_first_response(self):
        classes = [("left", "static", True), ("right", "static", True),
                   ("left", "slow_crossing", True),
                   ("right", "slow_crossing", True), ("none", "none", False)]
        runs = [{"trial_id": str(index), "target_side": side,
                 "target_motion": motion, "target_present": present,
                 "outcome": "correct" if present else "no_target",
                 "trial_exit": 0, "invalid_reasons": [],
                 "safety_limit_violations": 0,
                 "response": {"heading_delta_rad": .03 if side == "left" else -.03}
                 if present else None}
                for index, (side, motion, present) in enumerate(classes)]
        summary = {"status": "completed", "runs": runs}
        validate_development_smoke(summary)
        runs[0]["response"]["heading_delta_rad"] = -.03
        with self.assertRaisesRegex(ValueError, "first response failed"):
            validate_development_smoke(summary)


if __name__ == "__main__":
    unittest.main()
