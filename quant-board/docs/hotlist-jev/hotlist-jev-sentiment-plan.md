# Jev 热榜情绪轨道 — 阶段 0 可行性实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 验证 typesafe/jev 在 Cloudflare 免费计划上可被 QuantBoard 后端调用（Worker 桥链路），产出 Go/No-Go 结论与实测数据（延迟/消耗/中文支持）。

**Architecture:** REST 直调 jev 已证死锁（网关强制 messages / 模型拒绝 messages）；唯一官方通道是 Worker 绑定 `env.AI.run`。本阶段部署一个约 30 行的 jev-bridge Worker（secret 鉴权 + /evaluate 路由），用假 state 探测全部三种 question schema，把结果写回 design 文档。阶段 1（回放验证）与阶段 2（盘中旁观）待本阶段 Go 后各出独立计划。

**Tech Stack:** Cloudflare Workers + AI binding、wrangler v4（npx 临时拉起，不进仓库依赖）、Python urllib 探测脚本（不新增后端依赖）、FastAPI 后端本阶段不改代码。

**Spec:** `quant-board/docs/hotlist-jev/hotlist-jev-sentiment-design.md`（2026-09-28，D1/D2/D3 已确认）

**Go/No-Go 判据（Task 5 用）:**
- GO = 桥可达 + `env.AI.run('typesafe/jev')` 在 Workers Free 计划返回 answers（无 Free-plan 拦截、无绑卡要求）+ 中文 instructions 判别有效（紧急文本 noul>0.7 且平静文本 noul<0.3）+ 延迟 <5s + choice 概率非退化（非单点 1.0/0.0 全排）。
- NO-GO = 任何一步要求升级付费/绑卡，或模型返回系统性无效（answers 恒缺/恒定），如实记录后止损，不硬绕。

---

### Task 1: REST 终验 — 用尽最后四种直调变体

**Files:** 无新文件（探测脚本直接在 Git Bash heredoc 执行）

- [ ] **Step 1: 运行四变体探测**

```bash
cd /c/Users/Think/.pi/agent && TOKEN=$(python -c "import json;print(json.load(open('models.json',encoding='utf-8'))['providers']['cloudflare']['apiKey'])") && ACC=921cf15176f84c90ea49865334af32c6 && python - "$TOKEN" "$ACC" <<'EOF'
import json, sys, urllib.request
token, acc = sys.argv[1], sys.argv[2]
base = f"https://api.cloudflare.com/client/v4/accounts/{acc}"
QUESTIONS = {
    "is_urgent": {"type": "noul", "instructions": "这段话是否表达紧急情绪？"},
}
STATE = "我的收益打款失败三天了，立刻解决！"

def post(path, payload):
    req = urllib.request.Request(f"{base}{path}", method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.data = json.dumps(payload).encode()
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return "OK: " + json.dumps(json.loads(r.read()), ensure_ascii=False)[:200]
    except urllib.error.HTTPError as e:
        try: return "ERR: " + str(json.loads(e.read()).get("errors"))[:220]
        except Exception: return f"HTTP {e.code}"

print("A /ai/v1/responses + state/questions:",
      post("/ai/v1/responses", {"model": "typesafe/jev", "state": STATE, "questions": QUESTIONS}))
print("B chat + messages:[]       :",
      post("/ai/v1/chat/completions", {"model": "typesafe/jev", "messages": [], "state": STATE, "questions": QUESTIONS}))
print("C chat + messages,无stream :",
      post("/ai/v1/chat/completions", {"model": "typesafe/jev", "messages": [{"role": "user", "content": "e"}], "state": STATE, "questions": QUESTIONS}))
print("D /ai/run/typesafe/jev     :",
      post("/ai/run/typesafe/jev", {"state": STATE, "questions": QUESTIONS}))
EOF
```

Expected：A/B/C/D 至少一种出现 `"answers"` 即 REST 可用 → 跳过 Task 2/3 直接 Task 4 改走 REST；四种全失败（预期：messages 死锁复现 + 7000 无路由）→ 确认唯一通道为 Worker 绑定，进 Task 2。

- [ ] **Step 2: 把四变体结果追加进 design.md §10**

一行一条，格式 `REST 终验(2026-09-28)：A responses=…；B messages:[]=…；C …；D …`。不 commit（Task 5 统一 commit）。

---

### Task 2: Worker 桥代码落库

**Files:**
- Create: `quant-board/workers/jev-bridge/worker.js`
- Create: `quant-board/workers/jev-bridge/wrangler.toml`
- Create: `quant-board/workers/jev-bridge/README.md`

- [ ] **Step 1: 写 worker.js**

```javascript
// jev-bridge: QuantBoard 后端 → typesafe/jev 的唯一通道（REST 直调已证死锁，见 design.md §10）
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return Response.json({ ok: true, model: "typesafe/jev" });
    }
    if (request.method !== "POST" || url.pathname !== "/evaluate") {
      return Response.json({ ok: false, errorCode: "not_found" }, { status: 404 });
    }
    if (request.headers.get("x-bridge-token") !== env.BRIDGE_TOKEN) {
      return Response.json({ ok: false, errorCode: "denied" }, { status: 401 });
    }
    let payload;
    try {
      payload = (await request.json()).payload;
    } catch {
      return Response.json({ ok: false, errorCode: "bad_json" }, { status: 400 });
    }
    if (!payload || typeof payload !== "object" || !payload.state || !payload.questions) {
      return Response.json({ ok: false, errorCode: "bad_payload" }, { status: 400 });
    }
    const t0 = Date.now();
    try {
      const result = await env.AI.run("typesafe/jev", payload);
      return Response.json({ ok: true, latencyMs: Date.now() - t0, result });
    } catch (e) {
      return Response.json(
        { ok: false, errorCode: "model_error", errorDetail: String(e).slice(0, 500), latencyMs: Date.now() - t0 },
        { status: 502 }
      );
    }
  },
};
```

- [ ] **Step 2: 写 wrangler.toml**

```toml
name = "jev-bridge"
main = "worker.js"
compatibility_date = "2026-09-01"
workers_dev = true

[ai]
binding = "AI"
```

- [ ] **Step 3: 写 README.md**

```markdown
# jev-bridge

QuantBoard 后端调用 Cloudflare `typesafe/jev` 的唯一通道（REST 直调已证死锁，见
`quant-board/docs/hotlist-jev/hotlist-jev-sentiment-design.md` §10）。

## 部署（Git Bash）

​```bash
cd quant-board/workers/jev-bridge
export CLOUDFLARE_API_TOKEN=<Workers Scripts:Edit + Workers AI:Edit 的令牌>
export CLOUDFLARE_ACCOUNT_ID=<帐户ID>
npx -y wrangler@4 deploy
python -c "import secrets;print(secrets.token_hex(16))"   # 生成桥令牌
echo "<桥令牌>" | npx -y wrangler@4 secret put BRIDGE_TOKEN
​```

部署输出会给出 https://jev-bridge.<子域>.workers.dev 。冒烟：

​```bash
curl https://jev-bridge.<子域>.workers.dev/health
​```

## 接口

- `GET /health` → `{ok:true}`（无鉴权，仅探活）
- `POST /evaluate`，头 `x-bridge-token: <BRIDGE_TOKEN>`，体 `{"payload": {state, questions}}`
  → `{ok:true, latencyMs, result:{model, answers}}`；失败 `{ok:false, errorCode, errorDetail?}`
```

- [ ] **Step 4: Commit 桥代码**

```bash
git add quant-board/workers/jev-bridge/worker.js quant-board/workers/jev-bridge/wrangler.toml quant-board/workers/jev-bridge/README.md
git commit -m "feat(hotlist-jev): jev-bridge Worker 桥代码（阶段0）"
```

---

### Task 3: 部署与冒烟

**Files:** 无新文件

- [ ] **Step 1: 用现有令牌尝试 wrangler 部署**

```bash
cd /d/dragon-board/quant-board/workers/jev-bridge
export CLOUDFLARE_API_TOKEN=$(python -c "import json;print(json.load(open(r'C:\Users\Think\.pi\agent\models.json',encoding='utf-8'))['providers']['cloudflare']['apiKey'])")
export CLOUDFLARE_ACCOUNT_ID=921cf15176f84c90ea49865334af32c6
npx -y wrangler@4 deploy 2>&1 | tail -20
```

Expected 分支：
- **成功**：输出 `Uploaded jev-bridge` + workers.dev URL → Step 2。
- **403 / Authentication error / token does not have required scope**：令牌缺 `Workers Scripts:Edit` → **停下，向用户报告两条路**（①面板 My Profile→API Tokens→创建令牌，权限加 `帐户→Workers 脚本→编辑` + `帐户→Workers AI→编辑`，换新令牌重跑本步；②用户自己在面板 Workers→Create Worker 粘贴 Task 2 的 worker.js 并在 Settings 里绑 AI binding、设 BRIDGE_TOKEN 变量）。此为阶段 0 唯一用户阻塞点。

- [ ] **Step 2: 设置 BRIDGE_TOKEN secret 并冒烟**

```bash
BRIDGE_TOKEN=$(python -c "import secrets;print(secrets.token_hex(16))")
echo "$BRIDGE_TOKEN" | npx -y wrangler@4 secret put BRIDGE_TOKEN
curl -s https://jev-bridge.<部署输出的子域>.workers.dev/health
```

Expected：secret put 输出 Success；curl 返回 `{"ok":true,"model":"typesafe/jev"}`。把 `<子域>` 与 BRIDGE_TOKEN 记入本地（后续阶段 2 后端配置用，不进仓库）。

---

### Task 4: 假 state 全 schema 探测（noul/choice/score + 中文判别）

**Files:** 无新文件（结果写回 design.md）

- [ ] **Step 1: 探测已知 schema（noul + choice）与中文判别力**

```bash
BRIDGE_URL=https://jev-bridge.<子域>.workers.dev BRIDGE_TOKEN=<Step3.2的值> python - <<'EOF'
import json, os, urllib.request
url, token = os.environ["BRIDGE_URL"] + "/evaluate", os.environ["BRIDGE_TOKEN"]

def ev(state, questions, tag):
    req = urllib.request.Request(url, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-bridge-token", token)
    req.data = json.dumps({"payload": {"state": state, "questions": questions}}).encode()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
            print(f"[{tag}]", "OK" if d.get("ok") else "FAIL", json.dumps(d.get("result") or d, ensure_ascii=False)[:400])
    except urllib.error.HTTPError as e:
        print(f"[{tag}] HTTP{e.code}:", e.read().decode()[:300])

Q1 = {
    "is_urgent": {"type": "noul", "instructions": "这段话是否表达紧急情绪？"},
    "stage": {"type": "choice", "instructions": "当前短线市场情绪处于哪一档？",
              "criteria": {"ice": "冰点：赚钱效应殆尽，观望", "start": "启动：出现修复迹象",
                           "ferment": "发酵：赚钱效应扩散", "climax": "高潮：全面亢奋", "retreat": "退潮：高位集体走弱"}},
}
ev("我的收益打款失败三天了，现在立刻就要解决！！", Q1, "紧急文本")
ev("今天市场平稳，资金按计划逐步建仓，无异常。", Q1, "平静文本")
EOF
```

Expected：两条均 `OK` 且 answers 含 noul/choice；紧急文本 is_urgent 明显高于平静文本（判别力证据）；记录 latencyMs。

- [ ] **Step 2: 探测 score schema（三变体，取首个可用）**

```bash
BRIDGE_URL=... BRIDGE_TOKEN=... python - <<'EOF'
# 同上 ev()
BASE = {"type": "score", "instructions": "短线情绪温度 0-100 打分"}
ev(state=..., questions={"temperature": BASE}, tag="score-裸")
ev(state=..., questions={"temperature": {**BASE, "criteria": {"min": 0, "max": 100}}}, tag="score-criteria")
ev(state=..., questions={"temperature": {**BASE, "min": 0, "max": 100}}, tag="score-minmax")
EOF
```

Expected：恰一变体返回 score 值，其余报 schema 错——把可用写法记入 design.md §6。

- [ ] **Step 3: 五问全量组合冒烟**

state 用 design.md §5 的样例（lifecycle counts + 3 只股票行），questions=noul×2 + choice×1 + score×2（用 Step 2 可用写法）。Expected：一次调用全 answers 返回，记录 latencyMs、usage（响应若含 token/neuron 计量字段）。

- [ ] **Step 4: 结果写回 design.md**

§10 追加探测结论（score 可用写法、中文判别、latency/usage 实测值）；§11 勾销已决项。不 commit（Task 5 统一）。

---

### Task 5: Go/No-Go 结论落盘

**Files:**
- Modify: `quant-board/docs/hotlist-jev/hotlist-jev-sentiment-design.md`（§9 阶段 0 状态、§10 实测数据、§11 未决项勾销）
- Create: `quant-board/docs/hotlist-jev/phase0-feasibility-report.md`（如 GO 且结论较长；否则仅改 design.md）

- [ ] **Step 1: 按 Task 1-4 证据逐条对照 Go/No-Go 判据，写结论**
- [ ] **Step 2: 更新 design.md §9 阶段 0 状态为 GO/NO-GO + 日期**
- [ ] **Step 3: Commit**

```bash
git add quant-board/docs/hotlist-jev/
git commit -m "docs(hotlist-jev): 阶段0可行性结论（GO/NO-GO + 实测数据）"
```

- [ ] **Step 4: 向用户报告结论；GO 则提议阶段 1 计划，NO-GO 则如实陈述死因与止损点**

---

## Self-Review 记录

- Spec 覆盖：§4 桥→Task 2/3；§5/§6 schema→Task 4；§9 阶段 0→全计划；§10/§11 回写→Task 1.2/4.4/5.2。阶段 1-3 有独立计划门禁（spec §9），不在本计划。
- 占位符：无 TBD；Task 4.2 score 三变体本身即探测目的，非占位。
- 类型一致性：bridge 响应 `{ok, latencyMs, result|errorCode}` 与 README/后续 jev_client（阶段 2 计划）一致；`x-bridge-token`/`BRIDGE_TOKEN`/`/evaluate` 各任务一致。
