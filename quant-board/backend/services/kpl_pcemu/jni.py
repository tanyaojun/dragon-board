# -*- coding: utf-8 -*-
"""libauthSign 白盒模拟：JNIEnv mock + libc/asset VFS + 高层密码操作。

移植自 .tmp_review/wbx_step3.py（差分已验证：WBE 4/4 组、ENC/DEC 9/9 项与设备
signsvc ground truth 逐字节一致，见 .tmp_review/wbx_step6.py / wbx_step8_encdec_diff.py）。

关键修正（勿回退）：canonical JNI 槽位以 JDK jni.h 为准——
ReleaseByteArrayElements=192(0x300)、GetByteArrayRegion=200(0x320)、
SetByteArrayRegion=208(0x340)。曾错标 190/197/205 导致输出全零。
__memmove_chk 等 *_chk 导入必须保留真实实现（缺失即静默不拷贝，fail-visible 违规）。
"""
from __future__ import annotations

import logging
import os
import struct
import time

from unicorn import UC_HOOK_CODE, UC_HOOK_INSN, UcError
from unicorn.x86_const import (
    UC_X86_INS_CPUID, UC_X86_REG_EAX, UC_X86_REG_EBP,
    UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESP,
)

from backend.services.kpl_pcemu.elf import BASE, HEAP, STACK, Emu

log = logging.getLogger(__name__)

ENV_TABLE = 0x47000000      # JNIEnv 函数表（240 槽 × 4B）
ENV_PTR = 0x47000F80        # *env → 表指针单元格（JNI 二级指针约定）
STUB_REGION = 0x46000000    # JNI 槽函数 stub 页

# 白盒/加密门位（镜像内 .data 状态字节；设备上由启动链置位，PC 端显式置位）：
# - WBE 签名校验检查函数读 [BASE+0x38597C]，非零 → 开头早退 al=1（等价 libpatch 语义）
# - encode/decodeAESGCMMsg 入口检查（0x34b210）读 [BASE+0x38597D]，非零 → 快路径 al=1
GATE_WBE_CHECK = 0x38597C
GATE_ENC_DEC = 0x38597D

# 导出地址（libauthSign_x86.so dynsym 实测）
ADDR_INIT_BAX_PWD = 0x347c10
ADDR_WBE = 0x3483c0
ADDR_ENC = 0x34af20
ADDR_DEC = 0x34b710

# JNI 函数表槽位（canonical 32-bit jni.h 索引，与 binary 实测偏移逐一对齐）
JNI = {
    "FindClass": 6, "ExceptionOccurred": 15, "ExceptionClear": 17,
    "GetObjectClass": 31, "GetMethodID": 33,
    "GetFieldID": 94, "GetObjectField": 95,
    "GetStaticMethodID": 113,
    "CallObjectMethod": 34, "CallObjectMethodV": 35, "CallBooleanMethod": 37,
    "CallStaticObjectMethod": 114, "CallStaticObjectMethodV": 115,
    "GetStaticFieldID": 144, "GetStaticObjectField": 145, "GetStaticIntField": 150,
    "NewStringUTF": 167, "GetStringUTFLength": 168, "GetStringUTFChars": 169,
    "ReleaseStringUTFChars": 170,
    "GetArrayLength": 171,
    "NewObjectArray": 172, "GetObjectArrayElement": 173, "SetObjectArrayElement": 174,
    "NewByteArray": 176,
    "GetByteArrayElements": 184, "ReleaseByteArrayElements": 192,
    "GetByteArrayRegion": 200, "SetByteArrayRegion": 208,
    "RegisterNatives": 215,
}


class WbEmu(Emu):
    """libauthSign_x86.so 模拟器（含 initBaxPwd / whiteBoxEncrypt / enc / dec）。"""

    def __init__(self, so_path: str, assets_dir: str, cert_path: str,
                 package_name: str = "com.aiyu.kaipanla"):
        self._assets_dir = assets_dir
        self._cert_path = cert_path
        self._package_name = package_name
        super().__init__(so_path)
        self.uc.mem_map(ENV_TABLE, 0x1000)
        self.uc.mem_map(STUB_REGION, 0x10000)
        self._jni_stub_n = 0
        self.jni_slot_addr = {}
        self.jni_addr_name = {}
        self.static_vals = {}
        self.classes = {}
        self.fields = {}
        self._class_n = 0x31000
        self._fid_n = 0xF0000
        self.java_strs = {}
        self.byte_arrays = {}
        self.byte_array_backing = {}
        self._next_jref = 0x20000
        self.tls_slots = {}
        self.alloc_sizes = {}
        self._block_caps: dict[int, int] = {}   # addr -> rounded 容量（复用不降级）
        self._free_set: set[int] = set()        # 已释放可复用地址集
        self.brk = HEAP + 0x1000
        self.CONTEXT_REF = 0x500
        self.FAKE_AM = 0x39000
        self.PM_REF = 0x600
        self.PI_REF = 0x700
        self.SIGNATURES_REF = 0x710
        self.SIGNATURE_REF = 0x720
        self.import_handlers = {}

        self.static_vals[("com/yzj/kaipanh/common/Config", "channelID")] = "129"
        self.static_vals[("com/yzj/kaipanh/common/Config", "versionName")] = "6.3.20.2"
        self.static_vals[("com/yzj/kaipanh/volley/ApiConfig", "apiVersion")] = "w48"
        # 真实签名证书 DER（APK META-INF/*.RSA 提取）
        self.byte_arrays[self.SIGNATURE_REF] = bytearray(open(cert_path, "rb").read())
        # GC 豁免：常驻字节数组（SIGNATURE_REF + 运行期 toByteArray 创建的 DER，见下）
        self._persistent_arrays = {self.SIGNATURE_REF}

        # bionic 栈保护：NULL 页映射（gs 基址 0 → canary 槽 0x14 原生可读写）
        self.uc.mem_map(0, 0x1000)
        self.uc.mem_write(0x14, struct.pack("<I", 0xDEADBEEF))

        # 门位置位（等价 libpatch 语义，避开 mid-function ret 破坏栈）
        self.set_gate(GATE_WBE_CHECK, b"\x01")
        self.set_gate(GATE_ENC_DEC, b"\x01")

        self._build_env_table()
        self._init_asset_vfs()
        self._init_file_vfs()
        self._hook_cpuid()

    # ---------- cpuid ----------
    def _hook_cpuid(self):
        def on_cpuid(uc, ud):
            leaf = uc.reg_read(UC_X86_REG_EAX)
            if leaf == 0:
                uc.reg_write(UC_X86_REG_EAX, 1)
                uc.reg_write(UC_X86_REG_EBX, 0x756E6547)
                uc.reg_write(UC_X86_REG_ECX, 0x6C65746E)
                uc.reg_write(UC_X86_REG_EDX, 0x49656E69)
            elif leaf == 1:
                # 无 AESNI/SSSE3 → OpenSSL 纯软路径
                uc.reg_write(UC_X86_REG_EAX, 0x000006F0)
                uc.reg_write(UC_X86_REG_EBX, 0)
                uc.reg_write(UC_X86_REG_ECX, 0)
                uc.reg_write(UC_X86_REG_EDX, 0x00008010)
            else:
                for r in (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX):
                    uc.reg_write(r, 0)
            return 0

        self.uc.hook_add(UC_HOOK_INSN, on_cpuid, None, 1, 0, UC_X86_INS_CPUID)

    # ---------- stub 基建 ----------
    def _jni_stub(self, name):
        idx = JNI[name]
        addr = STUB_REGION + self._jni_stub_n * 16
        self._jni_stub_n += 1
        self.uc.mem_write(addr, b"\xC3")
        self.jni_slot_addr[idx] = addr
        self.jni_addr_name[addr] = name
        self.uc.hook_add(UC_HOOK_CODE, self._on_jni, begin=addr, end=addr)
        return addr

    def _build_env_table(self):
        self.uc.mem_write(ENV_PTR, struct.pack("<I", ENV_TABLE))
        for name, idx in JNI.items():
            self.uc.mem_write(ENV_TABLE + idx * 4, struct.pack("<I", self._jni_stub(name)))
        generic = STUB_REGION + 0xFF0
        self.uc.mem_write(generic, b"\xC3")
        self.uc.hook_add(UC_HOOK_CODE, self._on_jni_generic, begin=generic, end=generic)
        for i in range(240):
            if i not in self.jni_slot_addr:
                self.uc.mem_write(ENV_TABLE + i * 4, struct.pack("<I", generic))
        log.info("[pcemu] %d JNI slots implemented / 240", len(JNI))

    def _args(self, uc, n):
        esp = uc.reg_read(UC_X86_REG_ESP)
        return [int.from_bytes(uc.mem_read(esp + 4 + 4 * i, 4), "little") for i in range(n)]

    def _ret_str(self, s: bytes):
        addr = self._arena_alloc(len(s) + 1)
        self.uc.mem_write(addr, s + b"\x00")
        return addr

    def _arena_alloc(self, n):
        a = self._arena
        self._arena += (n + 15) & ~15
        return a

    def _cstr(self, addr, maxn=4096):
        if not addr:
            return b""
        return bytes(self.uc.mem_read(addr, maxn)).split(b"\x00")[0]

    # ---------- JNI 处理器 ----------
    def _on_jni(self, uc, address, size, ud):
        name = self.jni_addr_name[address]
        fn = getattr(self, f"jni_{name}", None)
        if fn:
            try:
                uc.reg_write(UC_X86_REG_EAX, fn(uc) or 0)
            except UcError as e:
                log.error("[pcemu] JNI %s UcError: %s", name, e)
                raise
        else:
            log.debug("[pcemu] JNI unimplemented %s", name)
            uc.reg_write(UC_X86_REG_EAX, 0)

    def _on_jni_generic(self, uc, address, size, ud):
        # 未实现槽位（ExceptionCheck=228 等语义性 slot 返回 0 即"无异常/默认"）
        uc.reg_write(UC_X86_REG_EAX, 0)

    def _mk_ref(self, obj):
        self._next_jref += 4
        self.java_strs[self._next_jref] = obj
        return self._next_jref

    def jni_FindClass(self, uc):
        a = self._args(uc, 2)
        name = self._cstr(a[1], 128).decode(errors="replace")
        self._class_n += 4
        self.classes[self._class_n] = name
        return self._class_n

    def jni_GetObjectClass(self, uc):
        a = self._args(uc, 2)
        self._class_n += 4
        self.classes[self._class_n] = ("android/app/Application" if a[1] == self.CONTEXT_REF
                                       else "java/lang/String")
        return self._class_n

    def jni_GetMethodID(self, uc):
        a = self._args(uc, 4)
        nm = self._cstr(a[2], 96).decode(errors="replace")
        self._fid_n += 4
        self.fields[self._fid_n] = ("method", nm)
        return self._fid_n

    jni_GetStaticMethodID = jni_GetMethodID

    def jni_GetFieldID(self, uc):
        a = self._args(uc, 4)
        cn = self.classes.get(a[1], "?")
        nm = self._cstr(a[2], 96).decode(errors="replace")
        self._fid_n += 4
        self.fields[self._fid_n] = (cn, nm)
        return self._fid_n

    jni_GetStaticFieldID = jni_GetFieldID

    def jni_GetStaticObjectField(self, uc):
        a = self._args(uc, 3)
        key = self.fields.get(a[2])
        val = self.static_vals.get(key)
        if val is None:
            log.debug("[pcemu] GetStaticObjectField MISS key=%s", key)
            return 0
        return self._mk_ref(val)

    def jni_GetStaticIntField(self, uc):
        a = self._args(uc, 3)
        return int(self.static_vals.get(self.fields.get(a[2]), 0))

    def jni_NewStringUTF(self, uc):
        a = self._args(uc, 2)
        return self._mk_ref(self._cstr(a[1], 256).decode(errors="replace"))

    def jni_GetStringUTFLength(self, uc):
        a = self._args(uc, 2)
        v = self.java_strs.get(a[1], "")
        return len(v.encode() if isinstance(v, str) else v)

    def jni_GetStringUTFChars(self, uc):
        a = self._args(uc, 2)
        s = self.java_strs.get(a[1], "")
        return self._ret_str(s.encode() if isinstance(s, str) else s)

    def jni_ReleaseStringUTFChars(self, uc):
        return 0

    def jni_GetArrayLength(self, uc):
        a = self._args(uc, 2)
        if a[1] == self.SIGNATURES_REF:
            return 1
        return len(self.byte_arrays.get(a[1], b""))

    def jni_NewByteArray(self, uc):
        a = self._args(uc, 2)
        self._next_jref += 4
        self.byte_arrays[self._next_jref] = bytearray(a[1])
        # 稳定后备缓冲：GetByteArrayElements 返回直写指针（bionic 语义），Release 回写
        self.byte_array_backing[self._next_jref] = self._mem_alloc(a[1] + 16)
        return self._next_jref

    def _ba_backing(self, handle):
        addr = self.byte_array_backing.get(handle)
        if addr is None:
            data = self.byte_arrays.get(handle, b"")
            addr = self._mem_alloc(len(data) + 16)
            self.uc.mem_write(addr, bytes(data))
            self.byte_array_backing[handle] = addr
        return addr

    def jni_GetByteArrayElements(self, uc):
        a = self._args(uc, 3)
        addr = self._ba_backing(a[1])
        self.uc.mem_write(addr, bytes(self.byte_arrays.get(a[1], b"")))
        return addr

    def jni_ReleaseByteArrayElements(self, uc):
        a = self._args(uc, 3)
        addr = self.byte_array_backing.get(a[1])
        if addr is not None and a[1] in self.byte_arrays:
            ba = self.byte_arrays[a[1]]
            cur = bytes(self.uc.mem_read(addr, len(ba)))
            ba[:] = cur
        return 0

    def jni_GetByteArrayRegion(self, uc):
        a = self._args(uc, 5)
        data = self.byte_arrays.get(a[1], b"")
        self.uc.mem_write(a[4], data[a[2]:a[2] + a[3]])
        return 0

    def jni_SetByteArrayRegion(self, uc):
        a = self._args(uc, 5)
        data = bytes(self.uc.mem_read(a[4], a[3]))
        ba = self.byte_arrays.setdefault(a[1], bytearray())
        ba[a[2]:a[2] + a[3]] = data
        addr = self.byte_array_backing.get(a[1])
        if addr is not None:
            self.uc.mem_write(addr + a[2], data)
        return 0

    def jni_CallStaticObjectMethod(self, uc):
        a = self._args(uc, 3)
        key = self.fields.get(a[2], ("?", "?"))
        if key[1] == "currentApplication":
            return self.CONTEXT_REF
        log.debug("[pcemu] CallStaticObjectMethod %s", key)
        return 0

    jni_CallStaticObjectMethodV = jni_CallStaticObjectMethod

    def jni_CallObjectMethod(self, uc):
        a = self._args(uc, 3)
        name = self.fields.get(a[2], ("?", "?"))[1]
        if name == "getAssets":
            return self.FAKE_AM
        if name == "getPackageName":
            return self._mk_ref(self._package_name)
        if name == "toByteArray":
            der = open(self._cert_path, "rb").read()
            self._next_jref += 4
            self.byte_arrays[self._next_jref] = bytearray(der)
            # 白盒可能把 DER 指针缓存进静态区跨调用使用 → 常驻豁免，防 GC 后备复用腐坏
            self._persistent_arrays.add(self._next_jref)
            return self._next_jref
        if name == "getPackageManager":
            return self.PM_REF
        if name == "getPackageInfo":
            return self.PI_REF
        if name in ("getApplicationContext", "getApplication", "getContext"):
            return self.CONTEXT_REF
        if name == "getFilesDir":
            return self._mk_ref(f"/data/data/{self._package_name}/files")
        log.debug("[pcemu] CallObjectMethod MISS %s", name)
        return 0

    jni_CallObjectMethodV = jni_CallObjectMethod

    def jni_CallBooleanMethod(self, uc):
        return 1

    def jni_GetObjectField(self, uc):
        a = self._args(uc, 3)
        name = self.fields.get(a[2], ("?", "?"))[1]
        if name == "versionName":
            return self._mk_ref("6.3.20.2")
        if name == "signatures":
            return self.SIGNATURES_REF
        log.debug("[pcemu] GetObjectField MISS %s", name)
        return 0

    def jni_NewObjectArray(self, uc):
        a = self._args(uc, 4)
        self._next_jref += 4
        self.java_strs[self._next_jref] = [None] * a[2]
        return self._next_jref

    def jni_GetObjectArrayElement(self, uc):
        a = self._args(uc, 3)
        if a[1] == self.SIGNATURES_REF:
            return self.SIGNATURE_REF
        arr = self.java_strs.get(a[1])
        return arr[a[2]] if isinstance(arr, list) and a[2] < len(arr) else 0

    def jni_SetObjectArrayElement(self, uc):
        a = self._args(uc, 4)
        arr = self.java_strs.get(a[1])
        if isinstance(arr, list) and a[2] < len(arr):
            arr[a[2]] = a[3]
        return 0

    def jni_RegisterNatives(self, uc):
        log.debug("[pcemu] RegisterNatives called (ignored)")
        return 0

    # ---------- libc ----------
    def _mem_alloc(self, n, align=16):
        # free-list 首次适配：imp_free 必须真实回收，否则 EVP ctx/operator new
        # 每次调用泄漏，长跑几百次 dec 后堆耗尽 → UC_ERR_WRITE_UNMAPPED。
        # 对齐：仅当块地址满足请求对齐才复用（posix_memalign 语义）；
        # 容量：按 rounded 容量记录（_block_caps），复用不降级，剩余空间不永久丢失。
        for p, cap in self._block_caps.items():
            if p in self._free_set and cap >= n and p % align == 0:
                self._free_set.discard(p)
                self.alloc_sizes[p] = n
                return p
        a = (self.brk + align - 1) & ~(align - 1)
        self.brk = a + ((n + 15) & ~15)
        self.alloc_sizes[a] = n
        self._block_caps[a] = self.brk - a  # rounded 实际占用容量
        return a

    def _free_block(self, p):
        if p in self.alloc_sizes:
            del self.alloc_sizes[p]
            self._free_set.add(p)  # 容量记录保留在 _block_caps（可能大于后续请求）

    def imp_malloc(self, uc):
        return self._mem_alloc(self._args(uc, 1)[0])

    def imp_calloc(self, uc):
        n, sz = self._args(uc, 2)
        a = self._mem_alloc(n * sz)
        self.uc.mem_write(a, b"\x00" * (n * sz))
        return a

    def imp_realloc(self, uc):
        p, n = self._args(uc, 2)
        if not p:
            return self._mem_alloc(n)
        old = self.alloc_sizes.get(p, n)
        a = self._mem_alloc(n)
        self.uc.mem_write(a, bytes(self.uc.mem_read(p, min(old, n))))
        return a

    def imp_free(self, uc):
        self._free_block(self._args(uc, 1)[0])
        return 0

    def imp_feof(self, uc):
        return 0

    imp_ferror = imp_feof
    imp_fflush = imp_feof

    def imp_posix_memalign(self, uc):
        out, align, n = self._args(uc, 3)
        self.uc.mem_write(out, struct.pack("<I", self._mem_alloc(n, max(align, 16))))
        return 0

    def imp_memcpy(self, uc):
        d, s, n = self._args(uc, 3)
        if n:
            self.uc.mem_write(d, bytes(self.uc.mem_read(s, n)))
        return d

    imp_memmove = imp_memcpy
    imp___memcpy_chk = imp_memcpy
    imp___memmove_chk = imp_memcpy  # libauthSign 真实未定义导入；缺失时静默不拷贝（fail-visible 违规）

    def imp_memset(self, uc):
        d, c, n = self._args(uc, 3)
        if n:
            self.uc.mem_write(d, bytes([c & 0xFF]) * n)
        return d

    imp___memset_chk = imp_memset

    def imp_memcmp(self, uc):
        a, b, n = self._args(uc, 3)
        x, y = bytes(self.uc.mem_read(a, n)), bytes(self.uc.mem_read(b, n))
        return (x > y) - (x < y)

    def imp_memchr(self, uc):
        s, c, n = self._args(uc, 3)
        idx = bytes(self.uc.mem_read(s, n)).find(bytes([c & 0xFF]))
        return s + idx if idx >= 0 else 0

    def imp_strlen(self, uc):
        return len(self._cstr(self._args(uc, 1)[0]))

    imp___strlen_chk = imp_strlen

    def imp_strcpy(self, uc):
        d, s = self._args(uc, 2)
        data = self._cstr(s) + b"\x00"
        self.uc.mem_write(d, data)
        return d

    imp___strcpy_chk = imp_strcpy

    def imp_strncpy(self, uc):
        d, s, n = self._args(uc, 3)
        data = self._cstr(s, n)[:n]
        self.uc.mem_write(d, data + b"\x00" * (n - len(data)))
        return d

    imp___strncpy_chk = imp_strncpy

    def imp_strcmp(self, uc):
        a, b = self._args(uc, 2)
        x, y = self._cstr(a), self._cstr(b)
        return (x > y) - (x < y)

    def imp_strncmp(self, uc):
        a, b, n = self._args(uc, 3)
        x, y = self._cstr(a, n)[:n], self._cstr(b, n)[:n]
        return (x > y) - (x < y)

    def imp_strcat(self, uc):
        d, s = self._args(uc, 2)
        self.uc.mem_write(d + len(self._cstr(d)), self._cstr(s) + b"\x00")
        return d

    def imp_strchr(self, uc):
        s, c = self._args(uc, 2)
        idx = self._cstr(s).find(bytes([c & 0xFF]))
        return s + idx if idx >= 0 else 0

    imp_strrchr = imp_strchr

    def imp_strstr(self, uc):
        h, n = self._args(uc, 2)
        idx = self._cstr(h).find(self._cstr(n))
        return h + idx if idx >= 0 else 0

    def imp_strdup(self, uc):
        s = self._args(uc, 1)[0]
        data = self._cstr(s) + b"\x00"
        a = self._mem_alloc(len(data))
        self.uc.mem_write(a, data)
        return a

    def imp_abort(self, uc):
        raise RuntimeError("[pcemu] abort() called")

    def imp___android_log_print(self, uc):
        esp = uc.reg_read(UC_X86_REG_ESP)
        tag = int.from_bytes(uc.mem_read(esp + 8, 4), "little")
        fmt = int.from_bytes(uc.mem_read(esp + 12, 4), "little")
        log.debug("[pcemu][log] %s: %s",
                  self._cstr(tag, 64).decode(errors="replace"),
                  self._cstr(fmt, 128).decode(errors="replace"))
        return 0

    def imp_getenv(self, uc):
        return 0

    def imp_pthread_once(self, uc):
        return 0

    imp_pthread_mutex_lock = imp_pthread_once
    imp_pthread_mutex_unlock = imp_pthread_once
    imp_pthread_rwlock_rdlock = imp_pthread_once
    imp_pthread_rwlock_wrlock = imp_pthread_once
    imp_pthread_rwlock_unlock = imp_pthread_once
    imp_pthread_key_create = imp_pthread_once
    imp_pthread_key_delete = imp_pthread_once

    def imp_pthread_getspecific(self, uc):
        return self.tls_slots.get(self._args(uc, 1)[0], 0)

    def imp_pthread_setspecific(self, uc):
        k, v = self._args(uc, 2)
        self.tls_slots[k] = v
        return 0

    def imp___stack_chk_fail(self, uc):
        raise RuntimeError("[pcemu] __stack_chk_fail")

    def imp___errno(self, uc):
        if not hasattr(self, "_errno_addr"):
            self._errno_addr = self._mem_alloc(4)
        return self._errno_addr

    # ---------- 文件 VFS ----------
    def _init_file_vfs(self):
        self.files = {}
        self._file_n = 0x3B000

    def _synth_maps(self):
        lines = [
            "0c000000-0c100000 rwxp 00000000 00:00 0          [anon:libc_malloc]",
            f"{BASE:x}-{BASE + 0x382398:x} r-xp 00000000 fd:01 12345    /data/app/com.aiyu.kaipanla-MibnEsTYjx-z7wDAymTrqQ==/lib/x86_sig/libauthSign.so",
            f"{BASE + 0x382398:x}-{BASE + 0x384398:x} rw-p 000382398 fd:01 12345    /data/app/com.aiyu.kaipanla-MibnEsTYjx-z7wDAymTrqQ==/lib/x86_sig/libauthSign.so",
            "f7000000-f7800000 r-xp 00000000 fd:01 6789     /system/lib/libc.so",
        ]
        return ("\n".join(lines) + "\n").encode()

    def imp_fopen(self, uc):
        a = self._args(uc, 2)
        path = self._cstr(a[0], 256).decode(errors="replace")
        if path == "/proc/self/maps":
            data = self._synth_maps()
        elif path.startswith("/proc/"):
            data = b""
        else:
            p = os.path.join(self._assets_dir, path.lstrip("/"))
            if os.path.exists(p):
                data = open(p, "rb").read()
            else:
                # 不可读路径（如编译期 openssl.cnf）→ 空文件句柄，避免 NULL 解引用级联
                log.debug("[pcemu] fopen MISS %s → empty", path)
                data = b""
        self._file_n += 4
        self.files[self._file_n] = [data, 0]
        return self._file_n

    def imp_fread(self, uc):
        buf, sz, n, f = self._args(uc, 4)
        st = self.files.get(f)
        if not st:
            return 0
        want = sz * n
        chunk = st[0][st[1]:st[1] + want]
        self.uc.mem_write(buf, chunk)
        st[1] += len(chunk)
        return len(chunk) // sz if sz else 0

    def imp_fgets(self, uc):
        buf, n, f = self._args(uc, 3)
        st = self.files.get(f)
        if not st:
            return 0
        data, pos = st
        nl = data.find(b"\n", pos)
        end = (nl + 1) if nl >= 0 else len(data)
        line = data[pos:min(end, pos + n - 1)]
        if not line:
            return 0
        self.uc.mem_write(buf, line + b"\x00")
        st[1] = pos + len(line)
        return buf

    def imp_fclose(self, uc):
        self.files.pop(self._args(uc, 1)[0], None)
        return 0

    def imp_fseek(self, uc):
        f, off, whence = self._args(uc, 3)
        st = self.files.get(f)
        if not st:
            return -1 & 0xFFFFFFFF
        st[1] = off if whence == 0 else (len(st[0]) + off if whence == 2 else st[1] + off)
        return 0

    def imp_ftell(self, uc):
        st = self.files.get(self._args(uc, 1)[0])
        return st[1] if st else -1 & 0xFFFFFFFF

    imp_feof = imp_free
    imp_ferror = imp_free
    imp_fflush = imp_free

    def imp_fstat(self, uc):
        f, st = self._args(uc, 2)
        info = self.files.get(f)
        size = len(info[0]) if info else 0
        self.uc.mem_write(st, struct.pack("<8I", 0, 0, 0, 0, 0, size, 0, 0))
        return 0

    def imp_getpid(self, uc):
        return 12345

    imp___assert2 = imp_getpid

    def imp_getuid(self, uc):
        return 10050

    def imp_sysconf(self, uc):
        return 4096

    def imp_clock_gettime(self, uc):
        clk, ts = self._args(uc, 2)
        self.uc.mem_write(ts, struct.pack("<II", int(time.time()), 0))
        return 0

    def imp_gettimeofday(self, uc):
        self.uc.mem_write(self._args(uc, 1)[0], struct.pack("<II", int(time.time()), 0))
        return 0

    def imp_usleep(self, uc):
        return 0

    def imp_dl_iterate_phdr(self, uc):
        return 0

    def imp_dlopen(self, uc):
        return 0x3A000

    def imp_dlsym(self, uc):
        return 0

    def imp_dlclose(self, uc):
        return 0

    def imp_dlerror(self, uc):
        return 0

    def imp_getauxval(self, uc):
        return 0

    def imp_syscall(self, uc):
        return 0

    # ---------- Asset VFS ----------
    def _init_asset_vfs(self):
        self._arena = 0x56000000
        self.uc.mem_map(0x56000000, 16 * 1024 * 1024)
        self.assets = {}
        self._asset_n = 0x40000
        for nm in ("AAssetManager_fromJava", "AAssetManager_open", "AAsset_close",
                   "AAsset_getLength", "AAsset_read"):
            self.import_handlers[self._stub_for(nm)] = getattr(self, f"asset_{nm}")

    def asset_AAssetManager_fromJava(self, uc):
        return 0x39000

    def asset_AAssetManager_open(self, uc):
        esp = uc.reg_read(UC_X86_REG_ESP)
        fn_ptr = int.from_bytes(uc.mem_read(esp + 8, 4), "little")
        path = self._cstr(fn_ptr, 200).decode(errors="replace")
        p = os.path.join(self._assets_dir, path)
        if os.path.exists(p):
            data = open(p, "rb").read()
            self._asset_n += 4
            self.assets[self._asset_n] = [data, 0, path]
            log.info("[pcemu] asset open %s (%dB)", path, len(data))
            return self._asset_n
        log.warning("[pcemu] asset MISS %s", path)
        return 0

    def asset_AAsset_read(self, uc):
        esp = uc.reg_read(UC_X86_REG_ESP)
        h, buf, ln = (int.from_bytes(uc.mem_read(esp + 4 + 4 * i, 4), "little") for i in range(3))
        a = self.assets.get(h)
        if not a:
            return 0
        chunk = a[0][a[1]:a[1] + ln]
        self.uc.mem_write(buf, chunk)
        a[1] += len(chunk)
        return len(chunk)

    def asset_AAsset_getLength(self, uc):
        h = self._args(uc, 1)[0]
        return len(self.assets[h][0]) if h in self.assets else 0

    def asset_AAsset_close(self, uc):
        return 0

    # ---------- on_stub（libc/asset 分发） ----------
    def _on_stub(self, uc, address, size, user_data):
        name = self.stub_names.get(address, "?")
        self.hit_counts[name] = self.hit_counts.get(name, 0) + 1
        handler = getattr(self, f"imp_{name}", None)
        if handler is None:
            handler = self.import_handlers.get(address)
        if handler:
            ret = handler(uc)
            uc.reg_write(UC_X86_REG_EAX, ret if ret is not None else 0)
        elif self.hit_counts[name] <= 3:
            log.debug("[pcemu] stub %s args=%s", name, [hex(a) for a in self._args(uc, 4)])
            uc.reg_write(UC_X86_REG_EAX, 0)
        else:
            uc.reg_write(UC_X86_REG_EAX, 0)

    # ---------- 高层操作 ----------
    def call(self, addr_off: int, args=()) -> None:
        uc = self.uc
        MAGIC = 0x1DEAD000
        esp = STACK - 0x100000
        for a in reversed(args):
            esp -= 4
            uc.mem_write(esp, struct.pack("<I", a & 0xFFFFFFFF))
        esp -= 4
        uc.mem_write(esp, struct.pack("<I", MAGIC))
        uc.reg_write(UC_X86_REG_ESP, esp)
        uc.reg_write(UC_X86_REG_EBP, STACK - 0x90000)
        uc.emu_start(BASE + addr_off, MAGIC, timeout=0)

    def _mk_ba(self, data: bytes) -> int:
        self._next_jref += 4
        h = self._next_jref
        self.byte_arrays[h] = bytearray(data)
        self.byte_array_backing[h] = self._mem_alloc(len(data) + 16)
        self.uc.mem_write(self.byte_array_backing[h], data)
        return h

    def _gc_temp_arrays(self, before: set) -> None:
        """回收本次调用新建的 jbyteArray（JNI local 引用随调用消亡）。

        before = 调用前 byte_arrays 快照：集合差即本次新建（含输入与输出），
        全部回收后备缓冲；常驻数组（_persistent_arrays：SIGNATURE_REF、
        非调用期创建的 toByteArray DER）不动——白盒可能在静态区缓存其指针。
        """
        for k in set(self.byte_arrays) - before:
            if k in self._persistent_arrays:
                continue
            addr = self.byte_array_backing.pop(k, None)
            if addr is not None:
                self._free_block(addr)
            del self.byte_arrays[k]

    def _ba_out(self) -> bytes:
        h = self.uc.reg_read(UC_X86_REG_EAX)
        return bytes(self.byte_arrays.get(h, b""))

    def init_bax_pwd(self) -> None:
        self.call(ADDR_INIT_BAX_PWD, (ENV_PTR, 0x1, self.FAKE_AM))

    def whitebox_encrypt(self, challenge: str, device_id: str,
                         conn_type: str, cur_time: str) -> bytes:
        before = set(self.byte_arrays)
        try:
            a = self._mk_ref(challenge)
            b = self._mk_ref(device_id)
            c = self._mk_ref(conn_type)
            d = self._mk_ref(cur_time)
            self.call(ADDR_WBE, (ENV_PTR, 0x1, a, b, c, d))
            return self._ba_out()
        finally:
            self._gc_temp_arrays(before)

    def encrypt(self, plain: bytes) -> bytes:
        before = set(self.byte_arrays)
        h = self._mk_ba(plain)
        try:
            self.call(ADDR_ENC, (ENV_PTR, 0x1, h))
            return self._ba_out()
        finally:
            self._gc_temp_arrays(before)

    def decrypt(self, cipher: bytes) -> bytes:
        before = set(self.byte_arrays)
        h = self._mk_ba(cipher)
        try:
            self.call(ADDR_DEC, (ENV_PTR, 0x1, h))
            return self._ba_out()
        finally:
            self._gc_temp_arrays(before)
