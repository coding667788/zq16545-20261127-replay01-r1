---
name: labelreplay-project
description: labelreplay 标签传播隔离复核工具的项目结构与运行约束
metadata:
  type: project
---

labelreplay 是在 `D:\Zhongqiang-...\zq16545-20261127-replay01-r1-work\labelreplay`
从空仓库实现的合成文档标签传播隔离策略复核工具（纯 Python 3.12 标准库、离线、UTF-8 JSON CLI）。

关键约束与决策：
- 该 Python 构建在 `python -I`（隔离模式）下**不会**把脚本目录/cwd 加入 `sys.path`，
  所以 `lr.py` 顶部需显式 `sys.path.insert(0, 脚本目录)`；测试用 `run_tests.py` 同样显式加根目录。
- 数据标签去标签需同时满足「白名单 + 已批准概要 + 全部可行赋值下非干扰」；
  控制标签概要函数永远不能去除（残留即 control_label_residual）。
- amend 决胜顺序是「总损失 → 规模 → 动作码字典序」（损失优先，非规模优先）；
  靠共享求值缓存 + NI 记忆化 + 可行性缓存把搜索压到秒级。
- list 型来源的 symbols 每个元素就是一个完整文档值（2-4 个），不再做笛卡尔积。
- 运行：`python -I lr.py ...`；测试：`python -I run_tests.py`（49 个用例，约 34 秒）。
- PowerShell 5.1 的 Remove-Item 在该环境偶发 "Access to D:\" 错误，删除文件改用
  `[System.IO.File]::Delete(绝对路径)`。
