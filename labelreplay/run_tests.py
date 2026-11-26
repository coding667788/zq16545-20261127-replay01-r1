#!/usr/bin/env python3
"""离线测试运行器：显式加入项目根后以 unittest 发现全部测试。

用法（在项目根目录）：
    python -I run_tests.py
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=os.path.join(ROOT, "tests"), pattern="test_*.py"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
