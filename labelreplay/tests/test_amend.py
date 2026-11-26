"""amend 最小损失规划与观察点区分能力测试。"""

import unittest

from labelreplay import catalog
from labelreplay.commands import amend
from labelreplay.engine import Engine
from labelreplay.solver import solve

from _helper import load_case, CASE02


class AmendTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case(CASE02)
        self.sols = solve(self.case)

    def test_prefers_lower_loss_over_fewer_actions(self):
        out = amend(self.case, "G_AUDIT", "L_REC", suppress_weight=12)
        # 禁出单动作损失 12；信号+替换组合损失 8 → 选后者（损失优先）
        self.assertEqual(out["total_loss"], 8)
        self.assertEqual(out["plan_size"], 2)
        self.assertEqual(out["suppressed_reports"], [])
        actions = {p["action"] for p in out["plan"]}
        self.assertIn("M05@n3@v1", actions)
        self.assertIn("R3@nA@v1", actions)

    def test_suppression_wins_when_cheapest(self):
        # 把禁出权重降到 1，单动作禁出成为最低损失
        out = amend(self.case, "G_AUDIT", "L_REC", suppress_weight=1)
        self.assertEqual(out["plan"], [{"action": "S:r1", "loss": 1}])
        self.assertEqual(out["suppressed_reports"], ["r1"])

    def test_plan_actually_removes_leak(self):
        out = amend(self.case, "G_AUDIT", "L_REC", suppress_weight=12)
        codes = [p["action"] for p in out["plan"]]
        engine = Engine(
            self.case, policy_window="w1", actions=codes,
            solutions=self.sols,
        )
        rep = next(r for r in self.case["reports"] if r["id"] == "r1")
        self.assertFalse(engine.report_status(rep, "L_REC")["leak"])

    def test_observation_discrimination_preserved(self):
        from labelreplay.commands import _observation_preserved

        out = amend(self.case, "G_AUDIT", "L_REC", suppress_weight=12)
        codes = [p["action"] for p in out["plan"]]
        engine = Engine(
            self.case, policy_window="w1", actions=codes,
            solutions=self.sols,
        )
        ok, failing = _observation_preserved(self.case, engine, self.sols)
        self.assertTrue(ok, f"观察点 {failing} 的区分能力被破坏")

    def test_plan_that_destroys_observation_is_rejected(self):
        # M02 把 n4（观察点）替换成固定常量 → 长度区分能力丧失，
        # 任何含该动作的计划都不可行。对照：M01(mask_star) 保留长度，
        # 不破坏观察点。
        from labelreplay.commands import _candidate_actions, _observation_preserved

        cands = _candidate_actions(self.case, "L_REC", "G_AUDIT")
        self.assertIn("M02@n4@v1", cands)
        # M01 保留结构长度，观察点仍然成立
        e_mask = Engine(
            self.case, policy_window="w1", actions=["M01@n4@v1"],
            solutions=self.sols,
        )
        ok_mask, _ = _observation_preserved(self.case, e_mask, self.sols)
        self.assertTrue(ok_mask)
        # M02 常量替换抹掉区分，观察点失败
        e_fixed = Engine(
            self.case, policy_window="w1", actions=["M02@n4@v1"],
            solutions=self.sols,
        )
        ok, failing = _observation_preserved(self.case, e_fixed, self.sols)
        self.assertFalse(ok)
        self.assertEqual(failing, "o1")

    def test_catalog_has_16_signals(self):
        self.assertEqual(len(catalog.SIGNALS), 16)
        codes = sorted(catalog.SIGNALS)
        self.assertEqual(codes[0], "M01")
        self.assertEqual(codes[-1], "M16")

    def test_tie_break_is_deterministic_and_lexicographic(self):
        out_a = amend(self.case, "G_AUDIT", "L_REC", suppress_weight=12)
        out_b = amend(self.case, "G_AUDIT", "L_REC", suppress_weight=12)
        self.assertEqual(
            [p["action"] for p in out_a["plan"]],
            [p["action"] for p in out_b["plan"]],
        )


if __name__ == "__main__":
    unittest.main()
