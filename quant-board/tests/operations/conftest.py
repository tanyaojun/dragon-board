# -*- coding: utf-8 -*-
"""operations 测试隔离（评审 I-3）：真凭据已在 .env.local（settings 导入即入 os.environ），
任何漏 mock 的用例不得借真实凭据发起真实登录/采集——默认清空，需要的用例在用例内显式 setenv。
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_jiuyan_credentials(monkeypatch):
    for key in ("JIUYAN_PHONE", "JIUYAN_PASSWORD", "JIUYAN_SESSION"):
        monkeypatch.delenv(key, raising=False)
