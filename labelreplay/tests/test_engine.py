"""标签传播、非干扰与冻结策略窗口测试（含两项手算实例核对）。"""

import unittest

from labelreplay.engine import Engine
from labelreplay.solver import solve

from _helper import load_case, CASE01, CASE02


class Case01FrozenPolicyTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case(CASE01)
        self.sols = solve(self.case)

    def test_len_invariant_declassifies_in_w1(self):
        # 四个文档等长（长度 3），len 恒为 3 → 白名单+概要+NI 去 L_DOC
        e = Engine(self.case, policy_window="w1", solutions=self.sols)
        self.assertTrue(e.ni_check("n1@v1", "L_DOC")[0])
        self.assertNotIn("L_DOC", e.labels["n1@v1"]["data"])
        self.assertIn("L_DOC", e.labels["n1@v1"]["dropped_data"])

    def test_whitelist_revoked_in_w2_reintroduces_label(self):
        # w2 撤销 n1@v2 白名单：即使 NI 成立，标签也必须残留
        e2 = Engine(self.case, policy_window="w2", solutions=self.sols)
        self.assertTrue(e2.ni_check("n1@v2", "L_DOC")[0])
        self.assertIn("L_DOC", e2.labels["n1@v2"]["data"])
        # 旧的 n1@v1 白名单在两个窗口都保持冻结有效
        self.assertNotIn("L_DOC", e2.labels["n1@v1"]["data"])

    def test_rollback_node_uses_frozen_window(self):
        # n6 同时依赖 n1@v2 与回滚版本 n1@v1
        e1 = Engine(self.case, policy_window="w1", solutions=self.sols)
        e2 = Engine(self.case, policy_window="w2", solutions=self.sols)
        self.assertEqual(e1.labels["n6@v1"]["data"], set())
        self.assertIn("L_DOC", e2.labels["n6@v1"]["data"])

    def test_prove_safe_for_archived_w1_report(self):
        from labelreplay.commands import prove

        out = prove(self.case, "G_AUDIT", "L_DOC", window="w1")
        self.assertEqual(out["verdict"], "safe")

    def test_prove_leak_after_whitelist_revocation(self):
        from labelreplay.commands import prove

        out = prove(self.case, "G_AUDIT", "L_DOC", window="w2")
        self.assertEqual(out["verdict"], "leak")
        self.assertEqual(out["leak"]["mode"], "declassification_not_authorized")

    def test_control_label_cannot_be_removed_by_summary(self):
        # n4 是 mux，携带控制标签 L_CTL；概要函数无权去除
        e = Engine(self.case, policy_window="w1", solutions=self.sols)
        self.assertIn("L_CTL", e.labels["n4@v1"]["control"])


class Case02LabelAndNITests(unittest.TestCase):
    def setUp(self):
        self.case = load_case(CASE02)
        self.sols = solve(self.case)
        self.engine = Engine(
            self.case, policy_window="w1", solutions=self.sols
        )

    def test_wide_bucket_is_invariant_and_drops_label(self):
        self.assertTrue(self.engine.ni_check("n5@v1", "L_REC")[0])
        self.assertNotIn("L_REC", self.engine.labels["n5@v1"]["data"])

    def test_narrow_bucket_varies_and_keeps_label(self):
        invariant, witness = self.engine.ni_check("n4@v1", "L_REC")
        self.assertFalse(invariant)
        self.assertIsNotNone(witness)
        self.assertIn("L_REC", self.engine.labels["n4@v1"]["data"])
        # 见证对固定其他变量，仅 L_REC 变量变化
        a1, a2 = witness
        self.assertEqual(a1["C1@v1"], a2["C1@v1"])
        self.assertNotEqual(a1["D1@v1"], a2["D1@v1"])

    def test_witness_pair_both_satisfy_constraints(self):
        from labelreplay.solver import check_partial

        _, witness = self.engine.ni_check("n3@v1", "L_REC")
        self.assertIsNotNone(witness)
        for assignment in witness:
            self.assertTrue(
                check_partial(self.case["constraints"], assignment)
            )

    def test_shortest_sensitive_chain(self):
        chain = self.engine.sensitive_chain("n3@v1", "L_REC")
        self.assertEqual(chain[0], "n3@v1")
        self.assertTrue(chain[-1].startswith("src:"))
        self.assertLessEqual(len(chain), 4)

    def test_control_label_residual_is_leak_even_if_invariant(self):
        rep = next(r for r in self.case["reports"] if r["id"] == "r2")
        status = self.engine.report_status(rep, "L_SW")
        self.assertTrue(status["leak"])
        self.assertEqual(status["mode"], "control_label_residual")
        self.assertTrue(status["invariant"])  # NI 成立也不能救控制标签

    def test_prove_leak_payload(self):
        from labelreplay.commands import prove

        out = prove(self.case, "G_AUDIT", "L_REC")
        self.assertEqual(out["verdict"], "leak")
        self.assertEqual(out["leak"]["mode"], "non_interference_failure")
        self.assertIsNotNone(out["leak"]["witness_pair"])
        self.assertIsNotNone(out["leak"]["shortest_sensitive_chain"])


if __name__ == "__main__":
    unittest.main()
