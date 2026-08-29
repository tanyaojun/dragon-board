"""RankTrend 兼容入口。

生产实现位于 :mod:`backend.analysis.ranktrend.engine.runtime`；保留本模块
是为了兼容历史调用方从 ``ranktrend.engine`` 导入公开符号。
"""

from .engine.config import RankTrendConfig, _validate_tier_constraints
from .engine.primitives import *  # noqa: F401,F403
from .engine.runtime import *  # noqa: F401,F403
from .trend.technical import *  # noqa: F401,F403
from .trend.lifecycle import *  # noqa: F401,F403
from .trend.risk import *  # noqa: F401,F403

__all__ = [name for name in globals() if not name.startswith("__")]
