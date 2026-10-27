# -*- coding: utf-8 -*-
"""提取 KPL PC 模拟核工件 → quant-board/data/kpl_pcemu/（gitignored 本地状态）。

产物三件套：
- libauthSign_x86.so   白盒签名库（x86_sig 变体，从设备已安装 APK 提取）
- assets/middle_new.bin 白盒表资产（PCEmulatorCodec initBaxPwd 输入）
- signer_cert.der      签名证书 DER（JNI GetByteArrayElements/toByteArray 链输入）

两种来源模式：
1) 设备模式（默认）：adb + su 从模拟器已安装 base.apk 提取（需 root 模拟器在线）
2) 归档模式：--from-dir <已解包 apk 目录> --so <libauthSign_x86.so> --cert <cert.der>
   供离线环境从既有研究工件组装（.tmp_review 即此来源；so 必须用设备
   /data/app/.../lib/x86_sig/ 提取的白盒签名变体，APK 内 lib/x86/ 普通变体不可用）

用法：
  .venv/Scripts/python.exe scripts/extract_kpl_pcemu.py
  .venv/Scripts/python.exe scripts/extract_kpl_pcemu.py --from-dir ../.tmp_review/apk_unzip \
      --so ../.tmp_review/libauthSign_x86.so --cert ../.tmp_review/kpl_signer_cert.der

验证：提取后自动跑最小校验（文件尺寸 + ELF magic）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "kpl_pcemu"
ADB = os.environ.get("KPL_ADB_PATH", r"D:/Android/Sdk/platform-tools/adb.exe")
DEVICE = os.environ.get("KPL_ADB_DEVICE", "emulator-5554")  # 与 serve_kpl_socket 同约定
PKG = "com.aiyu.kaipanla"
EXPECTED_SO_SIZE_MIN = 3_000_000  # libauthSign_x86.so 实测 3.68MB
EXPECTED_ASSET_SIZE_MIN = 100_000  # middle_new.bin 实测 283920B


def device_mode(out_dir: Path) -> None:
    # pm path 拿安装路径
    r = subprocess.run([ADB, "-s", DEVICE, "shell", f"pm path {PKG}"],
                       capture_output=True, text=True, timeout=30)
    apk_line = (r.stdout or "").strip().splitlines()
    if not apk_line or not apk_line[0].startswith("package:"):
        raise SystemExit(f"[extract] pm path 失败: {r.stdout!r} {r.stderr!r}")
    apk_path = apk_line[0].removeprefix("package:").strip()
    print(f"[extract] device apk: {apk_path}")
    with tempfile.TemporaryDirectory() as td:
        local_apk = Path(td) / "base.apk"
        # su cat 绕过 /data/app 权限（root 模拟器）
        with open(local_apk, "wb") as f:
            r2 = subprocess.run([ADB, "-s", DEVICE, "shell", f"su -c 'cat {apk_path}'"],
                                stdout=f, stderr=subprocess.PIPE, timeout=120)
        if r2.returncode != 0 or local_apk.stat().st_size < 1_000_000:
            raise SystemExit(f"[extract] adb pull 失败: {r2.stderr!r}")
        _unpack(local_apk, out_dir)


def archive_mode(from_dir: Path, so_path: Path, cert_path: Path, out_dir: Path) -> None:
    src_assets = from_dir / "assets" / "middle_new.bin"
    if not src_assets.exists():
        raise SystemExit(f"[extract] 找不到 {src_assets}")
    (out_dir / "assets").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_assets, out_dir / "assets" / "middle_new.bin")
    print(f"[extract] middle_new.bin <- {src_assets}")
    shutil.copyfile(so_path, out_dir / "libauthSign_x86.so")
    print(f"[extract] libauthSign_x86.so <- {so_path}")
    shutil.copyfile(cert_path, out_dir / "signer_cert.der")
    print(f"[extract] signer_cert.der <- {cert_path}")


def _unpack(apk_zip: Path, out_dir: Path) -> None:
    z = zipfile.ZipFile(apk_zip)
    so_names = [n for n in z.namelist() if n == "lib/x86_sig/libauthSign.so"]
    asset_names = [n for n in z.namelist() if n == "assets/middle_new.bin"]
    cert_names = [n for n in z.namelist()
                  if n.startswith("META-INF/") and n.upper().endswith((".RSA", ".DSA", ".EC"))]
    missing = []
    if not so_names:
        missing.append("lib/x86_sig/libauthSign.so")
    if not asset_names:
        missing.append("assets/middle_new.bin")
    if not cert_names:
        missing.append("META-INF/*.RSA")
    if missing:
        raise SystemExit(f"[extract] apk 内缺条目: {missing}")
    (out_dir / "assets").mkdir(parents=True, exist_ok=True)
    (out_dir / "libauthSign_x86.so").write_bytes(z.read(so_names[0]))
    (out_dir / "assets" / "middle_new.bin").write_bytes(z.read(asset_names[0]))
    der = _pkcs7_to_cert_der(z.read(cert_names[0]))
    (out_dir / "signer_cert.der").write_bytes(der)
    print(f"[extract] from {apk_zip}: so/asset/cert 三件套已写入")


def _pkcs7_to_cert_der(pkcs7_der: bytes) -> bytes:
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509 import load_der_pkcs7_certificates

    certs = load_der_pkcs7_certificates(pkcs7_der)
    if not certs:
        raise SystemExit("[extract] PKCS7 内无证书")
    return certs[0].public_bytes(Encoding.DER)


def _load_x509_der(der: bytes):
    from cryptography import x509

    return x509.load_der_x509_certificate(der)


def verify(out_dir: Path) -> None:
    so = out_dir / "libauthSign_x86.so"
    asset = out_dir / "assets" / "middle_new.bin"
    cert = out_dir / "signer_cert.der"
    for p in (so, asset, cert):
        if not p.exists():
            raise SystemExit(f"[verify] 缺 {p}")
    if so.stat().st_size < EXPECTED_SO_SIZE_MIN:
        raise SystemExit(f"[verify] so 尺寸异常: {so.stat().st_size}")
    if so.read_bytes()[:4] != b"\x7fELF":
        raise SystemExit("[verify] so 非 ELF")
    if asset.stat().st_size < EXPECTED_ASSET_SIZE_MIN:
        raise SystemExit(f"[verify] middle_new.bin 尺寸异常: {asset.stat().st_size}")
    try:
        _load_x509_der(cert.read_bytes())
    except Exception as e:
        raise SystemExit(f"[verify] signer_cert.der 非 DER X.509（PEM 不可用）: {e}")
    print(f"[verify] OK  so={so.stat().st_size}B asset={asset.stat().st_size}B "
          f"cert={cert.stat().st_size}B → {out_dir}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-dir", type=Path, default=None,
                    help="已解包 apk 目录（含 assets/middle_new.bin）")
    ap.add_argument("--so", type=Path, default=None)
    ap.add_argument("--cert", type=Path, default=None)
    args = ap.parse_args()
    if (args.so or args.cert) and not args.from_dir:
        raise SystemExit("[extract] --so/--cert 只能与 --from-dir 搭配（缺 --from-dir 会静默落入设备模式）")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.from_dir:
        if not (args.so and args.cert):
            raise SystemExit("[extract] --from-dir 需同时给 --so 与 --cert")
        archive_mode(args.from_dir, args.so, args.cert, OUT_DIR)
    else:
        device_mode(OUT_DIR)
    verify(OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
