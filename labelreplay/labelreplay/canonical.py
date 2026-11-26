"""规范化 JSON 与指纹。

规范化规则：键排序、无空白、保留 Unicode、不转义非 ASCII。
指纹 = 规范化字节的 SHA-256，用于重放时检测夹具或见证被篡改。
"""

import hashlib
import json


def _default(obj):
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=lambda x: canonical_dumps(x))
    raise TypeError(f"无法规范化类型 {type(obj).__name__}")


def canonical_dumps(obj):
    """返回规范化 JSON 字符串（确定性行为，与键顺序无关）。"""
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False, default=_default,
    )


def fingerprint(obj):
    """返回规范化内容的 SHA-256 十六进制指纹。"""
    return hashlib.sha256(canonical_dumps(obj).encode("utf-8")).hexdigest()


def loads(text):
    return json.loads(text)


def dumps_pretty(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
