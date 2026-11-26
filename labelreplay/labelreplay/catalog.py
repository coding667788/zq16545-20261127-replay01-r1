"""已许可的硬ening（屏蔽/替换/禁出）动作目录。

共 16 个已许可屏蔽控制信号 M01..M16，外加替换摘要算子 R1..R4 与
禁出动作 S:<报告 id>。所有动作只操作虚构抽象值，离线、确定、可重放。

信号记录字段：
  applies   : 适用节点 op 集合（"*" 表示全部 1 元数据节点）
  kind      : replace|input_mask|fixed_branch|table_const|control_mask|fixed
  loss      : 业务损失权重（越小越好）
  index     : 作用的输入下标（input_mask 用）
  op/params : 替换后的算子与参数
  drop      : "all_data" 表示该硬ening会擦除节点处全部数据标签；
              None 表示不直接擦标签（如弱控制 M08，仅固定控制值）
"""

# 16 个已许可屏蔽控制信号（目录顺序固定，决胜与目录顺序无关，按动作码字典序）
SIGNALS = {
    "M01": {"applies": {"len", "bucket", "hash_prefix", "table_lookup"},
            "kind": "replace", "op": "mask_star", "params": {},
            "loss": 4, "drop": "all_data"},
    "M02": {"applies": {"len", "bucket", "hash_prefix", "table_lookup"},
            "kind": "replace", "op": "fixed", "params": {"value": "■"},
            "loss": 4, "drop": "all_data"},
    "M03": {"applies": {"len", "bucket", "hash_prefix", "table_lookup"},
            "kind": "replace", "op": "fixed", "params": {"value": "?"},
            "loss": 5, "drop": "all_data"},
    "M04": {"applies": {"pair"}, "kind": "input_mask", "index": 0,
            "loss": 3, "drop": "all_data"},
    "M05": {"applies": {"pair"}, "kind": "input_mask", "index": 1,
            "loss": 3, "drop": "all_data"},
    "M06": {"applies": {"concat"}, "kind": "input_mask", "index": 0,
            "loss": 4, "drop": "all_data"},
    "M07": {"applies": {"concat"}, "kind": "input_mask", "index": -1,
            "loss": 4, "drop": "all_data"},
    "M08": {"applies": {"mux"}, "kind": "control_mask",
            "loss": 3, "drop": None},
    "M09": {"applies": {"mux"}, "kind": "fixed_branch", "branch": 0,
            "loss": 4, "drop": "all_inputs"},
    "M10": {"applies": {"mux"}, "kind": "fixed_branch", "branch": 1,
            "loss": 4, "drop": "all_inputs"},
    "M11": {"applies": {"table_lookup"}, "kind": "table_const",
            "params": {"value": "■"}, "loss": 4, "drop": "all_data"},
    "M12": {"applies": {"table_lookup"}, "kind": "table_const",
            "params": {"value": "?"}, "loss": 5, "drop": "all_data"},
    "M13": {"applies": {"count_distinct", "sum_sizes"},
            "kind": "input_mask", "index": 0, "loss": 4, "drop": "all_data"},
    "M14": {"applies": {"count_distinct", "sum_sizes"},
            "kind": "input_mask", "index": -1, "loss": 4, "drop": "all_data"},
    "M15": {"applies": {"eq"}, "kind": "replace", "op": "fixed",
            "params": {"value": False}, "loss": 5, "drop": "all_data"},
    "M16": {"applies": {"hash_prefix"}, "kind": "replace", "op": "fixed",
            "params": {"value": "#"}, "loss": 6, "drop": "all_data"},
}

# 替换摘要算子（不自动擦标签：重算标签，只有通过非干扰+白名单才去标签）
REPLACEMENTS = {
    "R1": {"applies": {"len", "bucket", "hash_prefix", "table_lookup", "mask_star"},
           "op": "len", "params": {}, "loss": 2},
    "R2": {"applies": {"len", "hash_prefix", "table_lookup", "mask_star"},
           "op": "bucket", "params": {"width": 1}, "loss": 3},
    "R3": {"applies": {"mux"}, "op": "fixed", "params": {"value": "■"},
           "loss": 5},
    "R4": {"applies": {"eq"}, "op": "fixed", "params": {"value": False},
           "loss": 4},
}

SUPPRESS_PREFIX = "S"


def suppress_code(report_id):
    return f"{SUPPRESS_PREFIX}:{report_id}"


def applicable_signals(node):
    out = []
    for code, spec in SIGNALS.items():
        if node["op"] in spec["applies"]:
            out.append(code)
    return sorted(out)


def applicable_replacements(node):
    out = []
    for code, spec in REPLACEMENTS.items():
        if node["op"] in spec["applies"]:
            out.append(code)
    return sorted(out)


def parse_action(code):
    """动作码 -> (家族, 标识, 节点键或 None)。"""
    if code.startswith("S:"):
        return "suppress", code[2:], None
    head, _, rest = code.partition("@")
    if not rest:
        raise ValueError(f"动作码 {code!r} 缺少 '@节点键'")
    if head in SIGNALS:
        return "signal", head, rest
    if head in REPLACEMENTS:
        return "replacement", head, rest
    raise ValueError(f"未知动作码 {code!r}")


def make_action(family, ident, node_key=None):
    if family == "suppress":
        return suppress_code(ident)
    return f"{ident}@{node_key}"
