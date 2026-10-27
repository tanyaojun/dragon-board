# -*- coding: utf-8 -*-
"""PCEmulatorCodec：KPL 白盒签名 PC 模拟 codec（KplCollectorService codec 接口）。

与 SignSvcAdbCodec 接口语义对齐（duck-type 双轨）：
- enc(plain: bytes) -> Optional[bytes]     GCM 加密（失败 None / 硬错误 PCEmuError）
- dec(cipher_hex: str) -> Optional[bytes]  GCM 解密
- wbe(challenge, device_id, conn_type, cur_time) -> Optional[str]  白盒签名 hex
- close() -> None

fail-visible：缺工件 / native abort / unicorn 异常 → PCEmuError（SignSvcError 子类，
collector 的 610 ack 降级路径按 SignSvcError 捕获）。空输出按 SignSvcAdbCodec 语义
返回 None（调用侧结构化上报，不伪装成功）。

双轨切换见 serve_kpl_socket（KPL_CODEC=pc|adb）：PC codec 为主，signsvc 兜底保留。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from backend.services.kpl_collector_service import SignSvcError

log = logging.getLogger(__name__)

# 默认工件目录（本地状态，gitignored；由 scripts/extract_kpl_pcemu.py 从设备提取）
# codec.py 位于 backend/services/kpl_pcemu/ → parents[3] = quant-board/
DEFAULT_ASSETS_DIR = Path(__file__).resolve().parents[3] / "data" / "kpl_pcemu"

REQUIRED_FILES = ("libauthSign_x86.so", "assets/middle_new.bin", "signer_cert.der")


class PCEmuError(SignSvcError):
    """PC 模拟核初始化/调用失败（缺工件、native abort、unicorn 异常）。"""


class PCEmulatorCodec:
    """unicorn 模拟 libauthSign 的 codec；懒初始化 + 互斥（uc 非线程安全）。"""

    def __init__(self, assets_dir: Optional[str] = None):
        self._assets_dir = Path(assets_dir) if assets_dir else DEFAULT_ASSETS_DIR
        self._core = None
        self._lock = threading.Lock()

    # ---------- 初始化 ----------

    def _build_core(self):
        missing = [f for f in REQUIRED_FILES
                   if not (self._assets_dir / f).exists()]
        if missing:
            raise PCEmuError(
                f"PC 模拟核工件缺失: {missing}（目录 {self._assets_dir}）；"
                f"请运行 quant-board/scripts/extract_kpl_pcemu.py 从设备提取，"
                f"或设 KPL_CODEC=adb 走 signsvc 双轨"
            )
        from backend.services.kpl_pcemu.jni import WbEmu

        so = self._assets_dir / "libauthSign_x86.so"
        cert = self._assets_dir / "signer_cert.der"
        core = WbEmu(str(so), str(self._assets_dir / "assets"), str(cert))
        core.init_bax_pwd()
        return core

    def _ensure(self):
        with self._lock:
            if self._core is not None:
                return self._core
            try:
                core = self._build_core()
            except PCEmuError:
                raise
            except Exception as e:  # fail-visible：初始化失败必须显式暴露
                raise PCEmuError(f"PC 模拟核初始化失败: {e}") from e
            self._core = core
            log.info("[pcemu-codec] ready (assets=%s)", self._assets_dir)
            return self._core

    # ---------- codec 接口 ----------
    def _drop_core_locked(self) -> None:
        """native 异常后丢核重建；与 _ensure 建核同锁，避免写-写竞态丢新鲜核。"""
        with self._lock:
            self._core = None

    def enc(self, plain: bytes) -> Optional[bytes]:
        try:
            core = self._ensure()
            with self._lock:
                out = core.encrypt(plain)
        except PCEmuError:
            raise
        except Exception as e:
            # native abort / unicorn fault → 核状态不可信，丢弃实例（下次调用重建）
            self._drop_core_locked()
            raise PCEmuError(f"PC enc 失败: {e}") from e
        return out if out else None

    def dec(self, cipher_hex: str) -> Optional[bytes]:
        try:
            raw = bytes.fromhex(cipher_hex)
        except ValueError as e:
            # 非法 hex 是调用侧契约错误，不是 native 故障：不丢弃健康模拟核
            raise PCEmuError(f"PC dec 非法 hex 输入: {e}") from e
        try:
            core = self._ensure()
            with self._lock:
                out = core.decrypt(raw)
        except PCEmuError:
            raise
        except Exception as e:
            self._drop_core_locked()
            raise PCEmuError(f"PC dec 失败: {e}") from e
        return out if out else None

    def wbe(self, challenge: str, device_id: str, conn_type: str, cur_time: str) -> Optional[str]:
        try:
            core = self._ensure()
            with self._lock:
                out = core.whitebox_encrypt(challenge, device_id, conn_type, cur_time)
        except PCEmuError:
            raise
        except Exception as e:
            self._drop_core_locked()
            raise PCEmuError(f"PC wbe 失败: {e}") from e
        return out.hex() if out else None

    def close(self) -> None:
        with self._lock:
            self._core = None
