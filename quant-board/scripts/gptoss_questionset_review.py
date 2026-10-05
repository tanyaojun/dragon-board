# -*- coding: utf-8 -*-
"""GPT-OSS-120B 题目集研讨直连脚本（绕开 pi agent 链，纯 chat 一问一答落盘）。

背景（2026-10-05 实证）：pi 的 openai-completions 通道对 CF gpt-oss 存在结构性不兼容——
①会话历史带 thinking 块时 assistant content 重放为数组（CF schema 只收字符串，code 5006）；
②工具调用后的 assistant 消息 content=null 也被 CF 拒——pi 里多轮/工具链/中断重试必炸。
本脚本只发 [system, user] 两条字符串消息 + reasoning_effort，不提供工具、零历史重放，
规避全部 schema 雷；reasoning=high 得以保留（pi 通道做不到）。

用法（Git Bash，quant-board 目录）：
  export CLOUDFLARE_API_KEY=<key>
  python scripts/gptoss_questionset_review.py --prompt <提示词.txt> --out <输出.md>
  cat <提示词.txt> | python scripts/gptoss_questionset_review.py --out <输出.md>

成本：≈$0.005/次（语料 7-12k input + 2-5k output，workers-ai 计费口径见
docs/hotlist-jev/reasoning-corpus-jev-questionset.md §5）。
红线：模型输出不构成生产改动授权；产出必须经人工审定并落 pilot 预登记后才可开火。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ACCOUNT_ID = "921cf15176f84c90ea49865334af32c6"  # pi models.json workers-ai baseUrl 同源（非机密标识）
MODEL = "@cf/openai/gpt-oss-120b"
GATEWAY_ID = "pi-geteway"  # 与 pi 配置同一 AI Gateway，日志/缓存集中可见

DEFAULT_SYSTEM = (
    "你是 LLM 评估系统（结构化决策模型）的题目集（question set）设计专家。\n"
    "遵守项目归因纪律：输出偏差时归因顺序固定 ①原料/语料供给 → ②题目/判据设计 →\n"
    "③协议与解析层 → 最后才是方案重设计。任何题目改动建议必须配套：\n"
    "pilot 样本与窗口、预登记门判据（可量化）、人工抽验方案、成本估算（tokens）、回退方式。\n"
    "禁止建议绕过 pilot 直接改生产题目集。"
)


def _post(url: str, payload: dict, api_key: str, use_gateway: bool, timeout: int) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if use_gateway:
        headers["cf-aig-gateway-id"] = GATEWAY_ID
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="GPT-OSS-120B 题目集研讨直连（无工具/无历史/effort 可调）")
    ap.add_argument("--prompt", help="提示词文件路径；缺省读 stdin")
    ap.add_argument("--out", required=True, help="输出 markdown 路径")
    ap.add_argument("--system", default=None, help="自定义 system 文本文件；缺省用语料包 §5 system；--no-system 关闭")
    ap.add_argument("--no-system", action="store_true")
    ap.add_argument("--effort", choices=("low", "medium", "high"), default="high")
    ap.add_argument("--timeout", type=int, default=600, help="单次请求超时秒（high 推理 12k input 建议 ≥300）")
    ap.add_argument("--no-gateway", action="store_true", help="不走 AI Gateway 直连")
    args = ap.parse_args()

    api_key = os.environ.get("CLOUDFLARE_API_KEY", "").strip()
    if not api_key:
        print("缺 CLOUDFLARE_API_KEY 环境变量", file=sys.stderr)
        return 1

    if args.prompt:
        with open(args.prompt, encoding="utf-8") as f:
            user_text = f.read()
    else:
        user_text = sys.stdin.read()
    user_text = user_text.strip()
    if not user_text:
        print("提示词为空（--prompt 或 stdin）", file=sys.stderr)
        return 1

    messages: list[dict] = []
    if not args.no_system:
        if args.system:
            with open(args.system, encoding="utf-8") as f:
                messages.append({"role": "system", "content": f.read().strip()})
        else:
            messages.append({"role": "system", "content": DEFAULT_SYSTEM})
    messages.append({"role": "user", "content": user_text})

    url = (f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/v1/chat/completions")
    payload = {"model": MODEL, "messages": messages, "reasoning_effort": args.effort, "stream": False}

    t0 = time.time()
    try:
        body = _post(url, payload, api_key, use_gateway=not args.no_gateway, timeout=args.timeout)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:800]
        print(f"HTTP {e.code}: {detail}", file=sys.stderr)
        return 1
    elapsed = time.time() - t0

    choices = body.get("choices") or []
    content = (choices[0].get("message") or {}).get("content") if choices else None
    usage = body.get("usage") or {}
    if not content:
        print(f"响应无 content：{json.dumps(body, ensure_ascii=False)[:600]}", file=sys.stderr)
        return 1

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"完成：{args.out}")
    print(f"model={body.get('model')} | input={usage.get('prompt_tokens')} output={usage.get('completion_tokens')} "
          f"tokens | effort={args.effort} | {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
