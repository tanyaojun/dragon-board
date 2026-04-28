# Dragon Board 项目工作区与 GitHub 管理标准

本文档用于固定灾难恢复后的项目管理规则。后续所有人工或 AI 代码修改、提交、清理、同步 GitHub，都必须先遵守本文档。

当前恢复后工作区基线：

- 本地目录：`D:\dragon-board`
- 主分支：`main`
- 远程仓库：`origin https://github.com/tanyaojun/dragon-board.git`
- 当前稳定提交：`8fa363b chore: quiet debug console logs`
- 重要历史基线：`d4be468 chore: clean workspace and trim dependencies`
- 既有保护标签/分支：`baseline-clean-20260428`、`baseline/clean-workspace-20260428`

## 1. 核心原则

1. 本地工作区优先保护。任何远程同步、清理、回滚、重装依赖前，必须先确认本地未提交修改。
2. 小步提交。每一类独立修改完成并验证后立即提交，不允许长期堆积大量未提交改动。
3. 先备份，再同步。涉及 GitHub 拉取、重置、分支切换、依赖清理、批量删除文件前，必须创建本地保护点。
4. 禁止无确认覆盖。本项目禁止在未审查本地状态时执行会覆盖工作区的命令。
5. 构建可用优先。代码提交前至少保证当前修改相关的验证命令通过，无法验证时必须在提交说明或交接说明里写明。

## 2. 严禁操作

以下操作除非用户明确要求，并且已经创建本地保护点，否则禁止执行：

- `git reset --hard`
- `git checkout -- .`
- `git clean -fd` 或 `git clean -fdx`
- `git pull --rebase` 后自动解决冲突并覆盖本地文件
- 删除 `node_modules` 后不恢复依赖
- 批量删除未知 `.json`、`.txt`、隐藏文件、构建配置文件
- 直接用 GitHub 远端版本覆盖本地工作区
- 对未理解用途的目录执行清理，尤其是 `src`、`proxy-server`、`python-bridge`、`tools`、`public`

如果确实需要执行危险操作，先执行保护流程：

```powershell
git status --short
git branch backup/before-risky-change-YYYYMMDD-HHMM
git tag backup-before-risky-change-YYYYMMDD-HHMM
```

## 3. 每次修改前检查流程

开始任何代码修改前，必须执行：

```powershell
git status --short
git log --oneline -5
```

判断规则：

- 工作树干净：可以开始修改。
- 有未提交文件：先判断是否是当前任务相关。
- 有用户修改：不得回滚，不得覆盖，必须在现有修改上继续工作。
- 修改范围不明：先汇总文件列表和风险，再继续。

建议补充检查：

```powershell
git diff --stat
git diff --name-only
```

## 4. 提交标准

每次提交应满足：

- 只包含一个清晰主题。
- 提交信息使用英文 Conventional Commit 风格。
- 提交前执行必要验证。
- 不把临时日志、构建缓存、测试输出、个人环境文件提交进仓库。

常用提交类型：

- `fix:` 修复用户可见问题或运行错误
- `feat:` 新功能
- `refactor:` 行为不变的结构调整
- `chore:` 构建、依赖、清理、维护
- `docs:` 文档
- `test:` 测试

推荐提交流程：

```powershell
git status --short
git diff --stat
npm run build
git add <files>
git commit -m "fix: describe the change"
git status --short
```

如果只是文档修改，可以不跑完整构建，但最终说明必须写明“仅文档变更，未运行构建”。

## 5. GitHub 同步标准

### 5.1 推送本地稳定版本

推送前：

```powershell
git status --short
git log --oneline -5
```

确认工作树干净后：

```powershell
git push origin main
```

推送后检查：

```powershell
git status --short
git log --oneline -5
```

### 5.2 拉取远程更新

禁止直接用 `git pull` 作为第一步。必须先 fetch 和审查差异：

```powershell
git status --short
git branch backup/before-fetch-YYYYMMDD-HHMM
git fetch origin
git log --oneline --left-right --graph HEAD...origin/main
git diff --stat HEAD..origin/main
```

只有确认远程变更不会覆盖本地成果后，才允许合并：

```powershell
git merge origin/main
```

如果合并冲突，必须逐文件分析，禁止用远端或本地一键覆盖全部文件。

### 5.3 远程落后于本地

如果 GitHub 仓库版本比本地旧，以本地稳定提交为准。不要用旧远程覆盖本地。

推荐做法：

```powershell
git status --short
git log --oneline --left-right --graph origin/main...HEAD
git push origin main
```

## 6. 基线版本管理

重要恢复点、重大重构前、依赖清理前，必须创建标签和备份分支：

```powershell
git branch baseline/name-YYYYMMDD
git tag baseline-name-YYYYMMDD
```

建议命名：

- `baseline/clean-workspace-YYYYMMDD`
- `baseline/before-github-sync-YYYYMMDD-HHMM`
- `backup/before-risky-change-YYYYMMDD-HHMM`

查看保护点：

```powershell
git branch --list "baseline/*" "backup/*"
git tag --list "baseline*" "backup*"
```

## 7. 依赖与生成文件管理

### 7.1 `node_modules`

`node_modules` 是本地安装依赖目录，不应提交到 Git，但运行和构建需要它存在。

根目录 `node_modules` 由根目录 `package.json` 和 `package-lock.json` 管理：

```powershell
npm install
```

`proxy-server/node_modules` 由 `proxy-server/package.json` 管理：

```powershell
cd proxy-server
npm install
```

清理依赖前必须确认：

- 对应目录有 `package.json`
- `node_modules` 不在 Git 跟踪中
- 删除后能通过 `npm install` 恢复
- 删除后必须验证启动或构建

### 7.2 不应入库的文件

以下通常不应提交：

- `node_modules/`
- `dist/`
- `.tmp/`
- `*.tsbuildinfo`
- `*.log`
- 临时验证输出
- 本地 IDE 缓存

如果发现误入库，先确认用途，再用 `git rm --cached` 从索引移除，避免删除用户本地需要的文件。

## 8. 验证标准

常用验证命令：

```powershell
npm run build
```

类型检查可用时执行：

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

涉及 Python bridge：

```powershell
python -m py_compile python-bridge\main.py
```

涉及 TDX helper：

```powershell
dotnet build tools\TdxL2Helper\TdxL2Helper.csproj -c Release
```

验证结果必须在最终交接中说明：

- 执行了什么命令
- 是否通过
- 有哪些剩余 warning
- 未执行的原因

## 9. 日志管理标准

默认浏览器控制台只保留：

- 系统启动关键日志
- `console.warn`
- `console.error`

普通调试日志必须使用：

```ts
import { debugLog } from '@/utils/logger'

debugLog('[Module] debug message', data)
```

调试日志默认关闭。需要临时打开时，在浏览器控制台执行：

```js
localStorage.setItem('dragon-board:debug-logs', '1')
```

关闭：

```js
localStorage.removeItem('dragon-board:debug-logs')
```

禁止新增默认刷屏的 `console.log`、`console.info`、`console.debug`、`console.trace`。

## 10. AI 协作规则

AI 修改代码时必须遵守：

1. 修改前先检查 `git status --short`。
2. 不回滚用户已有修改。
3. 不执行危险 Git 命令，除非用户明确要求且已创建保护点。
4. 不删除未知目录或文件。
5. 对依赖目录先说明用途，再清理。
6. 变更前说明将修改哪些模块。
7. 变更后运行验证。
8. 验证通过后及时提交。
9. 最终回复必须包含提交号、验证结果和剩余风险。

遇到冲突或不确定文件用途时，AI 必须暂停并说明判断依据，不能猜测删除。

## 11. 灾难恢复流程

如果再次发生误覆盖、误删除或远程旧版本覆盖本地：

1. 立即停止继续操作，不要再 pull、reset、clean。
2. 查看最近提交和 reflog：

```powershell
git log --oneline -20
git reflog --date=local -20
```

3. 查找保护分支和标签：

```powershell
git branch --all
git tag --list
```

4. 创建当前现场保护分支：

```powershell
git branch rescue/current-state-YYYYMMDD-HHMM
```

5. 从最近稳定提交恢复到新分支，不直接覆盖 `main`：

```powershell
git switch -c rescue/from-baseline <commit-or-tag>
```

6. 逐文件比对恢复：

```powershell
git diff --name-status rescue/from-baseline..main
```

7. 恢复完成后构建验证并提交。

## 12. 当前建议执行节奏

后续每个修复任务按这个节奏走：

1. `git status --short`
2. 明确本次只改哪些问题
3. 小范围修改
4. `npm run build`
5. 必要时补充类型检查或专项测试
6. `git diff --stat`
7. `git commit`
8. 需要同步 GitHub 时先 `git fetch origin` 审查，再 `git push origin main`

这个流程的目标不是增加手续，而是保证本地抢救回来的成果不会再被远程旧版本或批量清理误伤。

