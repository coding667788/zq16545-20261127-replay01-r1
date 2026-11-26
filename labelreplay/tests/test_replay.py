"""replay 重放复核：见证、互斥分支可达性、决胜顺序三类篡改必须被检出。"""

import copy
import json
import os
import tempfile
import unittest

from labelreplay.canonical import fingerprint
from labelreplay.commands import amend, enumerate_assignments, prove, replay
from labelreplay.errors import ReplayError
from labelreplay.model import parse_case

from _helper import load_case, CASE01, CASE02


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case(CASE02)

    def test_clean_artifact_replays_ok(self):
        artifact = prove(self.case, "G_AUDIT", "L_REC")
        out = replay(self.case, artifact)
        self.assertEqual(out["verdict"], "replay_ok")
        self.assertEqual(out["mismatches"], [])

    def test_tampered_witness_is_detected(self):
        # 篡改项 1：改写见证赋值（把 D1 换成一个不满足约束的取值）
        artifact = prove(self.case, "G_AUDIT", "L_REC")
        tampered = copy.deepcopy(artifact)
        bad = tampered["leak"]["witness_pair"]["assignment_beta"]
        bad["D1@v1"] = ["p", "q", "r", "s"]  # 不在有限域内
        out = replay(self.case, tampered)
        self.assertEqual(out["verdict"], "tampered")
        fields = {m["field"] for m in out["mismatches"]}
        self.assertIn("leak", fields)

    def test_tampered_mutex_reachability_is_detected(self):
        # 篡改项 2：在全枚举工件中插入一个互斥分支不可达的赋值
        # (C1=A, D2=r) 被 tuple_in 约束禁止。
        artifact = enumerate_assignments(self.case)
        original_count = artifact["feasible_count"]
        tampered = copy.deepcopy(artifact)
        tampered["assignments"].append({
            "C1@v1": "A",
            "D1@v1": ["p"],
            "D2@v1": "r",  # 仅在 C1=B 时允许
        })
        tampered["feasible_count"] = original_count + 1
        out = replay(self.case, tampered)
        self.assertEqual(out["verdict"], "tampered")
        fields = {m["field"] for m in out["mismatches"]}
        self.assertTrue({"feasible_count", "assignments"} & fields)

    def test_tampered_tie_break_order_is_detected(self):
        # 篡改项 3：用另一个等规模但更高损失的计划替换最优计划，
        # 并重算工件指纹 —— 重放仍应通过重新决胜识别出决胜被篡改。
        artifact = amend(self.case, "G_AUDIT", "L_REC", suppress_weight=12)
        tampered = copy.deepcopy(artifact)
        tampered["plan"] = [{"action": "S:r1", "loss": 12}]
        tampered["plan_size"] = 1
        tampered["total_loss"] = 12
        tampered["suppressed_reports"] = ["r1"]
        out = replay(self.case, tampered)
        self.assertEqual(out["verdict"], "tampered")
        fields = {m["field"] for m in out["mismatches"]}
        self.assertIn("plan", fields)

    def test_extra_forged_field_is_detected(self):
        artifact = prove(self.case, "G_AUDIT", "L_REC")
        tampered = copy.deepcopy(artifact)
        tampered["forged_approval"] = "backdoor"
        out = replay(self.case, tampered)
        self.assertEqual(out["verdict"], "tampered")
        fields = {m["field"] for m in out["mismatches"]}
        self.assertIn("forged_approval", fields)

    def test_case_fingerprint_mismatch_raises(self):
        artifact = prove(self.case, "G_AUDIT", "L_REC")
        other = load_case(CASE01)
        with self.assertRaises(ReplayError):
            replay(other, artifact)

    def test_tampered_case_file_detected_end_to_end(self):
        # 端到端：落盘的 case 被改一个符号后，工件指纹立即失效
        with open(CASE02, "rb") as fh:
            raw = json.loads(fh.read().decode("utf-8"))
        artifact = prove(self.case, "G_AUDIT", "L_REC")
        mutated = copy.deepcopy(raw)
        mutated["sources"][0]["versions"][0]["symbols"][0] = ["ZOMBIE"]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "mutated.json")
            with open(path, "wb") as fh:
                fh.write(json.dumps(mutated).encode("utf-8"))
            mutated_case = parse_case(mutated)
            with self.assertRaises(ReplayError):
                replay(mutated_case, artifact)

    def test_result_fingerprint_covers_payload(self):
        artifact = prove(self.case, "G_AUDIT", "L_REC")
        body = {k: v for k, v in artifact.items()
                if k != "result_fingerprint"}
        self.assertEqual(artifact["result_fingerprint"], fingerprint(body))


class CrossCommandReplayTests(unittest.TestCase):
    def test_amend_and_enumerate_artifacts_replay(self):
        case = load_case(CASE02)
        for artifact in (
            amend(case, "G_AUDIT", "L_REC"),
            enumerate_assignments(case),
        ):
            out = replay(case, artifact)
            self.assertEqual(out["verdict"], "replay_ok")


if __name__ == "__main__":
    unittest.main()
