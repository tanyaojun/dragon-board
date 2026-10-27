# -*- coding: utf-8 -*-
"""PCEmulatorCodec 测试 —— 全 mock（红线：测试不得加载真实 ELF/触发 adb/signsvc/网络）。

覆盖：
1. 工件缺失 → PCEmuError fail-visible（初始化前置检查，不触碰 unicorn）
2. 懒初始化仅一次 + FakeCore 语义（wbe hex / enc/dec bytes / 空输出 → None）
3. native 异常 → PCEmuError 且核实例被丢弃（下次调用重建）
4. 与 SignSvcAdbCodec 接口签名对齐（双轨 duck-type 合同）
5. serve_kpl_socket KPL_CODEC 开关（pc/adb/非法值）
"""
from __future__ import annotations

import inspect
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.kpl_pcemu import PCEmulatorCodec, PCEmuError  # noqa: E402
from backend.services.kpl_collector_service import SignSvcError, SignSvcAdbCodec  # noqa: E402


class FakeCore:
    """替身模拟核：记录调用，返回可预测输出。"""

    def __init__(self):
        self.calls: list[str] = []
        self.init_bax_pwd_called = False
        self.fail_on: str | None = None

    def init_bax_pwd(self):
        self.init_bax_pwd_called = True

    def whitebox_encrypt(self, ch, dv, ct, tm):
        self.calls.append(f"wbe:{ch}")
        if self.fail_on == "wbe":
            raise RuntimeError("[pcemu] __stack_chk_fail")
        return b"\x01\x02" if ch != "EMPTY" else b""

    def encrypt(self, plain):
        self.calls.append(f"enc:{len(plain)}")
        if self.fail_on == "enc":
            raise RuntimeError("[pcemu] abort() called")
        return b"\xaa" + plain

    def decrypt(self, cipher):
        self.calls.append(f"dec:{len(cipher)}")
        if self.fail_on == "dec":
            raise RuntimeError("[pcemu] abort() called")
        return cipher[1:]


def _codec_with(tmp_path: Path, core: FakeCore) -> PCEmulatorCodec:
    codec = PCEmulatorCodec(assets_dir=str(tmp_path))
    codec._build_core = lambda: core  # mock 核心，绝不加载真实 ELF
    return codec


def test_missing_assets_fail_visible(tmp_path):
    """工件缺失必须显式报错并给出修复指引，不得静默回退/伪装。"""
    codec = PCEmulatorCodec(assets_dir=str(tmp_path / "nowhere"))
    with pytest.raises(PCEmuError) as ei:
        codec.wbe("c", "d", "99", "1")
    msg = str(ei.value)
    assert "工件缺失" in msg
    assert "extract_kpl_pcemu.py" in msg  # 修复指引
    assert "KPL_CODEC=adb" in msg  # 双轨提示


def test_pcdmu_error_is_signsvc_error():
    """PCEmuError 必须是 SignSvcError 子类（collector 610 ack 降级路径依赖）。"""
    assert issubclass(PCEmuError, SignSvcError)


def test_lazy_init_once_and_semantics(tmp_path):
    """懒初始化仅一次；wbe→hex / enc→bytes / 空输出→None。"""
    core = FakeCore()
    codec = _codec_with(tmp_path, core)
    builds = [0]
    orig = codec._build_core

    def counting_build():
        builds[0] += 1
        return orig()

    codec._build_core = counting_build

    sig = codec.wbe("a" * 32, "d" * 32, "99", "1793060000")
    assert sig == "0102"
    assert codec.enc(b"hello") == b"\xaahello"
    assert codec.dec((b"\xaahello").hex()) == b"hello"
    assert builds[0] == 1  # 多次调用只构建一次
    assert any(c.startswith("wbe:") for c in core.calls)


def test_empty_output_returns_none(tmp_path):
    """空输出按 SignSvcAdbCodec 语义返回 None（调用侧结构化上报）。"""
    core = FakeCore()
    codec = _codec_with(tmp_path, core)
    assert codec.wbe("EMPTY", "d", "99", "1") is None


def test_native_failure_raises_and_rebuilds(tmp_path):
    """native 异常 → PCEmuError，核实例被丢弃，下次调用重建。"""
    core = FakeCore()
    codec = _codec_with(tmp_path, core)
    core.fail_on = "wbe"
    with pytest.raises(PCEmuError):
        codec.wbe("c", "d", "99", "1")
    assert codec._core is None  # 已丢弃
    core.fail_on = None
    sig = codec.wbe("c", "d", "99", "1")  # 重建成功
    assert sig == "0102"


def test_codec_interface_aligned_with_adb():
    """双轨 duck-type 合同：enc/dec/wbe/close 签名与 SignSvcAdbCodec 一致。"""
    for name in ("enc", "dec", "wbe", "close"):
        a = inspect.signature(getattr(PCEmulatorCodec, name))
        b = inspect.signature(getattr(SignSvcAdbCodec, name))
        assert list(a.parameters) == list(b.parameters), name


def test_lock_serializes_calls(tmp_path):
    """uc 非线程安全：并发调用必须被互斥串行化。"""
    core = FakeCore()
    codec = _codec_with(tmp_path, core)
    inside = threading.Lock()
    counter = {"n": 0, "max": 0}

    def enc_recording(plain):
        with inside:
            counter["n"] += 1
            counter["max"] = max(counter["max"], counter["n"])
        try:
            return b"\xaa" + plain
        finally:
            with inside:
                counter["n"] -= 1

    core.encrypt = enc_recording
    threads = [threading.Thread(target=lambda i=i: codec.enc(bytes([i]) * 4))
               for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert counter["max"] == 1  # 无并发重叠


def test_serve_kpl_codec_switch(monkeypatch):
    """KPL_CODEC 开关：pc → PCEmulatorCodec，adb → SignSvcAdbCodec，非法值 fail-fast。"""
    import importlib

    import backend.serve_kpl_socket as svc

    monkeypatch.setenv("KPL_CODEC", "pc")
    m1 = importlib.reload(svc)
    assert m1._CODEC_MODE == "pc"
    assert isinstance(m1._codec, PCEmulatorCodec)

    monkeypatch.setenv("KPL_CODEC", "adb")
    m2 = importlib.reload(svc)
    assert m2._CODEC_MODE == "adb"
    assert isinstance(m2._codec, SignSvcAdbCodec)

    monkeypatch.setenv("KPL_CODEC", "bogus")
    with pytest.raises(RuntimeError):
        importlib.reload(svc)

    monkeypatch.setenv("KPL_CODEC", "pc")
    importlib.reload(svc)  # 还原默认，避免污染其它测试
