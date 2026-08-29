"""RankTrend 生产引擎实现包。

``ranktrend.engine`` 历史上是一个单文件模块，外部代码直接从中导入
技术指标、风险分析和基础工具。目录化后继续从本入口 re-export 这些公开
符号，避免迁移期间出现隐蔽的导入断裂。
"""

from .config import RankTrendConfig, _validate_tier_constraints
from .primitives import *  # noqa: F401,F403
from .runtime import *  # noqa: F401,F403
from ..trend.technical import *  # noqa: F401,F403
from ..trend.lifecycle import *  # noqa: F401,F403
from ..trend.risk import *  # noqa: F401,F403

# ``import *`` 遵循 Python 规则会跳过下划线开头的符号，但历史 API 对少量
# 私有辅助函数也有直接依赖（例如 ``_resonance_label``、``_confirm_jump``）。
# 将实现模块中的非双下划线成员完整投影到兼容入口。
from . import primitives as _primitives
from . import runtime as _runtime
from ..trend import technical as _technical
from ..trend import lifecycle as _lifecycle
from ..trend import risk as _risk

for _source in (_primitives, _runtime, _technical, _lifecycle, _risk):
    globals().update({name: value for name, value in vars(_source).items() if not name.startswith("__")})

__all__ = [name for name in globals() if not name.startswith("__")]
