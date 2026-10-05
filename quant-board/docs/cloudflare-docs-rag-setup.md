# Cloudflare AI Search 文档 RAG 索引 Runbook（2026-10-05）

**目的**：把 `quant-board/docs/**`（含 `hotlist-jev/` 全部 jev/EOD 研究文档）建成 Cloudflare AI Search（原 AutoRAG）语义索引，推理/复盘时按需检索相关段落，解决超长语料塞不进单次上下文的问题（GPT-OSS-120B 128k 窗口对策）。
**工具**：`scripts/cloudflare_docs_rag.py`（仅依赖 quant-board venv 已有的 httpx）。
**产品关系**：AutoRAG 已升级为 AI Search，API 路径 `.../ai-search/namespaces/default/instances/...`（旧 `/autorag/rags/` 路径兼容保留）；索引/嵌入（bge-m3）/存储由 Cloudflare 托管，无需自建 Vectorize。

## 一、前置准备（一次性）

1. **建 API Token**：Dashboard → My Profile → API Tokens → Create Custom Token
   - 权限：`Account > AI Search:Edit` + `Account > AI Search:Run`
   - （若用 R2 数据源模式，另见官方 service API token 流程；本项目默认 Items 上传模式，不需要）
2. **配环境变量**（本机 shell / `.env.local`，不入仓）：
   ```powershell
   $env:CLOUDFLARE_API_TOKEN = "<token>"
   # CLOUDFLARE_ACCOUNT_ID 有默认值（项目已登记账户），一般无需设置
   ```
3. 与 pi 的 `workers-ai` provider 共用同一账户；token 权限互不重叠（pi 用 Workers AI 权限，本工具用 AI Search 权限），建议分两个 token。

## 二、建索引（三条命令）

```powershell
cd quant-board
# 1) 创建实例（Items 上传模式，无需 R2）
.\.venv\Scripts\python.exe scripts\cloudflare_docs_rag.py create --id dragon-board-docs

# 2) 预览要上传的文件（dry-run 零成本）
.\.venv\Scripts\python.exe scripts\cloudflare_docs_rag.py upload --id dragon-board-docs --dry-run

# 3) 正式上传（默认 quant-board/docs/**.md；追加仓库根 docs/ 用 --extra-root ../docs）
.\.venv\Scripts\python.exe scripts\cloudflare_docs_rag.py upload --id dragon-board-docs

# 4) 查索引进度（上传后异步索引）
.\.venv\Scripts\python.exe scripts\cloudflare_docs_rag.py stats --id dragon-board-docs
```

## 三、检索用法

```powershell
.\.venv\Scripts\python.exe scripts\cloudflare_docs_rag.py search --id dragon-board-docs "拥挤 score 终判 门判据"
```

- 响应结构：命中在 `result.chunks[]`，每条含 `score`（相关度 0-1，rrf 融合）、`text`（段落原文）、`item.key`（**来源文件名**）；`result.data` 不是命中列表。
- 索引是异步的：上传完成（`stats` 全部 completed）后检索才会逐步命中；189 文档全量索引约需 10-20 分钟。
- **终端编码**：git-bash 向 python 传中文 argv 会乱码（响应 `search_query` 回显可验证）；**用 PowerShell 跑中文查询**，或在脚本内直传字符串（已验证回显一致、命中正常）。
- 上传已内置防限流：`--delay`（默认 0.3s/文件）+ 503 自动退避重试（`--retries`，5/10/15s）；遇 `unable_to_connect_to_ai_search`（7017）属 CF 侧瞬时容量错误，重跑 `upload` 幂等补齐即可。

典型工作流（复盘/题目设计）：
1. 先 `search` 拉相关段落（几十条命中带来源文件名）；
2. 把命中段落 + 对应 `docs/hotlist-jev/reasoning-corpus-*.md` 语料包一起投给 GPT-OSS-120B（pi `/model`）；
3. 语料包找不到的细节再回源文档精读。

## 四、更新与回退

- **文档更新**：重跑 `upload` 即可（同名覆盖，AI Search 重新索引）；建议 jev 大版本落地后同步刷一次。
- **回退/删除**：实例在 Dashboard → AI Search 页面删除即可；本工具只读写实例数据，不动账户其他资源。
- **成本**：AI Search 索引与查询计费见官方定价页（当前 beta 期免费额度内，本项目文档量 ~50 个 md 完全够用）；`upload --dry-run` 与 `stats` 不产生索引写入。

## 五、边界与纪律

- 本工具只索引 `docs/**` markdown，**不索引任何数据库数据、快照、日志**（机密/凭据永不入索引源）。
- 上传失败逐条打印（fail-visible），汇总行给出成功/失败计数；全部失败时退出码 1。
- 文档属研究档案，索引不含生产判据执行逻辑；消费结论仍以 `docs/hotlist-jev/` 正本为准。
