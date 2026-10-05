#!/usr/bin/env python
"""AI Search（原 AutoRAG）文档索引工具：把 quant-board/docs/** 的 markdown 建成可检索 RAG 索引。

凭据走环境变量（不入仓、不入库）：
  CLOUDFLARE_API_TOKEN    必填，权限需 Account > AI Search:Edit + AI Search:Run
  CLOUDFLARE_ACCOUNT_ID   选填，默认取本项目已知账户 ID

常用命令（在 quant-board/ 目录下）：
  .\\.venv\\Scripts\\python.exe scripts\\cloudflare_docs_rag.py create --id dragon-board-docs
  .\\.venv\\Scripts\\python.exe scripts\\cloudflare_docs_rag.py upload --id dragon-board-docs --dry-run
  .\\.venv\\Scripts\\python.exe scripts\\cloudflare_docs_rag.py upload --id dragon-board-docs
  .\\.venv\\Scripts\\python.exe scripts\\cloudflare_docs_rag.py upload --id dragon-board-docs --extra-root ../docs
  .\\.venv\\Scripts\\python.exe scripts\\cloudflare_docs_rag.py stats --id dragon-board-docs
  .\\.venv\\Scripts\\python.exe scripts\\cloudflare_docs_rag.py search --id dragon-board-docs "EOD 情绪分 门控"

Runbook：docs/cloudflare-docs-rag-setup.md
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

DEFAULT_ACCOUNT_ID = "921cf15176f84c90ea49865334af32c6"  # 项目已登记的 CF 账户（非机密）
BASE = "https://api.cloudflare.com/client/v4"
MAX_FILE_BYTES = 5 * 1024 * 1024  # 超过 5MB 跳过并告警（fail-visible，不静默）


def _token() -> str:
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not token:
        sys.exit(
            "[fail] 缺少 CLOUDFLARE_API_TOKEN 环境变量"
            "（Dashboard > My Profile > API Tokens，权限 AI Search:Edit + AI Search:Run）"
        )
    return token


def _account() -> str:
    return os.environ.get("CLOUDFLARE_ACCOUNT_ID", DEFAULT_ACCOUNT_ID).strip()


def _client(token: str) -> httpx.Client:
    # 不设默认 Content-Type：json= 调用由 httpx 自动补 application/json，
    # multipart 上传由 httpx 自动补 boundary（默认 Content-Type 会污染 multipart）。
    return httpx.Client(
        base_url=BASE,
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )


def _instance_url(account: str, instance_id: str, action: str = "") -> str:
    base = f"/accounts/{account}/ai-search/namespaces/default/instances/{instance_id}"
    return f"{base}/{action}" if action else base


def _instances_collection_url(account: str) -> str:
    # create POST 到集合路径（不能带 id，否则双斜杠 404）
    return f"/accounts/{account}/ai-search/namespaces/default/instances"


def collect_markdown(roots: list[Path]) -> list[tuple[Path, str]]:
    """收集各 root 下的 *.md，远端对象名加 root 目录名前缀防跨根重名。"""
    items: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            print(f"[warn] 目录不存在，跳过：{root}")
            continue
        prefix = root.resolve().name  # 如 "docs" / "quant-board"
        for path in sorted(root.rglob("*.md")):
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                print(f"[warn] 超 {MAX_FILE_BYTES // 1024 // 1024}MB 跳过（fail-visible）：{path}")
                continue
            remote_name = f"{prefix}/{path.relative_to(root).as_posix()}"
            if remote_name in seen:
                continue
            seen.add(remote_name)
            items.append((path, remote_name))
    return items


def cmd_create(args: argparse.Namespace) -> int:
    token, account = _token(), _account()
    body: dict = {"id": args.id}
    if args.r2_bucket:
        # R2 数据源模式需另行配置 service API token（token_id），见 runbook；默认走 Items 上传模式。
        body.update({"type": "r2", "source": args.r2_bucket, "token_id": args.r2_token_id})
    with _client(token) as client:
        resp = client.post(_instances_collection_url(account), json=body)
        data = resp.json()
        ok = resp.is_success and data.get("success", False)
        if ok:
            print(f"OK: create id={args.id} -> {data.get('result', {}).get('id', '')}")
        else:
            # fail-visible：HTTP 状态 + 原始响应体都打出来，便于定位鉴权/权限问题
            print(f"FAIL: create id={args.id} HTTP {resp.status_code}")
            print(f"  body: {resp.text[:500]}")
        return 0 if ok else 1


def cmd_upload(args: argparse.Namespace) -> int:
    # dry-run 纯本地文件列举，不需要凭据
    token, account = ("", "") if args.dry_run else (_token(), _account())
    roots = [Path(p).resolve() for p in (args.roots or [])]
    if not roots:
        roots = [Path(__file__).resolve().parent.parent / "docs"]  # 默认 quant-board/docs
    for extra in args.extra_root or []:
        roots.append(Path(extra).resolve())
    items = collect_markdown(roots)
    print(f"共 {len(items)} 个 markdown 待上传（roots={[str(r) for r in roots]}）")
    if args.dry_run:
        for path, remote in items:
            print(f"  [dry-run] {remote}  <-  {path}")
        return 0
    uploaded, failed = 0, []
    with _client(token) as client:
        for i, (path, remote) in enumerate(items):
            last_err = ""
            for attempt in range(args.retries + 1):
                try:
                    resp = client.post(
                        _instance_url(account, args.id, "items"),
                        files={"file": (remote, path.read_bytes(), "text/markdown")},
                    )
                except httpx.HTTPError as exc:  # 超时/连接错误同路重试，不中断整批
                    last_err = f"{type(exc).__name__}: {exc}"
                    if attempt < args.retries:
                        time.sleep(5 * (attempt + 1))
                    continue
                if resp.is_success:
                    uploaded += 1
                    last_err = ""
                    break
                last_err = f"HTTP {resp.status_code} {resp.text[:200]}"
                if resp.status_code == 503 and attempt < args.retries:
                    time.sleep(5 * (attempt + 1))  # 503 退避：5s/10s/15s
                    continue
            if last_err:
                failed.append((remote, last_err))
                print(f"[fail] {remote}: {last_err}")
            if args.delay and i < len(items) - 1:
                time.sleep(args.delay)
    print(f"上传完成：成功 {uploaded} / 失败 {len(failed)} / 总数 {len(items)}（AI Search 自动索引，稍后用 stats 查进度）")
    return 0 if not failed else 1


def cmd_stats(args: argparse.Namespace) -> int:
    with _client(_token()) as client:
        resp = client.get(_instance_url(_account(), args.id, "stats"))
        data = resp.json()
        print(resp.text)
        return 0 if resp.is_success and data.get("success", False) else 1


def cmd_search(args: argparse.Namespace) -> int:
    with _client(_token()) as client:
        resp = client.post(
            _instance_url(_account(), args.id, "search"),
            json={"messages": [{"role": "user", "content": args.query}]},
        )
        print(resp.text)
        return 0 if resp.is_success else 1


def main() -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                try:
                    stream.reconfigure(encoding="utf-8", errors="replace")
                except Exception:
                    pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create", help="创建 AI Search 实例（默认 Items 上传模式）")
    p.add_argument("--id", required=True)
    p.add_argument("--r2-bucket", help="可选：改为 R2 数据源模式")
    p.add_argument("--r2-token-id", help="R2 模式的 service API token id")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("upload", help="上传 markdown 到实例（AI Search 自动索引）")
    p.add_argument("--id", required=True)
    p.add_argument("--roots", nargs="*", help="markdown 根目录列表，默认 quant-board/docs")
    p.add_argument("--extra-root", action="append", help="追加根目录（可多次），如仓库根 docs/")
    p.add_argument("--dry-run", action="store_true", help="只列出将上传的文件，不发请求")
    p.add_argument("--delay", type=float, default=0.3, help="每文件间隔秒数（默认 0.3，防限流）")
    p.add_argument("--retries", type=int, default=3, help="503 自动重试次数（退避 5/10/15s）")
    p.set_defaults(func=cmd_upload)

    p = sub.add_parser("stats", help="查看索引进度")
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("search", help="检索（语义搜索，返回相关段落）")
    p.add_argument("--id", required=True)
    p.add_argument("query")
    p.set_defaults(func=cmd_search)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
