# jev-bridge

QuantBoard 后端调用 Cloudflare `typesafe/jev` 的唯一通道（REST 直调已证死锁，见
`quant-board/docs/hotlist-jev/hotlist-jev-sentiment-design.md` §10）。

## 部署（Git Bash）

```bash
cd quant-board/workers/jev-bridge
export CLOUDFLARE_API_TOKEN=<Workers Scripts:Edit + Workers AI:Edit 的令牌>
export CLOUDFLARE_ACCOUNT_ID=<帐户ID>
npx -y wrangler@4 deploy
python -c "import secrets;print(secrets.token_hex(16))"   # 生成桥令牌
echo "<桥令牌>" | npx -y wrangler@4 secret put BRIDGE_TOKEN
```

部署输出会给出 `https://jev-bridge.<子域>.workers.dev`。冒烟：

```bash
curl https://jev-bridge.<子域>.workers.dev/health
```

## 接口

- `GET /health` → `{ok:true}`（无鉴权，仅探活）
- `POST /evaluate`，头 `x-bridge-token: <BRIDGE_TOKEN>`，体 `{"payload": {state, questions}}`
  → `{ok:true, latencyMs, result:{model, answers}}`；失败 `{ok:false, errorCode, errorDetail?}`
