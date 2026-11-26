"""prove / amend / enumerate / replay 命令实现。"""

from . import catalog
from .canonical import fingerprint
from .engine import Engine
from .errors import ReplayError, ValidationError
from .solver import brute_force, solve, value_key


# ----------------------------------------------------------------------
# prove
# ----------------------------------------------------------------------
def _witness_payload(witness):
    if witness is None:
        return None
    a1, a2 = witness
    return {"assignment_alpha": dict(a1), "assignment_beta": dict(a2)}


def prove(case, group, label, window=None, max_list_len=3):
    if label not in case["label_kind"]:
        raise ValidationError(f"未知保护标签 {label}")
    reports = [r for r in case["reports"] if r["group"] == group]
    if not reports:
        raise ValidationError(f"保护组 {group} 没有任何报告")

    # 按报告归档窗口分组：旧报告用归档时冻结的策略窗口复核
    windows = sorted({r["window"] for r in reports})
    if window is not None:
        if window not in windows:
            raise ValidationError(
                f"保护组 {group} 在窗口 {window} 下没有任何报告"
            )
        # 显式指定窗口时只复核该窗口报告；默认覆盖该组全部窗口
        reports = [r for r in reports if r["window"] == window]
        windows = [window]

    solutions = solve(case, max_list_len)
    case_fp = fingerprint(case)
    engines = {
        w: Engine(case, policy_window=w, solutions=solutions,
                  max_list_len=max_list_len)
        for w in windows
    }

    report_results = []
    for report in reports:
        engine = engines[report["window"]]
        status = engine.report_status(report, label)
        chain = None
        if status["leak"]:
            chain = engine.sensitive_chain(report["node_key"], label)
        report_results.append({
            "report_id": report["id"],
            "node_key": report["node_key"],
            "window": report["window"],
            "leak": status["leak"],
            "mode": status["mode"],
            "label_present": status["present"],
            "non_interferent": status["invariant"],
            "shortest_sensitive_chain": chain,
            "witness_pair": _witness_payload(status["witness"]),
            "label_set": {
                "data": sorted(engine.labels[report["node_key"]]["data"]),
                "control": sorted(engine.labels[report["node_key"]]["control"]),
            },
        })

    leaks = [r for r in report_results if r["leak"]]
    payload = {
        "tool": "labelreplay",
        "command": "prove",
        "case_id": case["case_id"],
        "case_fingerprint": case_fp,
        "group": group,
        "label": label,
        "label_kind": case["label_kind"][label],
        "feasible_assignments": len(solutions),
        "windows_checked": windows,
        "reports_checked": [r["id"] for r in reports],
    }
    if not leaks:
        payload["verdict"] = "safe"
        payload["proof"] = {
            "rule": (
                "数据标签：白名单 + 已批准概要 + 全部可行赋值下非干扰；"
                "控制标签：概要函数不可去除，仅控制信号可切断"
            ),
            "per_report": [
                {
                    "report_id": r["report_id"],
                    "window": r["window"],
                    "label_present": r["label_present"],
                    "non_interferent": r["non_interferent"],
                    "final_labels": r["label_set"],
                }
                for r in report_results
            ],
            "family_digest": _family_digest(case, engines, reports),
        }
    else:
        first = min(leaks, key=lambda r: (
            len(r["shortest_sensitive_chain"] or []), r["report_id"]
        ))
        payload["verdict"] = "leak"
        payload["leak"] = {
            "report_id": first["report_id"],
            "node_key": first["node_key"],
            "window": first["window"],
            "mode": first["mode"],
            "shortest_sensitive_chain": first["shortest_sensitive_chain"],
            "witness_pair": first["witness_pair"],
        }
        payload["all_report_results"] = report_results
    payload["result_fingerprint"] = fingerprint(
        {k: v for k, v in payload.items() if k != "result_fingerprint"}
    )
    return payload


def _family_digest(case, engines, reports):
    digest = []
    for report in reports:
        engine = engines[report["window"]]
        families = engine.output_families(report["node_key"])
        distinct = sorted({f["output_key"] for f in families})
        digest.append({
            "report_id": report["id"],
            "distinct_output_count": len(distinct),
            "distinct_outputs": [_jsonable(k) for k in distinct],
        })
    return digest


def _jsonable(key):
    if isinstance(key, tuple):
        return [_jsonable(x) for x in key]
    return key


# ----------------------------------------------------------------------
# 观察点业务区分能力
# ----------------------------------------------------------------------
def _observation_preserved(case, engine, solutions):
    for ob in case["observe"]:
        on = set(ob["distinguish_on"])
        groups = {}
        for assignment in solutions:
            ctx = tuple(
                (v, value_key(assignment[v]))
                for v in case["var_order"] if v not in on
            )
            out = value_key(engine.evaluate(assignment)[ob["node_key"]])
            groups.setdefault(ctx, set()).add(out)
        # 每个固定上下文中，观察点必须仍能区分 on 变量的不同取值
        if any(len(outs) < 2 for outs in groups.values()):
            return False, ob["id"]
    return True, None


# ----------------------------------------------------------------------
# amend
# ----------------------------------------------------------------------
def _candidate_actions(case, label, group):
    """生成全部候选动作（报告禁出 + 节点信号/替换），按动作码排序。"""
    actions = set()
    for report in case["reports"]:
        if report["group"] == group:
            actions.add(catalog.suppress_code(report["id"]))
    for node_key, node in case["nodes"].items():
        for code in catalog.applicable_signals(node):
            actions.add(catalog.make_action("signal", code, node_key))
        for code in catalog.applicable_replacements(node):
            actions.add(catalog.make_action("replacement", code, node_key))
    return sorted(actions)


def _action_loss(case, code, suppress_weight):
    family, ident, _ = catalog.parse_action(code)
    if family == "suppress":
        return suppress_weight
    if family == "signal":
        return catalog.SIGNALS[ident]["loss"]
    return catalog.REPLACEMENTS[ident]["loss"]


def amend(case, group, label, max_list_len=3, suppress_weight=12,
          max_plan_size=4):
    if label not in case["label_kind"]:
        raise ValidationError(f"未知保护标签 {label}")
    solutions = solve(case, max_list_len)
    candidates = _candidate_actions(case, label, group)
    windows = sorted({r["window"] for r in case["reports"]
                      if r["group"] == group})
    # 跨引擎共享无覆盖节点的求值结果，避免重复 DAG 计算
    shared_eval = {}

    def suppressed(codes):
        return {
            catalog.parse_action(c)[1] for c in codes
            if catalog.parse_action(c)[0] == "suppress"
        }

    feasible_cache = {}

    def is_feasible(codes):
        key = frozenset(codes)
        if key in feasible_cache:
            return feasible_cache[key]
        touched = set()
        for code in codes:
            family, _ident, node_key = catalog.parse_action(code)
            if family == "suppress":
                continue
            if node_key in touched:  # 同节点互斥覆盖
                feasible_cache[key] = False
                return False
            touched.add(node_key)
        try:
            engines = {
                window: Engine(
                    case, policy_window=window, actions=codes,
                    solutions=solutions, max_list_len=max_list_len,
                    shared_eval=shared_eval,
                )
                for window in windows
            }
            hidden = suppressed(codes)
            for report in case["reports"]:
                if report["group"] != group or report["id"] in hidden:
                    continue
                if engines[report["window"]].report_status(report, label)["leak"]:
                    feasible_cache[key] = False
                    return False
            # 业务区分能力必须在施加动作后的引擎上仍然成立
            ok, _ = _observation_preserved(
                case, engines[windows[0]], solutions
            )
            if not ok:
                feasible_cache[key] = False
                return False
        except ValidationError:
            feasible_cache[key] = False
            return False
        feasible_cache[key] = True
        return True

    # 同一节点至多一个非禁出动作（互斥覆盖），据此剪枝
    node_action_count = len({
        catalog.parse_action(c)[2] for c in candidates
        if catalog.parse_action(c)[0] != "suppress"
    })
    report_count = len([
        c for c in candidates if catalog.parse_action(c)[0] == "suppress"
    ])
    effective_max = min(max_plan_size, node_action_count + report_count)

    feasible_plans = []
    best_loss_so_far = [None]  # 分支限界：当前最优总损失

    def dfs(start, chosen, current_loss):
        if len(chosen) > effective_max:
            return
        # 分支限界：部分损失已严格超过已知最优，无需继续（损失均为正）；
        # 等于最优时保留，以便完整执行规模/字典序决胜。
        if best_loss_so_far[0] is not None and \
                current_loss > best_loss_so_far[0] and chosen:
            return
        if chosen:
            codes = tuple(sorted(chosen))
            if is_feasible(codes):
                feasible_plans.append((current_loss, len(codes), codes))
                if best_loss_so_far[0] is None or \
                        current_loss < best_loss_so_far[0]:
                    best_loss_so_far[0] = current_loss
        for i in range(start, len(candidates)):
            act = candidates[i]
            fam, _ident, node_key = catalog.parse_action(act)
            if fam != "suppress" and any(
                catalog.parse_action(c)[2] == node_key
                for c in chosen
                if catalog.parse_action(c)[0] != "suppress"
            ):
                continue
            chosen.append(act)
            dfs(i + 1, chosen,
                current_loss + _action_loss(case, act, suppress_weight))
            chosen.pop()

    dfs(0, [], 0)
    if not feasible_plans:
        raise ValidationError(
            f"在 {max_plan_size} 个动作内找不到可行修复计划"
        )

    # 决胜顺序（可重放、确定）：总损失升序 → 规模升序 → 动作码元组字典序
    loss, _size, codes = min(
        feasible_plans, key=lambda x: (x[0], x[1], x[2])
    )
    payload = {
        "tool": "labelreplay",
        "command": "amend",
        "case_id": case["case_id"],
        "case_fingerprint": fingerprint(case),
        "group": group,
        "label": label,
        "tie_break_rule": "(总损失升序, 计划规模升序, 动作码元组字典序)",
        "plan": [
            {"action": code, "loss": _action_loss(case, code, suppress_weight)}
            for code in codes
        ],
        "total_loss": loss,
        "plan_size": len(codes),
        "suppressed_reports": sorted(suppressed(codes)),
        "observation_points": [ob["id"] for ob in case["observe"]],
        "candidate_space_size": len(candidates),
        "feasible_plan_count": len(feasible_plans),
        "feasibility_cache_size": len(feasible_cache),
        "max_plan_size": effective_max,
    }
    payload["result_fingerprint"] = fingerprint(
        {k: v for k, v in payload.items() if k != "result_fingerprint"}
    )
    return payload


# ----------------------------------------------------------------------
# enumerate：小有限域全枚举
# ----------------------------------------------------------------------
def enumerate_assignments(case, max_list_len=3):
    brute = brute_force(case, max_list_len)
    back = solve(case, max_list_len)
    keys_b = [
        tuple((v, value_key(a[v])) for v in case["var_order"]) for a in brute
    ]
    keys_k = [
        tuple((v, value_key(a[v])) for v in case["var_order"]) for a in back
    ]
    if keys_b != keys_k:
        raise ReplayError("回溯与暴力全枚举结果不一致（求解器内部错误）")
    return {
        "tool": "labelreplay",
        "command": "enumerate",
        "case_id": case["case_id"],
        "case_fingerprint": fingerprint(case),
        "max_list_len": max_list_len,
        "solver_cross_check": "backtrack == brute_force",
        "feasible_count": len(brute),
        "assignments": [dict(a) for a in brute],
    }


# ----------------------------------------------------------------------
# replay：重放复核已产出的结果工件
# ----------------------------------------------------------------------
def replay(case, artifact, max_list_len=3):
    if fingerprint(case) != artifact.get("case_fingerprint"):
        raise ReplayError("夹具指纹不一致：case 已被篡改或不是同一份夹具")
    cmd = artifact.get("command")
    if cmd == "prove":
        fresh = prove(
            case, artifact["group"], artifact["label"],
            max_list_len=max_list_len
        )
    elif cmd == "amend":
        fresh = amend(
            case, artifact["group"], artifact["label"],
            max_list_len=max_list_len
        )
    elif cmd == "enumerate":
        fresh = enumerate_assignments(case, max_list_len=max_list_len)
    else:
        raise ValidationError(f"无法重放未知命令 {cmd!r}")

    mismatches = []
    for key in fresh:
        if key == "result_fingerprint":
            continue
        if key not in artifact:
            mismatches.append({"field": key, "reason": "结果工件缺少该字段"})
        elif artifact[key] != fresh[key]:
            mismatches.append({
                "field": key,
                "reason": "重算值与工件记录不一致（见证/可达性/决胜可能被篡改）",
                "recorded": artifact[key],
                "recomputed": fresh[key],
            })
    # 工件中出现重算结果没有的额外字段，同样视为伪造
    for key in artifact:
        if key not in fresh and key != "result_fingerprint":
            mismatches.append({"field": key, "reason": "工件包含重算结果中不存在的伪造字段"})
    recorded_fp = artifact.get("result_fingerprint")
    fresh_fp = fresh.get("result_fingerprint")
    if recorded_fp != fresh_fp:
        mismatches.append({
            "field": "result_fingerprint",
            "reason": "工件自身指纹与重算内容不符",
        })
    return {
        "tool": "labelreplay",
        "command": "replay",
        "case_id": case["case_id"],
        "replayed_command": cmd,
        "verdict": "replay_ok" if not mismatches else "tampered",
        "mismatches": mismatches,
    }

