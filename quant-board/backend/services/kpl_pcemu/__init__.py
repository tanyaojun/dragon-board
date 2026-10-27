# -*- coding: utf-8 -*-
"""KPL 白盒签名 PC 模拟核（unicorn x86-32 模拟 libauthSign_x86.so）。

分层：
- elf.py：ELF32 加载 + 重定位 + 导入 stub 机制
- jni.py：JNIEnv mock、libc/asset VFS、initBaxPwd/whiteBoxEncrypt/enc/dec 高层操作
- codec.py：PCEmulatorCodec（KplCollectorService codec 接口实现）

红线：pytest 不得加载真实 ELF（见 __tests__/test_kpl_pc_codec.py，全 mock）。
"""
from backend.services.kpl_pcemu.codec import PCEmulatorCodec, PCEmuError

__all__ = ["PCEmulatorCodec", "PCEmuError"]
