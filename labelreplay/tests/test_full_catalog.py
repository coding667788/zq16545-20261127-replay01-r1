"""综合夹具 case03：全 16 信号目录覆盖与端到端命令测试。"""

import unittest

from labelreplay import catalog
from labelreplay.commands import amend, enumerate_assignments, prove
from labelreplay.engine import Engine
from labelreplay.solver import brute_force, solve

from _helper import load_case
import os

CASE03 = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "examples", "case03_full_catalog_coverage.json",
)


class FullCatalogTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case(CASE03)
        self.sols = solve(self.case)

    def test_all_sixteen_signals_applicable_somewhere(self):
        exercised = set()
        for node in self.case["nodes"].values():
            exercised.update(catalog.applicable_signals(node))
        self.assertEqual(exercised, set(catalog.SIGNALS))
        self.assertEqual(len(catalog.SIGNALS), 16)

    def test_every_signal_builds_engine(self):
        for node_key, node in self.case["nodes"].items():
            for code in catalog.applicable_signals(node):
                engine = Engine(
                    self.case, policy_window="w1",
                    actions=[f"{code}@{node_key}"], solutions=self.sols,
                )
                # 施加动作后所有可行赋值仍可求值
                for assignment in self.sols:
                    engine.evaluate(assignment)

    def test_every_replacement_builds_engine(self):
        for node_key, node in self.case["nodes"].items():
            for code in catalog.applicable_replacements(node):
                engine = Engine(
                    self.case, policy_window="w1",
                    actions=[f"{code}@{node_key}"], solutions=self.sols,
                )
                for assignment in self.sols:
                    engine.evaluate(assignment)

    def test_enumeration_matches_manual_count(self):
        # D1 4 文档 × (C1,D2) 3 组合 = 12
        self.assertEqual(len(brute_force(self.case)), 12)
        out = enumerate_assignments(self.case)
        self.assertEqual(out["feasible_count"], 12)

    def test_prove_runs_for_both_groups(self):
        for group, label in (("G_AUDIT", "L_A"), ("G_OPS", "L_SW")):
            out = prove(self.case, group, label)
            self.assertIn(out["verdict"], ("safe", "leak"))
            self.assertEqual(out["group"], group)

    def test_amend_returns_valid_plan(self):
        out = amend(self.case, "G_OPS", "L_SW")
        self.assertGreaterEqual(out["total_loss"], 1)
        self.assertLessEqual(out["plan_size"], out["max_plan_size"])
        # 计划中的动作码都可解析
        for item in out["plan"]:
            catalog.parse_action(item["action"])


if __name__ == "__main__":
    unittest.main()
