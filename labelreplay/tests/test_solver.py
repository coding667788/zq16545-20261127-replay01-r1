"""求解器测试：回溯与暴力全枚举必须一致；约束语义手算核对。"""

import unittest

from labelreplay.solver import brute_force, backtrack, check_partial, value_key

from _helper import load_case, CASE01, CASE02


class SolverTests(unittest.TestCase):
    def test_two_solvers_agree_case01(self):
        case = load_case(CASE01)
        bf = brute_force(case)
        bt = backtrack(case)
        self.assertEqual(
            [tuple((v, value_key(a[v])) for v in case["var_order"]) for a in bf],
            [tuple((v, value_key(a[v])) for v in case["var_order"]) for a in bt],
        )

    def test_two_solvers_agree_case02(self):
        case = load_case(CASE02)
        bf = brute_force(case)
        bt = backtrack(case)
        self.assertEqual(len(bf), len(bt))
        self.assertEqual(
            [tuple((v, value_key(a[v])) for v in case["var_order"]) for a in bf],
            [tuple((v, value_key(a[v])) for v in case["var_order"]) for a in bt],
        )

    def test_case02_manual_feasible_count(self):
        # D1 4 个文档；约束 (C1,D2) ∈ {(A,p),(A,q),(B,r)} 共 3 组 → 12
        case = load_case(CASE02)
        sols = backtrack(case)
        self.assertEqual(len(sols), 12)

    def test_mutex_branches_never_joint(self):
        # n7 = pair(gA,gB)：只允许 (true,false) 或 (false,true)，
        # (true,true)/(false,false) 不可达。
        case = load_case(CASE02)
        from labelreplay.engine import Engine

        sols = backtrack(case)
        engine = Engine(case, policy_window="w1", solutions=sols)
        seen = {value_key(engine.evaluate(a)["n7@v1"]) for a in sols}
        # table_lookup 输出 Python 布尔，value_key 保留为 (True, False)
        self.assertEqual(seen, {(True, False), (False, True)})
        # 互斥：两种混合状态均不可达
        self.assertNotIn((True, True), seen)
        self.assertNotIn((False, False), seen)

    def test_implies_constraint_case01(self):
        # C1=on 时 D2 只能是 x/y；C1=off 时 D2 任意
        case = load_case(CASE01)
        sols = backtrack(case)
        for a in sols:
            if a["C1@v1"] == "on":
                self.assertIn(a["D2@v1"], ("x", "y"))
        # 两种 C1 取值都应可达
        self.assertEqual({a["C1@v1"] for a in sols}, {"on", "off"})

    def test_check_partial_skips_unassigned(self):
        case = load_case(CASE02)
        self.assertTrue(check_partial(case["constraints"], {}))
        self.assertFalse(check_partial(
            case["constraints"], {"C1@v1": "A", "D2@v1": "r"}
        ))
        self.assertTrue(check_partial(
            case["constraints"], {"C1@v1": "A", "D2@v1": "p"}
        ))


if __name__ == "__main__":
    unittest.main()
