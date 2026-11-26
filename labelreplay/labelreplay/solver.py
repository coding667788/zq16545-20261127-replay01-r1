"""有限域合成赋值求解。

每个来源变量取 2-4 种符号；list 型变量取其符号集上长度 0..max_list_len 的
所有序列。提供两条独立实现：
  brute_force : 笛卡尔积后逐条过滤（小有限域全枚举，验收基准）
  backtrack   : 带增量约束检查的回溯（默认使用）
两者结果在测试中交叉验证一致。
"""

from itertools import product

from .errors import ValidationError


def value_key(value):
    """可哈希的规范键：list -> tuple，标量保持原样。"""
    if isinstance(value, list):
        return tuple(value_key(v) for v in value)
    return value


def _domain_for(var, max_list_len):
    symbols = var["domain"]
    if var["kind"] == "scalar":
        # 标量：每个符号是一个完整取值
        return list(symbols)
    # list 型：每个符号本身就是一个完整文档值（2-4 个候选文档），
    # 直接作为有限域，不再二次组合；max_list_len 仅用于校验长度上限。
    domain = [list(sym) for sym in symbols if len(sym) <= max_list_len]
    if not domain:
        raise ValidationError(
            f"来源变量的所有文档长度都超过 max_list_len={max_list_len}，"
            f"有限域为空"
        )
    return domain


def domains(case, max_list_len=3):
    return {vid: _domain_for(var, max_list_len) for vid, var in case["variables"].items()}


def check_partial(constraints, assignment):
    """对所有变量已赋值的约束求值；未齐变量的约束跳过。"""
    for con in constraints:
        ctype = con["type"]
        if ctype in ("allowed", "forbidden"):
            var = con["var"]
            if var not in assignment:
                continue
            key = value_key(assignment[var])
            allowed_keys = [value_key(v) for v in con["values"]]
            if ctype == "allowed" and key not in allowed_keys:
                return False
            if ctype == "forbidden" and key in allowed_keys:
                return False
        elif ctype in ("all_equal", "all_different"):
            if not all(v in assignment for v in con["vars"]):
                continue
            keys = [value_key(assignment[v]) for v in con["vars"]]
            if ctype == "all_equal" and len(set(keys)) != 1:
                return False
            if ctype == "all_different" and len(set(keys)) != len(keys):
                return False
        elif ctype == "implies":
            if con["if_var"] not in assignment or con["then_var"] not in assignment:
                continue
            if_key = value_key(assignment[con["if_var"]])
            then_key = value_key(assignment[con["then_var"]])
            if if_key in [value_key(v) for v in con["if_in"]]:
                if then_key not in [value_key(v) for v in con["then_in"]]:
                    return False
        elif ctype == "tuple_in":
            if not all(v in assignment for v in con["vars"]):
                continue
            tkey = tuple(value_key(assignment[v]) for v in con["vars"])
            allowed = [
                tuple(value_key(x) for x in t) for t in con["tuples"]
            ]
            if tkey not in allowed:
                return False
    return True


def brute_force(case, max_list_len=3):
    """全枚举基准实现：笛卡尔积 + 完整约束过滤，按规范序输出。"""
    dom = domains(case, max_list_len)
    order = case["var_order"]
    solutions = []
    for combo in product(*(dom[v] for v in order)):
        assignment = dict(zip(order, combo))
        if check_partial(case["constraints"], assignment):
            solutions.append(assignment)
    return solutions


def backtrack(case, max_list_len=3):
    """回溯实现：按 var_order 赋值，每步增量剪枝。"""
    dom = domains(case, max_list_len)
    order = case["var_order"]
    assignment = {}
    solutions = []

    def recurse(idx):
        if idx == len(order):
            solutions.append(dict(assignment))
            return
        vid = order[idx]
        for val in dom[vid]:
            assignment[vid] = val
            if check_partial(case["constraints"], assignment):
                recurse(idx + 1)
        assignment.pop(vid, None)

    recurse(0)
    return solutions


def solve(case, max_list_len=3):
    """默认入口，返回满足全部约束的合成赋值列表。"""
    return backtrack(case, max_list_len)

