# labelreplay

合成文档批处理的**标签传播隔离策略复核工具**。在一个只含虚构符号的有限域上，
重放“文件节点 → 信息摘要/报告”的处理 DAG，验证标签传播是否符合隔离策略，
并对已产出的结果工件做可重放的防篡改复核。

* 纯 Python 3.12 标准库，**完全离线**，无第三方依赖。
* 全部输入/输出为 **UTF-8 JSON**，确定性序列化（键排序、无空白）+ SHA-256 指纹。
* Windows 普通 CPU 可运行；推荐始终用隔离模式 `python -I`。

---

## 1. 快速开始

```powershell
# 有限域全枚举（回溯求解器与暴力全枚举交叉验证）
python -I lr.py --case examples\case02_leak_mutex_amend.json enumerate

# prove：复核保护组 G_AUDIT 的报告族对标签 L_REC 是否非干扰
python -I lr.py --case examples\case02_leak_mutex_amend.json prove `
    --group G_AUDIT --label L_REC

# amend：求最少损失的最小可行修复计划
python -I lr.py --case examples\case02_leak_mutex_amend.json amend `
    --group G_AUDIT --label L_REC

# replay：重放已产出的结果工件，检测见证/可达性/决胜篡改
python -I lr.py --case examples\case02_leak_mutex_amend.json replay `
    --artifact result.json
```

运行单元测试：

```powershell
python -I run_tests.py
```

退出码：`0` 成功；`2` 输入/校验错误（错误信息走 stderr 的 JSON）；
`3` replay 检出篡改。

---

## 2. 隔离策略与标签规则

每个节点是一个文件，取值只保留**长度、分桶、计数、占位**等信息摘要，
或是给特定保护组阅读的报告。节点可同时依赖数据来源、控制条件，以及
**同一节点的回滚旧版本输出**（按普通依赖边处理）。

### 2.1 数据标签（`label_kind: "data"`）

沿数据依赖并集传播。一个带**已批准概要函数**（`approved_summary: true`）
的节点，只有在下面两个条件**同时**成立时，才能去除某个数据标签：

1. 该标签位于当前冻结策略窗口的节点**白名单**内；
2. 节点输出抽象值在**全部可行合成赋值**下，对该标签对应的来源变量变化保持
   一致（非干扰，NI）——即固定其他来源变量、只变化该标签的变量时输出不变。

任一条件不满足，标签都会残留在输出上，`prove` 判泄漏。
特别地：**白名单不是充分条件**——窄分桶/长度若随敏感来源变化，即使在
白名单内也不能去标签（见实例二的 `n4`）。

### 2.2 控制标签（`label_kind: "control"`）—— 不同规则

控制标签沿控制依赖传播，并可经 `mux` 的数据分支继续泄漏。
**概要函数永远不能去除控制标签**；即使输出对控制变量非干扰，残留的控制标签
仍判泄漏（模式 `control_label_residual`）。控制标签只能由固定分支、
控制信号屏蔽等结构性动作切断。

### 2.3 冻结策略与版本窗口

策略按 `policies[].window` 冻结。报告在其归档窗口下复核；
某个窗口可以**撤销白名单**，但旧报告仍按归档当时的窗口重放
（见实例一：`w2` 撤销 `n1@v2` 白名单，`w1` 的旧报告 `r1` 仍安全）。

---

## 3. 输入夹具格式（JSON Schema 要点）

根对象字段：

| 字段 | 说明 |
|---|---|
| `schema_version` | 固定 `"1.0"` |
| `case_id` / `description` | 标识与说明 |
| `sources[]` | 来源变量；每个来源可有多个版本 |
| `constraints[]` | 有限域联立约束 |
| `nodes[]` | 处理节点（DAG），支持同 id 多版本 |
| `policies[]` | 按窗口冻结的白名单策略 |
| `reports[]` | 给保护组阅读的报告，绑定节点与窗口 |
| `observe[]` | amend 必须保留其业务区分能力的观察点 |

### 3.1 sources

```json
{
  "id": "D1",
  "label": "L_REC",
  "label_kind": "data",
  "kind": "list",
  "versions": [
    {"version": "v1", "symbols": [["p"], ["p","q"], ["q","r"], ["p","q","r"]]}
  ]
}
```

* 每个版本的有限域必须是 **2–4 个符号**。
* `kind: "scalar"` 时每个符号是完整标量取值；`kind: "list"` 时每个符号
  本身是一个完整文档（列表）值，不再二次组合。
* `label_kind` 为 `data` 或 `control`；同名标签在所有来源上必须种类一致。

### 3.2 constraints

| 类型 | 形式 | 语义 |
|---|---|---|
| `all_equal` | `vars` | 所有变量取值相等 |
| `all_different` | `vars` | 所有变量取值互异 |
| `allowed` / `forbidden` | `var`, `values` | 单变量允许/禁止集合 |
| `implies` | `if_var`,`if_in` → `then_var`,`then_in` | 条件蕴含 |
| `tuple_in` | `vars`, `tuples` | 变量组合必须落在元组集合内（用于互斥分支） |

`tuple_in` 可表达“两个分支各自看似可达、但不能同时出现”的联立关系，
例如 `(C1,D2) ∈ {(A,p),(A,q),(B,r)}`：分支 A 与分支 B 各自可达，
但 `(A,r)`、`(B,p)` 等混合状态不可达。

### 3.3 引用（ref）

简写字符串 `"D1@v1"`（来源版本）或 `"n1@v2"`（节点版本）；
也支持对象 `{"source":"D1","version":"v1"}` / `{"node":"n1","version":"v2"}`。
依赖图必须是 DAG，环会被拒绝。

### 3.4 nodes

```json
{
  "id": "n5",
  "op": "bucket",
  "approved_summary": true,
  "declass": ["L_REC"],
  "params": {"width": 4},
  "data_inputs": ["D1@v1"],
  "control_inputs": []
}
```

内置算子（只处理虚构抽象值）：

| 算子 | 数据元数 | 说明 | 已批准概要 |
|---|---|---|---|
| `len` | 1 | 长度（标量长度记 1） | 是 |
| `bucket` | 1 | 长度分桶 `B[lo,hi]`，参数 `width` | 是 |
| `count_distinct` | n | 去重计数 | 是 |
| `sum_sizes` | n | 长度之和 | 是 |
| `hash_prefix` | 1 | 确定性伪指纹截断（默认单射，不去标签） | 是* |
| `pair` | 2 | 有序对 | 否 |
| `concat` | n | 序列拼接 | 否 |
| `mux` | n + 1 控制 | 按控制值选分支，参数 `branches` | 否 |
| `table_lookup` | 1 | 有限映射表 | 否 |
| `eq` | 2 | 相等判定 | 否 |
| `mask_star` | 1 | 占位替换，保留长度/结构 | 否 |
| `fixed` | 任意 | 常量（参数 `value`），忽略数据输入 | 否 |

\* `hash_prefix` 虽登记为已批准概要，但其输出对输入敏感，NI 检查会阻止它
在非恒定场景去标签。

### 3.5 policies / reports / observe

```json
"policies": [
  {"window": "w1", "whitelist": {"n5@v1": ["L_REC"]}, "note": "..."}
],
"reports": [
  {"id": "r1", "node": "n3@v1", "group": "G_AUDIT", "window": "w1"}
],
"observe": [
  {"id": "o1", "node": "n4@v1", "distinguish_on": ["D1@v1"]}
]
```

`observe` 要求：固定 `distinguish_on` 之外的来源变量时，观察点节点的输出
仍能区分这些变量的不同取值（每个上下文至少两个不同输出）。

---

## 4. 命令与输出

### 4.1 prove

求给定保护组能看到的所有报告摘要族，在保护标签对应来源变量变化、
其他来源变量固定时是否保持一致。

* `verdict: "safe"`：给出可重放的安全证明（逐报告标签残留、NI、摘要族指纹）。
* `verdict: "leak"`：给出
  - 最短敏感作用链 `shortest_sensitive_chain`（报告节点反向 BFS 到带标签来源）；
  - 两组满足全部约束的合成赋值 `witness_pair`（固定其他变量、仅标签变量不同）；
  - 违规模式 `non_interference_failure` / `declassification_not_authorized`
    / `control_label_residual`。

### 4.2 amend

从 **16 个已许可屏蔽控制信号 M01–M16**、4 个替换摘要算子 R1–R4、
以及报告禁出动作 `S:<报告id>` 中选计划。

* 同一节点至多施加一个非禁出动作（互斥覆盖）。
* 可行性：所有未禁出报告对目标标签不再泄漏，且全部观察点保留业务区分能力。
* 决胜顺序（确定性、可重放）：**总损失升序 → 计划规模升序 → 动作码元组字典序**。
* 采用可行性记忆化 + 跨引擎共享求值缓存 + 分支限界，普通 CPU 秒级返回。

信号与替换算子目录见 `labelreplay/catalog.py`，每个动作带显式损失权重。

### 4.3 enumerate

小有限域全枚举。`backtrack`（增量剪枝回溯）与 `brute_force`（笛卡尔积 +
完整约束过滤）两条独立实现的结果必须逐赋值一致，否则报内部错误。

### 4.4 replay

对 `prove` / `amend` / `enumerate` 的结果工件重放：

1. 先比对 `case_fingerprint`（夹具被改 → 直接 `ReplayError`）；
2. 重新计算并逐字段比对；
3. 任何见证、互斥分支可达性、替代计划决胜顺序的篡改都会产生字段级
   `mismatches`，输出 `verdict: "tampered"`，CLI 退出码 3。

---

## 5. 两项手算实例

### 实例一 `case01_safe_rollback_frozen_policy.json`
（安全概要 + 回滚版本 + 冻结窗口撤销白名单）

* 来源 `D1` 有 `v1/v2` 两版本，各 4 个**等长（长度 3）**虚构文档；
  节点 `n1@v1`、`n1@v2` 是已批准 `len` 概要。
* 因所有文档等长，`len ≡ 3`，输出对 `L_DOC` 非干扰；在 `w1` 白名单下，
  `n1@v1`/`n1@v2` 都合法去除 `L_DOC`。
* 节点 `n6@v1 = pair(n1@v2, n1@v1)` 同时**回滚依赖旧版本 `n1@v1`**。
* 窗口 `w2` 撤销 `n1@v2` 白名单：
  - 旧报告 `r1`（归档于 `w1`）重放仍 **safe**；
  - 新报告 `r2`（`w2`）上 `L_DOC` 重新残留，模式
    `declassification_not_authorized`。
* 控制来源 `C1` 与数据来源 `D2` 用 `implies` 联立；`mux` 节点 `n4`
  携带的控制标签 `L_CTL` 不被概要去除。

手算可行赋值数：总组合 `D1(v1) 4 × D1(v2) 4 × D2 3 × C1 2 = 96`；
蕴含约束在 `C1=on` 时排除 `D2=z`（减去 `4×4×1=16`），故可行赋值
`96 − 16 = 80`（其中 `C1=on` 32 个、`C1=off` 48 个），与 `enumerate` 一致。

### 实例二 `case02_leak_mutex_amend.json`
（泄漏 + 互斥分支 + 控制标签不同规则 + amend 决胜）

* `D1` 为 4 个长度 1/2/2/3 的文档；`D2` 标量；`C1∈{A,B}` 为控制来源。
* 约束 `(C1,D2) ∈ {(A,p),(A,q),(B,r)}` 构造互斥分支：
  守卫节点 `gA/gB` 使 `n7 = pair(gA,gB)` 只取 `(true,false)` 或
  `(false,true)`，`(true,true)` 不可达。
* `n4 = bucket(width=2)` 随长度变化（`B[0,1]`/`B[2,3]`），虽在白名单，
  NI 失败，**保留 `L_REC`**；`n5 = bucket(width=4)` 对四个文档恒定为
  `B[0,3]`，NI 成立，**合法去标签**——形成直接对照。
* 报告 `r1`（节点 `n3`）经 `n3→n1→D1` 最短敏感链泄漏 `L_REC`，
  `prove` 返回见证对；报告 `r2`（`nA` 这个 mux）残留控制标签 `L_SW`，
  即使 NI 成立也判 `control_label_residual`。
* 手算可行赋值数：`D1 4 × (C1,D2) 3 组合 = 12`。
* `amend`：禁出 `S:r1` 单动作损失 12；信号 `M05@n3@v1`（屏蔽 n3 第二输入，
  损失 3）+ 替换 `R3@nA@v1`（mux→常量，损失 5）合计 8，且不破坏观察点
  `o1`（n4 的长度区分）。按“损失优先”决胜，最终选择 2 动作、总损失 8 的计划。

### 综合夹具 `case03_full_catalog_coverage.json`

覆盖 `concat`、`eq`、`hash_prefix`、`count_distinct`、`mux`、`table_lookup`
等算子，使 **16 个已许可信号 M01–M16 与 4 个替换算子 R1–R4 全部能在某个节点上
实际选用**，由 `tests/test_full_catalog.py` 逐一构造引擎验证不产生运行时错误。
其约束同样是 `(C1,D2)` 三元组联立，可行赋值 12 个。

---

## 6. 目录结构

```
labelreplay/
  lr.py                     # UTF-8 JSON CLI 入口
  run_tests.py              # 离线 unittest 运行器
  README.md
  labelreplay/
    canonical.py            # 规范化 JSON + SHA-256 指纹
    model.py                # 夹具解析/校验/DAG 拓扑
    solver.py               # 回溯 + 暴力全枚举（交叉验证）
    operators.py            # 抽象算子注册表
    catalog.py              # 16 信号 + 4 替换 + 禁出动作目录
    engine.py               # 求值、标签传播、NI、敏感链
    commands.py             # prove / amend / enumerate / replay
    errors.py
  examples/                 # 三项夹具：两项手算实例 + 全目录覆盖综合夹具
  tests/                    # unittest（含三类篡改验收）
```

## 7. 安全与离线说明

* 所有数据均为虚构符号；算子不接触任何真实文档内容。
* 不发起任何网络/子进程（测试中的 CLI 调用仅在本机启动同解释器）。
* 建议用 `python -I` 运行，隔离 `sys.path` 与环境变量，避免不可信目录中的
  同名模块（如 `json.py`）被导入。
