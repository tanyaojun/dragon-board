# -*- coding: utf-8 -*-
"""relay_page【板块行情·行业】页签空态自愈守卫（2026-11-11 用户报障修复）。

报障：行业页签恒空态。根因链：881 只在 kplBootstrap 引导时并入订阅，且依赖引导那一刻
plate-tree 读口可用（collector 重启窗口期该口 ok:false 而排行口独立可用 → 引导「成功」
但漏行业）；旧看门狗只看 items.size≥20，到流后永不复查行业覆盖；多页签订阅替换语义
也会抹掉行业 → 空态永久化。

本测试零网络/零 jev（AGENTS §1.2-7）：
1. 静态守卫：引导记录 universeHy、quotes 记录服务端 ts、空态走诊断出口+手动重新引导；
2. 行为守卫：把 kplHyState/kplHyEmptyNote/kplHyRepair/kplHyRetry/kplWatchdogTick 真实
   源码抽出在 node 里跑（stub KPL/STATE/jpost），覆盖：非交易时段回放不算到流（不刷
   补引导）、有流缺行业 30s 节流补引导封顶 3 次后结构化透出、881 到流复位、引导时树
   未就绪无流也先订上、merge 不抹别页个股、历史模式空态口径。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_PAGE = Path(__file__).resolve().parents[2] / "backend" / "relay_page" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return _PAGE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js(html: str) -> str:
    m = re.search(r"<script>([\s\S]*)</script>", html)
    assert m, "relay_page 应含唯一 <script> 块"
    return m.group(1)


def _fn(js: str, name: str) -> str:
    """取一个顶层函数文本（花括号配对截断，不向下一个函数溢出）。"""
    start = js.index(f"function {name}(")
    brace = js.index("{", start)
    depth = 0
    for i in range(brace, len(js)):
        ch = js[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return js[start : i + 1]
    raise AssertionError(f"未找到 {name} 的函数结尾")


def test_bootstrap_records_hy_coverage(js: str):
    boot = _fn(js, "kplBootstrap")
    assert "let hyCount = 0;" in boot, "本轮行业覆盖用局部计数"
    assert "KPL.universeHy = hyCount;" in boot, "引导成功后才落行业覆盖计数"
    assert "KPL.universeHy = 0;" not in boot, "R1：引导开头不得清零（失败重引导会抹掉旧覆盖误触补引导）"


def test_new_session_resets_hy_repair_budget(js: str):
    m = re.search(r"case 'auth':(.{0,400}?)case 'status':", js, re.S)
    assert m, "kplHandleEvent 应含 auth 分支"
    assert "KPL.hyRepairN = 0; KPL.hyNote = '';" in m.group(1), \
        "R3：新会话 auth ok 应复位补引导预算（封顶不跨会话存续）"


def test_watchdog_repair_requires_bootstrapped_universe(js: str):
    tick = _fn(js, "kplWatchdogTick")
    assert "hy.needRepair && KPL.universeIds.length &&" in tick, \
        "R2：引导未成功时不得发仅行业清单（旧 collector 替换语义会抹掉订阅面）"


def test_watchdog_retries_plate_tree_when_missing(js: str):
    """R5：树瞬态失败（502/collector 重启）后 staying 页内也要有人重试树读。"""
    tick = _fn(js, "kplWatchdogTick")
    assert "if (!KPL.plateTree) kplFetchPlateTree();" in tick, "看门狗应在树缺位时每 10s 重试树读"


def test_empty_note_refreshed_after_guide_and_repair(js: str):
    """R4：无流时段没有 quotes 事件触发重渲染，引导/补引导/手动复位后必须主动刷新空态。"""
    assert "kplRenderSectors();" in _fn(js, "kplBootstrap"), "引导成功后应刷新空态诊断"
    assert "kplRenderSectors();" in _fn(js, "kplHyRepair"), "补引导成功后应刷新空态诊断"
    assert "kplRenderSectors();" in _fn(js, "kplHyRetry"), "手动复位后应刷新空态诊断"


def test_quotes_records_server_ts_and_resets_repair(js: str):
    m = re.search(r"case 'quotes':(.{0,900}?)case 'stock_quotes':", js, re.S)
    assert m, "kplHandleEvent 应含 quotes 分支"
    case = m.group(1)
    assert "KPL.lastQuotesTs = ev.ts;" in case, "quotes 应记录服务端事件 ts（回放不算到流）"
    assert "KPL.hyRepairN = 0; KPL.hyNote = '';" in case, "881 到流应复位补引导计数/原因"


def test_hy_empty_state_uses_diagnostic_and_manual_retry(js: str):
    render = _fn(js, "kplRenderSectors")
    assert "kplHyEmptyNote(kplHyState())" in render, "行业空态应走结构化诊断出口"
    assert 'onclick="kplHyRetry()"' in render, "行业空态应给手动重新引导出口"
    assert "setInterval(kplWatchdogTick, 10000);" in js, "看门狗应复用可测的 tick 函数"


_NODE_STUBS = r"""
const KPL_API = 'http://stub/api/kpl';
let NOW = 1700000000000;
Date.now = () => NOW;
const calls = [];      // jpost 订阅请求记录
const banners = [];
let bootstrapCalls = 0;
const STATE = {view: 'kpl'};
function jpost(url, body){ calls.push(body); return Promise.resolve({ok: true}); }
function kplBanner(msg, kind){ banners.push([msg, kind || '']); }
function kplBootstrap(){ bootstrapCalls++; }
let renders = 0;
function kplRenderSectors(){ renders++; }   // R4：引导/补引导后空态诊断即时刷新
function kplFetchPlateTree(){ return Promise.resolve(); }   // R5：看门狗树读重试 stub
function kplConnect(){ throw new Error('不应触发重连（items 已≥20）'); }
function kplEnsureRunning(){ throw new Error('不应触发拉起（running=true）'); }
function mkKPL(over){
  const items = new Map();
  for (let i = 0; i < 20; i++) items.set('8010' + i, {id: '8010' + i, name: '板' + i, quotas: []});
  return Object.assign({
    ws: {readyState: 1}, mode: 'live', items,
    plateTree: {'801001': {parent: '0'}, '881001': {parent: '0'}, '881002': {parent: '0'}},
    universeIds: ['801001'], universeHy: 2,
    lastQuotesTs: 0, hyRepairAt: 0, hyRepairN: 0, hyNote: '',
    bootstrapping: false, status: {running: true},
  }, over || {});
}
let KPL = mkKPL();
let kplStallCount = 0;   // 页内同名变量：提取仅取函数体，stub 显式声明（ESM 下未声明赋值会 ReferenceError）
const flush = () => new Promise(r => setImmediate(r));
const results = {};
"""


def _node_script(js: str) -> str:
    parts = []
    for name in ("kplHyState", "kplHyEmptyNote", "kplHyRepair", "kplHyRetry", "kplWatchdogTick"):
        body = _fn(js, name)
        if name == "kplHyRepair" and not body.startswith("async"):
            body = "async " + body   # 花括号截取从 function 起步，async 前缀需补回
        parts.append(body)
    fns = "\n".join(parts)
    scenarios = r"""
(async () => {
  // S1 非交易时段：回放旧 ts 不算到流 → 不刷补引导；空态说明无流+引导数
  KPL = mkKPL({lastQuotesTs: NOW / 1000 - 3600});
  kplWatchdogTick(); await flush();
  results.s1 = {calls: calls.length, needRepair: kplHyState().needRepair,
                note: kplHyEmptyNote(kplHyState())};
  // S2 有流但 881 缺流：30s 节流补引导（merge），封顶 3 次后结构化透出
  calls.length = 0;
  KPL = mkKPL({lastQuotesTs: NOW / 1000 - 5});
  kplWatchdogTick(); await flush();
  const first = calls[0];
  KPL.lastQuotesTs = NOW / 1000 - 5; kplWatchdogTick(); await flush();   // 10s 后：节流内不重发
  const nAt10s = calls.length;
  NOW += 31000; KPL.lastQuotesTs = NOW / 1000 - 5; kplWatchdogTick(); await flush();   // 模拟持续到流
  NOW += 31000; KPL.lastQuotesTs = NOW / 1000 - 5; kplWatchdogTick(); await flush();
  const nAt3 = calls.length;
  NOW += 31000; KPL.lastQuotesTs = NOW / 1000 - 5; kplWatchdogTick(); await flush();   // 第 4 窗口：封顶不再发
  results.s2 = {first, nAt10s, nAt3, nAfterCap: calls.length,
                hyNote: KPL.hyNote, note: kplHyEmptyNote(kplHyState()),
                universeHy: KPL.universeHy, renders};
  // S3 881 到流：不需补引导
  calls.length = 0;
  KPL = mkKPL({lastQuotesTs: NOW / 1000 - 5});
  KPL.items.set('881001', {id: '881001', name: '行业', quotas: []});
  kplWatchdogTick(); await flush();
  results.s3 = {calls: calls.length, needRepair: kplHyState().needRepair,
                received: kplHyState().received};
  // S4 引导时树未就绪（universeHy=0）+ 无流：也先把行业订上，且只订一次
  calls.length = 0;
  KPL = mkKPL({universeHy: 0, lastQuotesTs: NOW / 1000 - 3600});
  kplWatchdogTick(); await flush();
  const n1 = calls.length;
  NOW += 31000; kplWatchdogTick(); await flush();
  results.s4 = {n1, n2: calls.length, universeHy: KPL.universeHy,
                merge: calls[0] && calls[0].merge};
  // S5 merge 不抹别页已订个股（universe 含别页并入的代码）
  calls.length = 0;
  KPL = mkKPL({universeIds: ['801001', '600000'], lastQuotesTs: NOW / 1000 - 5});
  kplWatchdogTick(); await flush();
  results.s5 = {ids: calls[0] && calls[0].stock_ids};
  // S6 历史模式：tick 不动作；空态口径=仅实时模式
  calls.length = 0;
  KPL = mkKPL({mode: 'history'});
  kplWatchdogTick(); await flush();
  results.s6 = {calls: calls.length, note: kplHyEmptyNote(kplHyState())};
  // S8 引导从未成功（universeIds 空）：不发仅行业清单，交给 stall 路径全量引导
  calls.length = 0;
  KPL = mkKPL({universeIds: [], universeHy: 0, lastQuotesTs: NOW / 1000 - 5});
  kplWatchdogTick(); await flush();
  results.s8 = {calls: calls.length};
  // S7 手动重新引导：复位计数并下发 merge；宇宙为空时回退全量引导
  calls.length = 0; bootstrapCalls = 0;
  KPL = mkKPL({hyRepairN: 3, hyNote: 'x', lastQuotesTs: NOW / 1000 - 5});
  kplHyRetry(); await flush();
  const manual = {n: calls.length, merge: calls[0] && calls[0].merge,
                  reset: KPL.hyRepairN === 0 && KPL.hyNote === ''};
  KPL = mkKPL({universeIds: []});
  kplHyRetry(); await flush();
  results.s7 = {manual, bootstrapCalls};
  console.log(JSON.stringify(results));
})().catch(e => { console.error(e); process.exit(1); });
"""
    return _NODE_STUBS + fns + scenarios


def test_hy_selfheal_behavior_in_node(js: str, tmp_path):
    if shutil.which("node") is None:
        pytest.skip("node 不可用")
    script = tmp_path / "hy_guard.cjs"   # .cjs：不依赖运行目录 package.json 的 module 类型
    script.write_text(_node_script(js), encoding="utf-8")
    cp = subprocess.run(["node", str(script)], capture_output=True, timeout=60,
                        encoding="utf-8", errors="replace")
    assert cp.returncode == 0, f"node 执行失败：{cp.stderr}"
    r = json.loads(cp.stdout.strip().splitlines()[-1])
    # S1：回放不算到流 → 零补引导；空态显式无流原因与引导覆盖
    assert r["s1"]["calls"] == 0 and r["s1"]["needRepair"] is False
    assert "无实时行情到流" in r["s1"]["note"] and "2/2" in r["s1"]["note"]
    # S2：merge 补引导含行业+原宇宙；30s 节流；封顶 3 次；超限结构化透出
    s2 = r["s2"]
    assert s2["first"]["merge"] is True
    assert "881001" in s2["first"]["stock_ids"] and "801001" in s2["first"]["stock_ids"]
    assert s2["nAt10s"] == 1 and s2["nAt3"] == 3 and s2["nAfterCap"] == 3
    assert "上游仍未推" in s2["hyNote"] and s2["note"] == s2["hyNote"]
    assert s2["renders"] >= 3, "R4：每次补引导成功都应刷新空态诊断"
    # S3：881 到流 → 自愈闭环复位
    assert r["s3"]["calls"] == 0 and r["s3"]["needRepair"] is False and r["s3"]["received"] == 1
    # S4：树曾未就绪 → 无流也先订上行业，且不再重复刷
    assert r["s4"]["n1"] == 1 and r["s4"]["n2"] == 1
    assert r["s4"]["universeHy"] == 2 and r["s4"]["merge"] is True
    # S5：merge 保留别页个股
    assert "600000" in r["s5"]["ids"] and "881002" in r["s5"]["ids"]
    # S6：历史模式口径不变
    assert r["s6"]["calls"] == 0 and "仅实时模式" in r["s6"]["note"]
    # S8：引导未成功 → 零补引导（R2）
    assert r["s8"]["calls"] == 0
    # S7：手动出口复位+merge；宇宙空回退全量引导
    assert r["s7"]["manual"]["n"] == 1 and r["s7"]["manual"]["merge"] is True
    assert r["s7"]["manual"]["reset"] is True and r["s7"]["bootstrapCalls"] == 1


def test_page_script_syntax_ok(js: str, tmp_path):
    if shutil.which("node") is None:
        pytest.skip("node 不可用")
    script = tmp_path / "page_script.js"
    script.write_text(js, encoding="utf-8")
    cp = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True, timeout=60)
    assert cp.returncode == 0, f"页面脚本语法错误：{cp.stderr}"
