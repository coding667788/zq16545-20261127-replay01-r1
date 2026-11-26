"""标签传播与非干扰引擎。

标签规则（隔离策略）：
  * 数据标签：随数据依赖并集传播；已批准概要节点在「白名单 + 输出抽象值
    对全部可行赋值一致（非干扰）」两个条件同时成立时才能去掉该标签。
  * 控制标签：随控制依赖传播，再沿 mux 的数据分支继续传播；概要函数
    永远不能去除控制标签（与数据标签不同的规则），只能由固定分支等
    控制信号切断。
  * 版本依赖：节点可引用同一节点的旧版本输出（回滚），按普通边处理。
"""

from collections import deque

from . import catalog
from .errors import ValidationError
from .operators import APPROVED_SUMMARIES, apply
from .solver import solve, value_key


class Engine:
    def __init__(self, case, policy_window=None, actions=(), solutions=None,
                 max_list_len=3, shared_eval=None):
        self.case = case
        self.max_list_len = max_list_len
        self.solutions = (
            solutions if solutions is not None else solve(case, max_list_len)
        )
        if not self.solutions:
            raise ValidationError("约束过强：不存在任何可行合成赋值")
        self.window = policy_window
        self.policy = case["policies"][policy_window] if policy_window else None
        self.actions = tuple(actions)
        self._ni_cache = {}
        # 共享缓存：(赋值键, 节点键) -> 输出。仅缓存无覆盖节点，
        # 其输出只取决于来源与同样无覆盖的前驱，可跨引擎复用。
        self._shared_eval = shared_eval if shared_eval is not None else {}
        self._build_overrides()
        # 拓扑序下依赖节点必先填入，传播过程中增量读写
        self.labels = {}
        self.labels = self._propagate_labels()

    # ------------------------------------------------------------------
    # 硬ening动作 -> 节点级覆盖表
    # ------------------------------------------------------------------
    def _build_overrides(self):
        self.overrides = {}
        for code in self.actions:
            family, ident, node_key = catalog.parse_action(code)
            if family == "suppress":
                continue
            if node_key not in self.case["nodes"]:
                raise ValidationError(f"动作 {code} 指向未知节点 {node_key}")
            node = self.case["nodes"][node_key]
            if family == "signal":
                spec = catalog.SIGNALS[ident]
                if node["op"] not in spec["applies"]:
                    raise ValidationError(
                        f"信号 {ident} 不适用于算子 {node['op']}（节点 {node_key}）"
                    )
                self._apply_signal(node_key, node, spec)
            else:
                spec = catalog.REPLACEMENTS[ident]
                if node["op"] not in spec["applies"]:
                    raise ValidationError(
                        f"替换 {ident} 不适用于算子 {node['op']}（节点 {node_key}）"
                    )
                self.overrides[node_key] = {
                    "op": spec["op"], "params": dict(spec["params"]),
                    "mask_indexes": (), "control_mask": False,
                    "fixed_branch": None, "table_const": None,
                    "replacement": True,
                }

    def _apply_signal(self, node_key, node, spec):
        kind = spec["kind"]
        base = {
            "mask_indexes": (), "control_mask": False,
            "fixed_branch": None, "table_const": None, "replacement": False,
        }
        if kind == "replace":
            self.overrides[node_key] = dict(
                base, op=spec["op"], params=dict(spec["params"]))
        elif kind == "fixed":
            self.overrides[node_key] = dict(
                base, op="fixed", params=dict(spec["params"]))
        elif kind == "input_mask":
            self.overrides[node_key] = dict(
                base, op=node["op"], params=node["params"],
                mask_indexes=(spec["index"],))
        elif kind == "control_mask":
            self.overrides[node_key] = dict(
                base, op=node["op"], params=node["params"],
                control_mask=True)
        elif kind == "fixed_branch":
            self.overrides[node_key] = dict(
                base, op=node["op"], params=node["params"],
                control_mask=True, fixed_branch=spec["branch"])
        elif kind == "table_const":
            self.overrides[node_key] = dict(
                base, op=node["op"], params=node["params"],
                table_const=spec["params"]["value"])
        else:  # 不可达
            raise ValidationError(f"信号类型 {kind} 未实现")

    def _node_spec(self, node_key):
        node = self.case["nodes"][node_key]
        ov = self.overrides.get(node_key)
        if ov is None:
            return {
                "op": node["op"], "params": node["params"],
                "mask_indexes": (), "control_mask": False,
                "fixed_branch": None, "table_const": None,
                "replacement": False,
            }
        return ov

    # ------------------------------------------------------------------
    # 单个赋值下的 DAG 求值
    # ------------------------------------------------------------------
    def _assignment_key(self, assignment):
        return tuple(
            (v, value_key(assignment[v])) for v in self.case["var_order"]
        )

    def evaluate(self, assignment):
        values = {}
        assign_key = self._assignment_key(assignment)
        for node_key in self.case["node_order"]:
            if node_key not in self.overrides:
                shared_key = (assign_key, node_key)
                cached = self._shared_eval.get(shared_key)
                if cached is not None:
                    values[node_key] = cached
                    continue
            value = self._eval_node(node_key, assignment, values)
            values[node_key] = value
            if node_key not in self.overrides:
                self._shared_eval[(assign_key, node_key)] = value
        return values

    def _eval_input(self, kind, rkey, assignment, values):
        if kind == "source":
            if rkey not in assignment:
                raise ValidationError(f"变量 {rkey} 未赋值")
            return assignment[rkey]
        return values[rkey]

    @staticmethod
    def _mask(value):
        """保留长度/结构的占位替换。"""
        if isinstance(value, list):
            return ["★" for _ in value]
        return "★"

    def _eval_node(self, node_key, assignment, values):
        node = self.case["nodes"][node_key]
        spec = self._node_spec(node_key)
        mask_set = set(spec["mask_indexes"])

        def data_at(i):
            kind, rkey = node["data_inputs"][i]
            value = self._eval_input(kind, rkey, assignment, values)
            if i in mask_set:
                return self._mask(value)
            if -1 in mask_set and i == len(node["data_inputs"]) - 1:
                return self._mask(value)
            return value

        data_values = [data_at(i) for i in range(len(node["data_inputs"]))]
        control_values = [
            self._eval_input(kind, rkey, assignment, values)
            for kind, rkey in node["control_inputs"]
        ]

        op, params = spec["op"], spec["params"]
        if spec["fixed_branch"] is not None:
            return data_values[spec["fixed_branch"]]
        if spec["control_mask"] and op == "mux":
            first_when = params["branches"][0]["when"]
            return apply(op, data_values, [first_when], params)
        if spec["table_const"] is not None:
            return spec["table_const"]
        return apply(op, data_values, control_values, params)

    # ------------------------------------------------------------------
    # 标签流入
    # ------------------------------------------------------------------
    def _incoming_labels(self, node_key):
        node = self.case["nodes"][node_key]
        data_labels, control_labels = set(), set()
        for kind, rkey in node["data_inputs"]:
            if kind == "source":
                lab = self.case["variables"][rkey]["label"]
                if self.case["label_kind"][lab] == "control":
                    control_labels.add(lab)
                else:
                    data_labels.add(lab)
            else:
                data_labels |= self.labels[rkey]["data"]
                control_labels |= self.labels[rkey]["control"]
        for kind, rkey in node["control_inputs"]:
            if kind == "source":
                control_labels.add(self.case["variables"][rkey]["label"])
            else:
                control_labels |= self.labels[rkey]["control"]
                # 控制流上节点的数据标签经 mux 分支选择也可泄漏
                if node["op"] == "mux":
                    data_labels |= self.labels[rkey]["data"]
        return data_labels, control_labels

    # ------------------------------------------------------------------
    # 硬ening 的结构性切断（不依赖 NI）
    # ------------------------------------------------------------------
    def _structural_drops(self, node_key, data_labels, control_labels):
        ov = self.overrides.get(node_key)
        if ov is None:
            return set(), set()
        drop_data, drop_control = set(), set()

        if ov["table_const"] is not None or ov["op"] == "fixed":
            drop_data |= set(data_labels)
        if ov["op"] == "mask_star":
            drop_data |= set(data_labels)
        if ov["fixed_branch"] is not None:
            kept = self._branch_labels(node_key, ov["fixed_branch"])
            drop_data |= set(data_labels) - kept
        if ov["mask_indexes"]:
            drop_data |= self._masked_input_cuts(node_key, data_labels)
        if ov["control_mask"]:
            node = self.case["nodes"][node_key]
            for kind, rkey in node["control_inputs"]:
                if kind == "source":
                    drop_control.add(self.case["variables"][rkey]["label"])
                else:
                    drop_control |= self.labels[rkey]["control"]
        return drop_data, drop_control

    def _masked_input_cuts(self, node_key, data_labels):
        node = self.case["nodes"][node_key]
        ov = self.overrides[node_key]
        indexes = set(ov["mask_indexes"])
        if -1 in indexes:
            indexes.discard(-1)
            indexes.add(len(node["data_inputs"]) - 1)
        return {
            lab for lab in data_labels
            if self._all_inputs_of_label_masked(node, lab, indexes)
        }

    def _all_inputs_of_label_masked(self, node, lab, indexes):
        found = False
        for i, (kind, rkey) in enumerate(node["data_inputs"]):
            if kind == "source":
                in_labs = {self.case["variables"][rkey]["label"]}
            else:
                in_labs = set(self.labels[rkey]["data"])
            if lab in in_labs:
                found = True
                if i not in indexes:
                    return False
        return found

    def _branch_labels(self, node_key, branch_index):
        node = self.case["nodes"][node_key]
        kind, rkey = node["data_inputs"][branch_index]
        if kind == "source":
            lab = self.case["variables"][rkey]["label"]
            return {lab} if self.case["label_kind"][lab] == "data" else set()
        return set(self.labels[rkey]["data"])

    # ------------------------------------------------------------------
    # 静态标签传播
    # ------------------------------------------------------------------
    def _propagate_labels(self):
        labels = {}
        self.labels = labels
        for node_key in self.case["node_order"]:
            node = self.case["nodes"][node_key]
            data_labels, control_labels = self._incoming_labels(node_key)
            ov = self.overrides.get(node_key)
            drop_data, drop_control = self._structural_drops(
                node_key, data_labels, control_labels
            )
            spec = self._node_spec(node_key)

            # 非干扰 + 白名单去数据标签（替换算子必须重新通过 NI）
            can_summarize = node["approved_summary"] or (
                ov is not None and ov.get("replacement")
                and spec["op"] in APPROVED_SUMMARIES
            )
            whitelist = self._whitelist(node_key)
            for lab in list(data_labels):
                if lab in drop_data:
                    continue
                if (can_summarize and lab in whitelist
                        and self._is_invariant(node_key, lab)):
                    drop_data.add(lab)

            # 控制标签：概要函数永远不能去除；只接受结构切断
            labels[node_key] = {
                "data": data_labels - drop_data,
                "control": control_labels - drop_control,
                "dropped_data": set(drop_data),
                "dropped_control": set(drop_control),
            }
        return labels

    def _whitelist(self, node_key):
        if self.policy is None:
            return set()
        return set(self.policy["whitelist"].get(node_key, ()))

    # ------------------------------------------------------------------
    # 非干扰：固定其他源变量、变化 label 对应变量时输出是否一致
    # ------------------------------------------------------------------
    def _label_variables(self, lab):
        return [
            v for v in self.case["var_order"]
            if self.case["variables"][v]["label"] == lab
        ]

    def _context_and_output(self, assignment, node_key, label_vars):
        ctx = tuple(
            (v, value_key(assignment[v]))
            for v in self.case["var_order"] if v not in label_vars
        )
        out_key = value_key(self.evaluate(assignment)[node_key])
        return ctx, out_key

    def _is_invariant(self, node_key, label):
        return self.ni_check(node_key, label)[0]

    def ni_check(self, node_key, label):
        """返回 (是否非干扰, 见证赋值对或 None)。

        见证对：固定其他源变量、仅 label 变量不同、节点输出不同，
        且两个赋值都满足全部约束。按规范序取字典序最小的一对。
        结果按 (节点, 标签) 记忆化。
        """
        cache_key = (node_key, label)
        if cache_key in self._ni_cache:
            return self._ni_cache[cache_key]
        label_vars = set(self._label_variables(label))
        seen = {}
        result = None
        for assignment in self.solutions:
            ctx, out_key = self._context_and_output(
                assignment, node_key, label_vars
            )
            if ctx not in seen:
                seen[ctx] = (out_key, assignment)
            elif seen[ctx][0] != out_key:
                result = (False, (seen[ctx][1], assignment))
                break
        if result is None:
            result = (True, None)
        self._ni_cache[cache_key] = result
        return result

    def output_families(self, node_key):
        """报告摘要族：全部可行赋值 -> 输出抽象值的规范键。"""
        families = []
        for assignment in self.solutions:
            values = self.evaluate(assignment)
            families.append({
                "assignment": dict(assignment),
                "output_key": value_key(values[node_key]),
            })
        return families

    # ------------------------------------------------------------------
    # 最短敏感作用链：报告节点反向 BFS 到带 label 的来源
    # ------------------------------------------------------------------
    def sensitive_chain(self, node_key, label):
        queue = deque([(node_key, [node_key])])
        seen = {node_key}
        while queue:
            cur, path = queue.popleft()
            node = self.case["nodes"][cur]
            edges = list(node["data_inputs"]) + list(node["control_inputs"])
            for kind, rkey in sorted(edges, key=lambda e: e[1]):
                if kind == "source":
                    if self.case["variables"][rkey]["label"] == label:
                        return path + [f"src:{rkey}"]
                elif rkey not in seen:
                    seen.add(rkey)
                    queue.append((rkey, path + [rkey]))
        return None

    def report_status(self, report, label):
        """对单个报告执行 prove 检查。

        判定以传播后仍残留的标签集为准：标签被合法去除（白名单 + 已批准
        概要 + 全部可行赋值下非干扰）后才不残留。任何残留都判泄漏，
        数据/控制标签使用不同的违规模式。
        """
        node_key = report["node_key"]
        node_labels = self.labels[node_key]
        kind = self.case["label_kind"][label]
        invariant, witness = self.ni_check(node_key, label)
        present = label in (
            node_labels["data"] if kind == "data" else node_labels["control"]
        )
        if not present:
            return {
                "leak": False,
                "mode": "invariant" if invariant else "label_absent",
                "witness": None, "present": present, "invariant": invariant,
            }
        if kind == "control":
            # 控制标签：概要函数永远不能去除，残留即违规
            return {
                "leak": True, "mode": "control_label_residual",
                "witness": None, "present": present, "invariant": invariant,
            }
        # 数据标签残留：区分是 NI 失败还是仅缺白名单/概要资格
        mode = ("non_interference_failure" if not invariant
                else "declassification_not_authorized")
        return {
            "leak": True, "mode": mode,
            "witness": witness, "present": present, "invariant": invariant,
        }

