"""unittest 公共辅助：定位夹具目录并加载 case。"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from labelreplay.model import parse_case  # noqa: E402

EXAMPLES = os.path.join(ROOT, "examples")

CASE01 = os.path.join(EXAMPLES, "case01_safe_rollback_frozen_policy.json")
CASE02 = os.path.join(EXAMPLES, "case02_leak_mutex_amend.json")


def load_case(path):
    with open(path, "rb") as fh:
        return parse_case(json.loads(fh.read().decode("utf-8")))
