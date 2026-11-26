"""模型校验与 CLI 端到端测试。"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

from labelreplay.errors import ValidationError
from labelreplay.model import parse_case

from _helper import load_case, CASE02, ROOT

LR = os.path.join(ROOT, "lr.py")


class ValidationTests(unittest.TestCase):
    def setUp(self):
        with open(CASE02, "rb") as fh:
            self.raw = json.loads(fh.read().decode("utf-8"))

    def test_domain_size_must_be_2_to_4(self):
        bad = copy.deepcopy(self.raw)
        bad["sources"][0]["versions"][0]["symbols"] = [["only"]]
        with self.assertRaises(ValidationError):
            parse_case(bad)

    def test_unknown_label_in_declass_rejected(self):
        bad = copy.deepcopy(self.raw)
        bad["nodes"][1]["declass"] = ["L_GHOST"]
        with self.assertRaises(ValidationError):
            parse_case(bad)

    def test_cycle_rejected(self):
        bad = copy.deepcopy(self.raw)
        # 制造真实环：n3 原本被 n5 无关，改为 n5->n3 且 n3->n5
        for node in bad["nodes"]:
            if node["id"] == "n5":
                node["data_inputs"] = ["n3@v1"]
            if node["id"] == "n3":
                node["data_inputs"] = ["nA@v1", "n5@v1"]
        with self.assertRaises(ValidationError):
            parse_case(bad)

    def test_dangling_ref_rejected(self):
        bad = copy.deepcopy(self.raw)
        bad["nodes"][0]["data_inputs"] = ["GHOST@v1"]
        with self.assertRaises(ValidationError):
            parse_case(bad)

    def test_label_kind_must_be_consistent(self):
        bad = copy.deepcopy(self.raw)
        bad["sources"][1]["label_kind"] = "control"  # 与 D1 的 data 冲突
        with self.assertRaises(ValidationError):
            parse_case(bad)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, "-I", LR, *args],
            capture_output=True, env=env, cwd=ROOT,
        )
        return proc

    def test_enumerate_cli(self):
        proc = self.run_cli("--case", CASE02, "enumerate")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
        data = json.loads(proc.stdout.decode("utf-8"))
        self.assertEqual(data["feasible_count"], 12)
        self.assertEqual(data["solver_cross_check"], "backtrack == brute_force")

    def test_prove_and_replay_cli_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = os.path.join(tmp, "prove.json")
            p1 = self.run_cli(
                "--case", CASE02, "--out", artifact,
                "prove", "--group", "G_AUDIT", "--label", "L_REC",
            )
            self.assertEqual(p1.returncode, 0, p1.stderr.decode("utf-8"))
            p2 = self.run_cli(
                "--case", CASE02, "replay", "--artifact", artifact,
            )
            self.assertEqual(p2.returncode, 0)
            data = json.loads(p2.stdout.decode("utf-8"))
            self.assertEqual(data["verdict"], "replay_ok")

    def test_replay_tampered_returns_exit_code_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = os.path.join(tmp, "prove.json")
            self.run_cli(
                "--case", CASE02, "--out", artifact,
                "prove", "--group", "G_AUDIT", "--label", "L_REC",
            )
            with open(artifact, "rb") as fh:
                obj = json.loads(fh.read().decode("utf-8"))
            obj["leak"]["mode"] = "forged_mode"
            with open(artifact, "wb") as fh:
                fh.write(json.dumps(obj).encode("utf-8"))
            proc = self.run_cli(
                "--case", CASE02, "replay", "--artifact", artifact,
            )
            self.assertEqual(proc.returncode, 3)
            data = json.loads(proc.stdout.decode("utf-8"))
            self.assertEqual(data["verdict"], "tampered")

    def test_bad_case_returns_exit_code_2(self):
        proc = self.run_cli("--case", "no_such_file.json", "enumerate")
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
