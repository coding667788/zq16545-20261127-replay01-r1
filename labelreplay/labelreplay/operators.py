"""抽象算子注册表。

所有算子只处理虚构符号上的抽象值：
  标量 = str/int/bool；序列 = list（保持顺序）；对 = 二元 list。
算子只保留长度/桶/计数等信息摘要，绝不返回原始内容（fixed 除外，
fixed 只返回夹具里显式给定的常量，不读任何输入）。
"""

from .errors import ValidationError

# 每个算子的数据输入元数；None 表示任意长度（>=1）
ARITY = {
    "len": 1,
    "bucket": 1,
    "count_distinct": None,
    "pair": 2,
    "concat": None,
    "mux": None,
    "table_lookup": 1,
    "fixed": None,  # 常量替换：忽略节点原有数据输入元数
    "hash_prefix": 1,
    "sum_sizes": None,
    "mask_star": 1,
    "eq": 2,
}

# 已批准概要算子：允许在满足非干扰条件时去除数据标签
APPROVED_SUMMARIES = {
    "len",
    "bucket",
    "count_distinct",
    "sum_sizes",
    "hash_prefix",
}


def _as_list(value):
    return value if isinstance(value, list) else [value]


def op_len(value):
    if isinstance(value, list):
        return len(value)
    # 标量按“符号长度为 1”的抽象长度处理
    return 1


def op_bucket(value, params):
    width = int(params.get("width", 1))
    if width <= 0:
        raise ValidationError("bucket 的 width 必须为正整数")
    n = op_len(value)
    lo = (n // width) * width
    return f"B[{lo},{lo + width - 1}]"


def op_count_distinct(values):
    seen = []
    for v in values:
        for item in _as_list(v):
            if item not in seen:
                seen.append(item)
    return len(seen)


def op_pair(a, b):
    return [a, b]


def op_concat(values):
    out = []
    for v in values:
        out.extend(_as_list(v))
    return out


def op_mux(branch_values, control_value, params):
    """按控制值选择分支；params 给出 branch 顺序与匹配表。"""
    table = params.get("branches")  # [{"when": ..., "index": i}, ...]
    if table is None:
        raise ValidationError("mux 需要 params.branches 表")
    for row in table:
        if row["when"] == control_value:
            return branch_values[int(row["index"])]
    if "default" in params:
        return branch_values[int(params["default"])]
    raise ValidationError(f"mux 控制值 {control_value!r} 没有匹配分支且无 default")


def op_table_lookup(value, params):
    table = params.get("table")  # [{"in": x, "out": y}, ...]
    if table is None:
        raise ValidationError("table_lookup 需要 params.table")
    for row in table:
        if row["in"] == value:
            return row["out"]
    if "default" in params:
        return params["default"]
    raise ValidationError(f"table_lookup 对值 {value!r} 无匹配且无 default")


def op_fixed(params):
    if "value" not in params:
        raise ValidationError("fixed 需要 params.value")
    return params["value"]


def op_hash_prefix(value, params):
    width = int(params.get("prefix", 2))
    if width <= 0:
        raise ValidationError("hash_prefix 的 prefix 必须为正整数")
    # 确定性伪指纹（纯标准库 hashlib，离线）；对输入是单射式截断，
    # 因此默认不具备非干扰性，不能作为已批准概要去标签。
    import hashlib

    digest = hashlib.sha256(repr(value).encode("utf-8")).hexdigest()
    return f"H:{digest[:width]}"


def op_sum_sizes(values):
    return sum(op_len(v) for v in values)


def op_mask_star(value):
    """全部替换成虚构占位符 '★'，保留结构与长度信息。"""
    if isinstance(value, list):
        return ["★" for _ in value]
    return "★"


def op_eq(a, b):
    return a == b


def apply(op, data_values, control_values, params):
    if op not in ARITY:
        raise ValidationError(f"未知算子 {op!r}")
    arity = ARITY[op]
    # fixed 是常量替换，允许作用在任意元数的节点上（忽略其数据输入）
    if op != "fixed" and arity is not None and len(data_values) != arity:
        raise ValidationError(
            f"算子 {op} 需要 {arity} 个数据输入，实际 {len(data_values)}"
        )
    if op == "len":
        return op_len(data_values[0])
    if op == "bucket":
        return op_bucket(data_values[0], params)
    if op == "count_distinct":
        if not data_values:
            raise ValidationError("count_distinct 至少需要一个输入")
        return op_count_distinct(data_values)
    if op == "pair":
        return op_pair(data_values[0], data_values[1])
    if op == "concat":
        if not data_values:
            raise ValidationError("concat 至少需要一个输入")
        return op_concat(data_values)
    if op == "mux":
        if len(control_values) != 1:
            raise ValidationError("mux 需要恰好一个控制输入")
        if not data_values:
            raise ValidationError("mux 至少需要一个分支")
        return op_mux(data_values, control_values[0], params)
    if op == "table_lookup":
        return op_table_lookup(data_values[0], params)
    if op == "fixed":
        return op_fixed(params)
    if op == "hash_prefix":
        return op_hash_prefix(data_values[0], params)
    if op == "sum_sizes":
        if not data_values:
            raise ValidationError("sum_sizes 至少需要一个输入")
        return op_sum_sizes(data_values)
    if op == "mask_star":
        return op_mask_star(data_values[0])
    if op == "eq":
        return op_eq(data_values[0], data_values[1])
    raise ValidationError(f"算子 {op!r} 已注册但未实现")  # 不可达
