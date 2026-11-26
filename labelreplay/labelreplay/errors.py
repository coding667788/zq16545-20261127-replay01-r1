"""统一异常类型。"""


class LRSError(Exception):
    """labelreplay 所有可预期错误的基类。"""


class ValidationError(LRSError):
    """输入夹具不符合 schema 或内部一致性要求。"""


class ReplayError(LRSError):
    """重放复核时发现结果工件与重新计算不一致（见证/可达性/决胜被篡改）。"""
