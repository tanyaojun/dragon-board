"""RankTrend 分析包：golden 引擎与观察/回测辅助。

兼容入口：旧代码 `from backend.analysis.ranktrend import ...` 在本包经 `import *`
re-export `engine` 全部公开符号（含 analyze_technical/analyze_risk 等，供测试 monkeypatch）。
"""

from backend.analysis.ranktrend.engine import *  # noqa: F401,F403
