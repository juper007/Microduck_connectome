import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.p6_sim_preflight import probe_environment


MICRO_SHA="344925c9f8fa031f85428a305b1e8ec2eaae29c1"
RL_SHA="cb70b792312d559a4da09064d92009079671815f"


class Result:
    def __init__(self, returncode=0, stdout=""):
        self.returncode=returncode
        self.stdout=stdout
        self.stderr=""


class P6SimPreflightTests(unittest.TestCase):
    def make_fixture(self, root):
        root=Path(root)
        micro=root/"microduck"
        rl=root/"microduck_rl"
        (micro/"scripts").mkdir(parents=True)
        (micro/"scripts"/"duck-sim").write_text("#!/bin/sh\n",encoding="utf-8")
        (rl/".venv"/"bin").mkdir(parents=True)
        (rl/".venv"/"bin"/"python").write_text("",encoding="utf-8")
        versions=root/"versions.json"
        versions.write_text(json.dumps({
            "upstream":{
                "microduck":{"commit":MICRO_SHA},
                "microduck_rl":{"commit":RL_SHA},
            }
        }),encoding="utf-8")
        return micro,rl,versions

    def test_ready_only_when_exact_pins_and_prerequisites_exist(self):
        with tempfile.TemporaryDirectory() as td:
            micro,rl,versions=self.make_fixture(td)

            def fake_run(args,*,cwd=None):
                if args[:3]==["git","rev-parse","HEAD"]:
                    return Result(stdout=(MICRO_SHA if Path(cwd)==micro else RL_SHA)+"\n")
                return Result(returncode=0)

            with patch("scripts.p6_sim_preflight._run",side_effect=fake_run), \
                 patch("scripts.p6_sim_preflight.shutil.which",return_value="/tool"):
                result=probe_environment(microduck=micro,microduck_rl=rl,versions=versions)
            self.assertTrue(result["ready"])
            self.assertTrue(all(result["checks"].values()))

    def test_commit_mismatch_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as td:
            micro,rl,versions=self.make_fixture(td)

            def fake_run(args,*,cwd=None):
                if args[:3]==["git","rev-parse","HEAD"]:
                    return Result(stdout=("0"*40 if Path(cwd)==micro else RL_SHA)+"\n")
                return Result(returncode=0)

            with patch("scripts.p6_sim_preflight._run",side_effect=fake_run), \
                 patch("scripts.p6_sim_preflight.shutil.which",return_value="/tool"):
                result=probe_environment(microduck=micro,microduck_rl=rl,versions=versions)
            self.assertFalse(result["ready"])
            self.assertFalse(result["checks"]["microduck_commit_matches"])

    def test_missing_runtime_tools_or_checkouts_block_readiness(self):
        with tempfile.TemporaryDirectory() as td:
            versions=Path(td)/"versions.json"
            versions.write_text(json.dumps({
                "upstream":{
                    "microduck":{"commit":MICRO_SHA},
                    "microduck_rl":{"commit":RL_SHA},
                }
            }),encoding="utf-8")
            with patch("scripts.p6_sim_preflight.shutil.which",return_value=None):
                result=probe_environment(
                    microduck=Path(td)/"missing-micro",
                    microduck_rl=Path(td)/"missing-rl",
                    versions=versions,
                )
            self.assertFalse(result["ready"])
            self.assertFalse(result["checks"]["cargo_present"])
            self.assertFalse(result["checks"]["rl_venv_python_present"])


if __name__=="__main__":
    unittest.main()
