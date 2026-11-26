#!/usr/bin/env python3
"""labelreplay 命令行入口（UTF-8 JSON，纯标准库，离线）。

子命令：
  prove      复核保护组可见报告族对某保护标签的非干扰性
  amend      求最少损失的最小可行修复计划
  enumerate  小有限域全枚举（回溯 vs 暴力交叉验证）
  replay     重放复核已产出的结果工件，检测见证/可达性/决胜篡改
"""

import argparse
import os
import sys

# -I（隔离模式）下部分 Python 构建不把脚本目录加入 sys.path，
# 显式加入以保证离线、无环境依赖地导入同目录包。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from labelreplay.canonical import canonical_dumps, dumps_pretty, loads
from labelreplay.commands import (
    amend,
    enumerate_assignments,
    prove,
    replay,
)
from labelreplay.errors import LRSError
from labelreplay.model import parse_case


def _read_json(path):
    if path is None or path == "-":
        raw = sys.stdin.buffer.read()
    else:
        with open(path, "rb") as fh:
            raw = fh.read()
    return loads(raw.decode("utf-8"))


def _write_json(obj, path):
    text = dumps_pretty(obj)
    if path is None or path == "-":
        sys.stdout.buffer.write(text.encode("utf-8"))
    else:
        with open(path, "wb") as fh:
            fh.write(text.encode("utf-8"))


def _load_case(path):
    return parse_case(_read_json(path))


def build_parser():
    parser = argparse.ArgumentParser(
        prog="lr", description="合成文档批处理标签传播隔离策略复核工具"
    )
    parser.add_argument("--case", required=True, help="case JSON 路径（- 为 stdin）")
    parser.add_argument("--out", default="-", help="输出 JSON 路径（默认 stdout）")
    parser.add_argument(
        "--max-list-len", type=int, default=3,
        help="list 型来源枚举的最大序列长度（默认 3）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_prove = sub.add_parser("prove", help="非干扰复核")
    p_prove.add_argument("--group", required=True)
    p_prove.add_argument("--label", required=True)
    p_prove.add_argument("--window", default=None, help="只复核指定策略窗口")

    p_amend = sub.add_parser("amend", help="最少损失修复计划")
    p_amend.add_argument("--group", required=True)
    p_amend.add_argument("--label", required=True)
    p_amend.add_argument("--suppress-weight", type=int, default=12)
    p_amend.add_argument("--max-plan-size", type=int, default=4)

    sub.add_parser("enumerate", help="有限域全枚举")

    p_replay = sub.add_parser("replay", help="重放结果工件")
    p_replay.add_argument("--artifact", required=True, help="待重放的结果 JSON")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        case = _load_case(args.case)
        if args.command == "prove":
            result = prove(
                case, args.group, args.label,
                window=args.window, max_list_len=args.max_list_len,
            )
        elif args.command == "amend":
            result = amend(
                case, args.group, args.label,
                max_list_len=args.max_list_len,
                suppress_weight=args.suppress_weight,
                max_plan_size=args.max_plan_size,
            )
        elif args.command == "enumerate":
            result = enumerate_assignments(
                case, max_list_len=args.max_list_len
            )
        elif args.command == "replay":
            artifact = _read_json(args.artifact)
            result = replay(
                case, artifact, max_list_len=args.max_list_len
            )
        else:  # 不可达
            parser.error(f"未知子命令 {args.command}")
        _write_json(result, args.out)
        if args.command == "replay" and result["verdict"] != "replay_ok":
            return 3
        return 0
    except (LRSError, OSError, ValueError) as exc:
        name = type(exc).__name__
        if isinstance(exc, OSError):
            name = "InputError"
        elif isinstance(exc, ValueError) and not isinstance(exc, LRSError):
            name = "InvalidJSON"
        err = {"tool": "labelreplay", "error": name,
               "message": str(exc)}
        sys.stderr.buffer.write(
            (canonical_dumps(err) + "\n").encode("utf-8")
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
