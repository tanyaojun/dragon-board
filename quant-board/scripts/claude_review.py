# -*- coding: utf-8 -*-
"""Claude（cloudflare-ai 网关转售）语料研讨直连脚本——anthropic-messages 协议版 gptoss。

背景（2026-10-07 voting-signals 轮）：GPT-OSS 复述层干净但提案层幻觉率高（P2 撞已证伪
清单 + 预期数字凭空），按语料 §9.5 既定升级路径换 Claude；用户裁决本轮流向
claude-sonnet-5（$2/$10 per M，Opus 的 40%/20%），不走 Opus。

通道：pi 的 cloudflare-ai provider（AI Gateway /anthropic 路由），配置与密钥**单源**读
~/.pi/agent/models.json（不复制到本仓库任何位置）；--model 选网关内模型 id。

用法（Git Bash，任意目录）：
  python scripts/claude_review.py --prompt <提示词.txt> --out <输出.md> \
      [--system <system.txt>] [--model claude-sonnet-5] [--max-tokens 16000]

成本：打印实耗 tokens 并按 models.json cost 字段折算美元。
红线：模型输出不构成生产改动授权；产出必须经人工承重墙审定并落预登记后才可开火。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROVIDER_NAME = "cloudflare-ai"
DEFAULT_MODEL = "claude-sonnet-5"
ANTHROPIC_VERSION = "2023-06-01"
MODELS_JSON = Path.home() / ".pi" / "agent" / "models.json"


def _load_provider() -> dict:
    """读 pi cloudflare-ai provider 配置（baseUrl/apiKey/headers），密钥单源不复制。"""
    if not MODELS_JSON.exists():
        raise FileNotFoundError(f"缺 {MODELS_JSON}（pi cloudflare-ai provider 配置）")
    cfg = json.loads(MODELS_JSON.read_text(encoding="utf-8"))
    provider = (cfg.get("providers") or {}).get(PROVIDER_NAME)
    if not provider or not provider.get("baseUrl") or not provider.get("apiKey"):
        raise ValueError(f"{MODELS_JSON} 无可用 {PROVIDER_NAME} provider（baseUrl/apiKey）")
    return provider


def _model_cost(provider: dict, model_id: str) -> dict:
    for m in provider.get("models") or []:
        if m.get("id") == model_id:
            return m.get("cost") or {}
    return {}


def _post(url: str, payload: dict, api_key: str, extra_headers: dict, timeout: int) -> dict:
    """经 curl 子进程发请求——gateway.ai.cloudflare.com 边缘按 TLS 签名拦 python-urllib
    （HTTP 403 code 1010，2026-10-07 实测），curl 签名可过；参数走 argv 不经 shell。"""
    import subprocess

    body = json.dumps(payload).encode("utf-8")
    cmd = [
        "curl", "-sS", "-m", str(timeout), "-X", "POST", url,
        "-H", f"x-api-key: {api_key}",
        "-H", f"anthropic-version: {ANTHROPIC_VERSION}",
        "-H", "Content-Type: application/json",
        "--data-binary", "@-",
    ]
    for k, v in extra_headers.items():
        if isinstance(v, str):
            cmd += ["-H", f"{k}: {v}"]
    result = subprocess.run(cmd, input=body, capture_output=True, check=True)
    return json.loads(result.stdout.decode("utf-8"))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Claude（cloudflare-ai 网关）语料研讨直连（anthropic-messages 协议）")
    ap.add_argument("--prompt", help="提示词文件路径；缺省读 stdin")
    ap.add_argument("--out", required=True, help="输出 markdown 路径")
    ap.add_argument("--system", default=None, help="自定义 system 文本文件")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"网关模型 id（默认 {DEFAULT_MODEL}；见 models.json cloudflare-ai.models）")
    ap.add_argument("--max-tokens", type=int, default=16000, help="输出上限 tokens")
    ap.add_argument("--timeout", type=int, default=600, help="单次请求超时秒")
    args = ap.parse_args()

    provider = _load_provider()
    base_url = provider["baseUrl"].rstrip("/")

    if args.prompt:
        with open(args.prompt, encoding="utf-8") as f:
            user_text = f.read()
    else:
        user_text = sys.stdin.read()
    user_text = user_text.strip()
    if not user_text:
        print("提示词为空（--prompt 或 stdin）", file=sys.stderr)
        return 1

    payload: dict = {"model": args.model, "max_tokens": args.max_tokens,
                     "messages": [{"role": "user", "content": user_text}]}
    if args.system:
        with open(args.system, encoding="utf-8") as f:
            payload["system"] = f.read().strip()

    t0 = time.time()
    try:
        body = _post(f"{base_url}/v1/messages", payload, provider["apiKey"],
                     provider.get("headers") or {}, timeout=args.timeout)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:800]
        print(f"HTTP {e.code}: {detail}", file=sys.stderr)
        return 1
    elapsed = time.time() - t0

    if body.get("type") == "error":
        print(f"API error: {json.dumps(body, ensure_ascii=False)[:600]}", file=sys.stderr)
        return 1

    content_blocks = body.get("content") or []
    text = "\n\n".join(b.get("text", "") for b in content_blocks if b.get("type") == "text").strip()
    if not text:
        print(f"响应无 text 块：{json.dumps(body, ensure_ascii=False)[:600]}", file=sys.stderr)
        return 1

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)

    usage = body.get("usage") or {}
    cost = _model_cost(provider, args.model)
    in_tok = usage.get("input_tokens") or 0
    out_tok = usage.get("output_tokens") or 0
    usd = (in_tok / 1e6) * cost.get("input", 0) + (out_tok / 1e6) * cost.get("output", 0)
    print(f"完成：{args.out}")
    print(f"model={body.get('model')} | input={in_tok} output={out_tok} tokens | "
          f"stop_reason={body.get('stop_reason')} | ≈${usd:.3f} | {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
