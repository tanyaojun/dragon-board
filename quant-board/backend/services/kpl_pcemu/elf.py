# -*- coding: utf-8 -*-
"""ELF32 加载器 + unicorn x86-32 模拟基座（移植自 .tmp_review/wbx_emu.py）。

要点（历史教训，勿改坏）：
- R_386_32 必须 S+A 语义（曾错写 BASE+A 导致函数指针损坏）
- UC_HOOK_CODE 必须在首次执行前注册；unicorn fault hook 返回 True 会重试原指令
- unicorn 2.1.2 x86-32 的 gdtr/GS 段基址方案不生效 → 用 NULL 页映射替代栈保护
"""
from __future__ import annotations

import logging
import struct

from unicorn import UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESP

log = logging.getLogger(__name__)

BASE = 0x40000000
STACK = 0x7F000000
STACK_SIZE = 4 * 1024 * 1024
HEAP = 0x50000000
HEAP_SIZE = 64 * 1024 * 1024

# ELF32 常量
PT_LOAD = 1
R_386_32 = 1
R_386_GLOB_DAT = 6
R_386_JMP_SLOT = 7
R_386_RELATIVE = 8


class ElfImage:
    """最小 ELF32 解析：program headers + dynsym/dynstr/rel.dyn/rel.plt/hash。"""

    def __init__(self, path):
        self.data = open(path, "rb").read()
        d = self.data
        assert d[:4] == b"\x7fELF" and d[4] == 1, "expect ELF32"
        self.e_phoff, = struct.unpack_from("<I", d, 28)
        self.e_phentsize, self.e_phnum = struct.unpack_from("<HH", d, 42)
        self.e_shoff, = struct.unpack_from("<I", d, 32)
        self.e_shentsize, self.e_shnum, self.e_shstrndx = struct.unpack_from("<HHH", d, 46)
        self.phdrs = []
        for i in range(self.e_phnum):
            off = self.e_phoff + i * self.e_phentsize
            p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack_from("<8I", d, off)
            self.phdrs.append(dict(type=p_type, off=p_offset, vaddr=p_vaddr,
                                   filesz=p_filesz, memsz=p_memsz, flags=p_flags))
        secs = []
        for i in range(self.e_shnum):
            off = self.e_shoff + i * self.e_shentsize
            secs.append(struct.unpack_from("<10I", d, off))
        shstr = secs[self.e_shstrndx]

        def nm(n):
            s = d[shstr[4] + n:]
            return s[:s.index(b"\0")].decode()

        def sec(name):
            for v in secs:
                if nm(v[0]) == name:
                    return dict(addr=v[3], off=v[4], size=v[5], link=v[6], entsize=v[9])
            return None

        self.dynsym = sec(".dynsym")
        self.dynstr = sec(".dynstr")
        self.rel_dyn = sec(".rel.dyn")
        self.rel_plt = sec(".rel.plt")
        self.hash = sec(".hash")

    def sym(self, idx):
        off = self.dynsym["off"] + idx * 16
        st_name, st_value, st_size, st_info, st_other, st_shndx = struct.unpack_from("<IIIBBH", self.data, off)
        s = self.data[self.dynstr["off"] + st_name:]
        return s[:s.index(b"\0")].decode(errors="replace"), st_value, st_size, st_info, st_shndx

    def sym_by_name(self, name):
        def h(s):
            hh = 0
            for c in s.encode():
                hh = (hh << 4) + c
                g = hh & 0xF0000000
                if g:
                    hh ^= g >> 24
            return hh & 0xFFFFFFFF
        bucket_off = self.hash["off"]
        nbucket, nchain = struct.unpack_from("<II", self.data, bucket_off)
        buckets = struct.unpack_from(f"<{nbucket}I", self.data, bucket_off + 8)
        chains = struct.unpack_from(f"<{nchain}I", self.data, bucket_off + 8 + 4 * nbucket)
        idx = buckets[h(name) % nbucket]
        while idx:
            nm_, val, sz, info, shndx = self.sym(idx)
            if nm_ == name:
                return val, sz, info, shndx
            idx = chains[idx]
        return None


class Emu:
    """unicorn x86-32 载入一个 ELF32 so；未定义导入生成 trap stub。"""

    def __init__(self, so_path: str):
        self.so_path = so_path
        self.elf = ElfImage(so_path)
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.hooks = []
        self.import_stubs = {}     # name -> stub addr
        self.stub_names = {}       # addr -> name
        self.hit_counts = {}       # name -> n
        self.jni_refs = {}
        self._next_ref = 0x10000
        self.next_stub = 0
        self._load()
        self._relocate()

    # ---------- 内存 ----------
    def _load(self):
        uc = self.uc
        uc.mem_map(BASE, 8 * 1024 * 1024)
        for ph in self.elf.phdrs:
            if ph["type"] != PT_LOAD:
                continue
            va = BASE + ph["vaddr"]
            uc.mem_write(va, self.elf.data[ph["off"]:ph["off"] + ph["filesz"]])
        uc.mem_map(STACK - STACK_SIZE, STACK_SIZE)
        uc.mem_map(HEAP, HEAP_SIZE)
        self.brk = HEAP
        log.info("[pcemu] loaded %s @ %#x", self.so_path, BASE)

    def set_gate(self, offset: int, value: bytes) -> None:
        """写镜像内状态字节（白盒/enc 门位；设备上由启动链置位，PC 端显式置位）。"""
        self.uc.mem_write(BASE + offset, value)

    # ---------- 重定位 ----------
    def _relocate(self):
        uc = self.uc
        for rel_sec in (self.elf.rel_dyn, self.elf.rel_plt):
            if not rel_sec:
                continue
            n = rel_sec["size"] // 8
            for i in range(n):
                off = rel_sec["off"] + i * 8
                r_offset, r_info = struct.unpack_from("<II", self.elf.data, off)
                sym_idx, r_type = r_info >> 8, r_info & 0xFF
                va = BASE + r_offset
                if r_type == R_386_RELATIVE:
                    cur = int.from_bytes(self._read(va, 4), "little")
                    self._write(va, struct.pack("<I", (BASE + cur) & 0xFFFFFFFF))
                elif r_type in (R_386_32, R_386_GLOB_DAT, R_386_JMP_SLOT):
                    name, val, sz, info, shndx = self.elf.sym(sym_idx)
                    if val:
                        S = BASE + val
                    else:
                        S = self._stub_for(name) if name else 0
                    A = int.from_bytes(self._read(va, 4), "little") if r_type == R_386_32 else 0
                    self._write(va, struct.pack("<I", (S + A) & 0xFFFFFFFF))
                else:
                    log.warning("[pcemu] unhandled reloc type %d at %#x", r_type, va)
        log.info("[pcemu] relocation done")

    def _read(self, addr, n):
        return self.uc.mem_read(addr, n)

    def _write(self, addr, data):
        self.uc.mem_write(addr, data)

    # ---------- 导入 stub ----------
    def _stub_for(self, name):
        if name in self.import_stubs:
            return self.import_stubs[name]
        addr = 0x60000000 + self.next_stub * 16
        self.next_stub += 1
        if self.next_stub == 1:
            self.uc.mem_map(0x60000000, 64 * 1024)
        self.uc.mem_write(addr, b"\xC3")  # ret
        self.import_stubs[name] = addr
        self.stub_names[addr] = name
        h = self.uc.hook_add(UC_HOOK_CODE, self._on_stub, begin=addr, end=addr)
        self.hooks.append(h)
        return addr

    def _on_stub(self, uc, address, size, user_data):
        name = self.stub_names.get(address, "?")
        self.hit_counts[name] = self.hit_counts.get(name, 0) + 1
        handler = getattr(self, f"imp_{name}", None)
        if handler:
            ret = handler(uc)
            uc.reg_write(UC_X86_REG_EAX, ret if ret is not None else 0)
        elif self.hit_counts[name] <= 3:
            esp = uc.reg_read(UC_X86_REG_ESP)
            args = [int.from_bytes(uc.mem_read(esp + 4 + 4 * i, 4), "little") for i in range(4)]
            log.debug("[pcemu] stub %s args=%s", name, [hex(a) for a in args])
            uc.reg_write(UC_X86_REG_EAX, 0)
        else:
            uc.reg_write(UC_X86_REG_EAX, 0)
