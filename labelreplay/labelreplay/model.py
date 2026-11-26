"""夹具解析与校验：把原始 JSON 转成规范化的内部模型。

引用（ref）支持两种写法：
  字符串简写："D1@v1"（源版本变量）、"n1@v1"（节点版本输出）
  对象：{"source": "D1", "version": "v1"} 或 {"node": "n1", "version": "v1"}
"""

from .errors import ValidationError

DEFAULT_VERSION = "v1"


def parse_ref(ref):
    """把引用规范化为 ("source"|"node", id, version)。"""
    if isinstance(ref, str):
        if "@" not in ref:
            raise ValidationError(f"引用 {ref!r} 缺少 '@version'")
        ident, version = ref.split("@", 1)
        kind = None  # 由调用方按存在性判定
        return kind, ident, version
    if isinstance(ref, dict):
        if "source" in ref:
            return "source", str(ref["source"]), str(ref.get("version", DEFAULT_VERSION))
        if "node" in ref:
            return "node", str(ref["node"]), str(ref.get("version", DEFAULT_VERSION))
    raise ValidationError(f"无法解析引用: {ref!r}")


def ref_key(ref):
    _, ident, version = parse_ref(ref)
    return f"{ident}@{version}"


def _require(cond, msg):
    if not cond:
        raise ValidationError(msg)


def _normalize_constraint(raw):
    ctype = raw.get("type")
    if ctype in ("all_equal", "all_different"):
        vars_ = [ref_key(v) for v in raw["vars"]]
        _require(len(vars_) >= 2, f"约束 {ctype} 至少需要两个变量")
        return {"type": ctype, "vars": vars_}
    if ctype in ("allowed", "forbidden"):
        var = ref_key(raw["var"])
        return {"type": ctype, "var": var, "values": list(raw["values"])}
    if ctype == "implies":
        return {
            "type": "implies",
            "if_var": ref_key(raw["if_var"]),
            "if_in": list(raw["if_in"]),
            "then_var": ref_key(raw["then_var"]),
            "then_in": list(raw["then_in"]),
        }
    if ctype == "tuple_in":
        vars_ = [ref_key(v) for v in raw["vars"]]
        tuples = [list(t) for t in raw["tuples"]]
        _require(
            all(len(t) == len(vars_) for t in tuples),
            "tuple_in 中元组长度必须与变量数一致",
        )
        return {"type": "tuple_in", "vars": vars_, "tuples": tuples}
    raise ValidationError(f"未知约束类型: {ctype!r}")


def _constraint_vars(con):
    if con["type"] in ("all_equal", "all_different", "tuple_in"):
        return list(con["vars"])
    if con["type"] in ("allowed", "forbidden"):
        return [con["var"]]
    return [con["if_var"], con["then_var"]]


def parse_case(raw):
    _require(isinstance(raw, dict), "夹具根必须是 JSON 对象")
    _require(raw.get("schema_version") == "1.0", "schema_version 必须为 '1.0'")
    case_id = str(raw.get("case_id", ""))
    _require(case_id, "缺少 case_id")

    # ---- 来源 / 变量 ----
    variables = {}
    var_order = []
    label_kind = {}
    for src in raw.get("sources", []):
        sid = str(src["id"])
        label = str(src["label"])
        lk = str(src.get("label_kind", "data"))
        _require(lk in ("data", "control"), f"来源 {sid} 的 label_kind 非法")
        if label in label_kind:
            _require(
                label_kind[label] == lk,
                f"标签 {label} 同时被声明为 data 和 control",
            )
        else:
            label_kind[label] = lk
        kind = str(src.get("kind", "scalar"))
        _require(kind in ("scalar", "list"), f"来源 {sid} 的 kind 非法")
        versions = src.get("versions", [])
        _require(versions, f"来源 {sid} 至少需要一个版本")
        seen_versions = set()
        for ver in versions:
            vname = str(ver["version"])
            _require(vname not in seen_versions, f"来源 {sid} 版本 {vname} 重复")
            seen_versions.add(vname)
            symbols = ver["symbols"]
            _require(
                isinstance(symbols, list) and 2 <= len(symbols) <= 4,
                f"来源 {sid}@{vname} 每个有限域必须取 2-4 种符号",
            )
            var_id = f"{sid}@{vname}"
            _require(var_id not in variables, f"变量 {var_id} 重复定义")
            variables[var_id] = {
                "source": sid,
                "version": vname,
                "kind": kind,
                "domain": list(symbols),
                "label": label,
            }
            var_order.append(var_id)

    labels = set(label_kind)

    # ---- 约束 ----
    constraints = [_normalize_constraint(c) for c in raw.get("constraints", [])]
    for con in constraints:
        for v in _constraint_vars(con):
            _require(v in variables, f"约束引用了未知变量 {v}")

    # ---- 节点 ----
    nodes = {}
    for nd in raw.get("nodes", []):
        nid = str(nd["id"])
        nver = str(nd.get("version", DEFAULT_VERSION))
        key = f"{nid}@{nver}"
        _require(key not in nodes, f"节点 {key} 重复定义")
        data_inputs = [ref_key(r) for r in nd.get("data_inputs", [])]
        control_inputs = [ref_key(r) for r in nd.get("control_inputs", [])]
        op = str(nd["op"])
        params = nd.get("params", {}) or {}
        approved = bool(nd.get("approved_summary", False))
        declass = [str(x) for x in nd.get("declass", [])]
        for lab in declass:
            _require(lab in labels, f"节点 {key} 试图去掉未知标签 {lab}")
        if declass:
            _require(
                approved,
                f"节点 {key} 声明 declass 但 approved_summary 不为 true",
            )
        nodes[key] = {
            "id": nid,
            "version": nver,
            "op": op,
            "data_inputs": data_inputs,
            "control_inputs": control_inputs,
            "params": params,
            "approved_summary": approved,
            "declass": declass,
        }

    # 引用解析 + DAG 校验
    def resolve(ref):
        kind_hint, ident, version = parse_ref(ref)
        key = f"{ident}@{version}"
        if key in variables:
            return "source", key
        if key in nodes:
            return "node", key
        raise ValidationError(f"引用 {key} 不存在")

    for key, nd in nodes.items():
        resolved = []
        for r in nd["data_inputs"]:
            kind, rkey = resolve(r)
            resolved.append((kind, rkey))
        nd["data_inputs"] = resolved
        resolved_c = []
        for r in nd["control_inputs"]:
            kind, rkey = resolve(r)
            resolved_c.append((kind, rkey))
        nd["control_inputs"] = resolved_c

    node_order = _topo_sort(nodes)

    # ---- 策略（按版本窗口冻结） ----
    policies = {}
    for pol in raw.get("policies", []):
        window = str(pol["window"])
        _require(window not in policies, f"策略窗口 {window} 重复")
        wl = {}
        for node_ref, labs in pol.get("whitelist", {}).items():
            _, ident, version = parse_ref(node_ref)
            target_keys = []
            if version and f"{ident}@{version}" in nodes:
                target_keys = [f"{ident}@{version}"]
            else:
                target_keys = [k for k in nodes if nodes[k]["id"] == ident]
            _require(target_keys, f"白名单引用未知节点 {node_ref}")
            for tk in target_keys:
                for lab in labs:
                    _require(lab in labels, f"窗口 {window} 白名单含未知标签 {lab}")
                    wl.setdefault(tk, set()).add(str(lab))
        policies[window] = {"whitelist": wl, "note": str(pol.get("note", ""))}

    # ---- 报告 ----
    reports = []
    for rp in raw.get("reports", []):
        rid = str(rp["id"])
        nkey = ref_key(rp["node"]) if isinstance(rp["node"], (str, dict)) else None
        if nkey is None:
            nkey = f"{rp['node']}@{rp.get('version', DEFAULT_VERSION)}"
        _require(nkey in nodes, f"报告 {rid} 引用未知节点 {nkey}")
        window = str(rp["window"])
        _require(window in policies, f"报告 {rid} 引用未知策略窗口 {window}")
        reports.append(
            {
                "id": rid,
                "node_key": nkey,
                "group": str(rp["group"]),
                "window": window,
                "description": str(rp.get("description", "")),
            }
        )
    report_ids = [r["id"] for r in reports]
    _require(len(report_ids) == len(set(report_ids)), "报告 id 重复")

    # ---- 观察点（amend 必须保留的业务区分能力） ----
    observe = []
    for ob in raw.get("observe", []):
        nkey = ref_key(ob["node"])
        _require(nkey in nodes, f"观察点引用未知节点 {nkey}")
        on_vars = [ref_key(v) for v in ob.get("distinguish_on", [])]
        for v in on_vars:
            _require(v in variables, f"观察点区分变量 {v} 不存在")
        observe.append(
            {
                "id": str(ob["id"]),
                "node_key": nkey,
                "distinguish_on": on_vars,
            }
        )

    return {
        "case_id": case_id,
        "description": str(raw.get("description", "")),
        "variables": variables,
        "var_order": var_order,
        "label_kind": label_kind,
        "constraints": constraints,
        "nodes": nodes,
        "node_order": node_order,
        "policies": policies,
        "reports": reports,
        "observe": observe,
    }


def _topo_sort(nodes):
    """Kahn 拓扑排序，同层按节点键字典序，保证可重放的确定性。"""
    indeg = {k: 0 for k in nodes}
    adj = {k: [] for k in nodes}
    for key, nd in nodes.items():
        for kind, rkey in nd["data_inputs"] + nd["control_inputs"]:
            if kind == "node":
                adj[rkey].append(key)
                indeg[key] += 1
    ready = sorted(k for k, d in indeg.items() if d == 0)
    order = []
    while ready:
        cur = ready.pop(0)
        order.append(cur)
        for nxt in sorted(adj[cur]):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
        ready.sort()
    if len(order) != len(nodes):
        raise ValidationError("节点依赖图存在环，无法拓扑排序")
    return order
