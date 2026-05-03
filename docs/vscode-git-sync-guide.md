# VS Code Git 同步操作手册

适用对象：不熟悉 Git 命令，但需要在 VS Code GUI 失灵时，用控制台完成安全提交和推送的日常开发流程。

本手册目标只有一个：避免本地工作区再次被远端旧版本覆盖，避免把 `.tmp`、`node_modules`、`dist` 等本地产物误提交到 GitHub。

原则：只执行本文明确写出来的 Git 命令。没写的 Git 命令不要自己尝试。

## 核心原则

1. 看到同步按钮，不要立刻点。先看左侧“源代码管理”面板里有哪些文件改动。
2. 每次同步前，必须先有本地提交。不要把大量未检查文件直接混进一次提交。
3. 只提交代码、配置、文档、必要的项目资源。不要提交运行产物、临时文件、依赖目录。
4. 出现冲突、覆盖、拒绝、超大文件、无法推送等提示时，停止操作，先找 Codex 检查。
5. 不用 `git pull` 解决提交卡住。提交卡住是本地问题，拉远端代码可能把问题扩大。

## 控制台固定提交流程

以后 VS Code GUI 提交按钮没反应，直接按本节走。不要点“丢弃更改”，不要点“拉取”，不要点“同步”。

### 第一步：打开终端并进入项目目录

在 VS Code 底部打开终端，确认提示符在项目根目录。

如果不确定，执行：

```powershell
cd D:\dragon-board
```

### 第二步：查看当前改动

先看短状态：

```powershell
git status --short
```

再看改动摘要：

```powershell
git diff --stat
```

判断标准：

- 只看到本次任务相关文件，继续。
- 看到 `.tmp`、`node_modules`、`dist`、`*.exe`、`*.pdb`，停止。
- 看到大量 `D` 删除文件，停止。
- 看到完全不认识的文件，停止。

### 第三步：暂存文件

只提交一个文件，使用明确路径：

```powershell
git add docs/vscode-git-sync-guide.md
```

提交多个明确文件，就逐个执行 `git add`：

```powershell
git add src/services/dataLoader.ts
git add docs/attention-manual.md
```

确认当前所有改动都属于本次提交时，才使用：

```powershell
git add -A
```

`git add -A` 会把修改、新增、删除全部暂存。执行前必须确认第二步的文件列表没有异常。

### 第四步：确认暂存区

提交前必须看暂存区：

```powershell
git diff --cached --stat
```

再看暂存文件状态：

```powershell
git diff --cached --name-status
```

判断标准：

- 输出里的文件都应该进入本次提交，继续。
- 出现不该提交的文件，停止。
- 没有任何输出，说明没有暂存文件，回到第三步。

### 第五步：执行提交

使用一行命令提交，不打开编辑器：

```powershell
git commit -m "docs: 补充 VS Code Git 提交流程"
```

提交信息格式：

```text
fix: 修复某个问题
feat: 增加某个功能
docs: 更新项目文档
chore: 调整工程配置
refactor: 重构某段代码
test: 补充测试
```

提交信息不能为空，也不要只写 `update`、`fix` 这种看不出内容的词。

### 第六步：确认提交结果

提交后执行：

```powershell
git status
```

如果看到类似：

```text
Your branch is ahead of 'origin/main' by 1 commit.
nothing to commit, working tree clean
```

说明本地提交成功，还没有推送到 GitHub。

再看最近提交：

```powershell
git log --oneline -5
```

确认第一行是刚才的提交。

### 第七步：推送到 GitHub

确认本地工作区干净后，再推送：

```powershell
git push
```

推送成功后再执行：

```powershell
git status
```

如果看到：

```text
nothing to commit, working tree clean
```

并且不再提示 `ahead of 'origin/main'`，说明本地和 GitHub 已同步。

如果 `git push` 报错，不要执行其它 Git 命令，把完整错误信息发给 Codex。

### 固定模板

最常用流程如下：

```powershell
cd D:\dragon-board
git status --short
git diff --stat
git add -A
git diff --cached --stat
git diff --cached --name-status
git commit -m "docs: 补充 VS Code Git 提交流程"
git status
git log --oneline -5
git push
git status
```

这个模板里的 `git add -A` 只适用于确认所有改动都应该提交的情况。如果只想提交某个文件，把 `git add -A` 换成 `git add 具体文件路径`。

## 当前截图这种 COMMIT_EDITMSG 怎么处理

如果 VS Code 打开了 `.git/COMMIT_EDITMSG`，并且内容类似：

```text
# Please enter the commit message for your changes.
# Lines starting with '#' will be ignored...
```

这表示 Git 正在等提交信息。以 `#` 开头的行都是注释，不算提交信息。

有两种处理方式，选一种即可。

方式一：在文件第一行写提交信息。

```text
docs: 补充 VS Code Git 提交流程
```

然后保存文件，关闭 `.git/COMMIT_EDITMSG` 标签页。

方式二：取消这次编辑器提交，改用控制台一行命令。

1. 关闭 `.git/COMMIT_EDITMSG` 标签页。
2. 如果 VS Code 问是否保存，选择不保存。
3. 在终端执行：

```powershell
git status
git diff --cached --stat
git commit -m "docs: 补充 VS Code Git 提交流程"
```

如果 `git diff --cached --stat` 有输出，说明文件已经暂存，可以直接提交。

如果提示没有暂存文件，再按固定流程从 `git status --short` 开始。

## 可以提交的内容

通常可以提交：

- `src/` 下的源码文件
- `docs/` 下的项目文档
- `python-bridge/` 下的源码、研究脚本、说明文档
- `tools/` 下的源码、项目文件、说明文档
- `package.json`、`package-lock.json`
- `tsconfig*.json`、`vite.config.ts`、`vitest.config.ts`
- `.gitignore`
- `.vscode/extensions.json`

`.vscode/extensions.json` 是 VS Code 推荐扩展清单，可以提交；其它 `.vscode` 个人配置不要提交。

## 不要提交的内容

以下目录和文件通常不要提交：

- `.tmp/`
- `node_modules/`
- `dist/`
- `dist-ssr/`
- `coverage/`
- `playwright-report/`
- `test-results/`
- `*.log`
- `*.tsbuildinfo`
- `*.exe`
- `*.pdb`
- `**/bin/`
- `**/obj/`

如果 VS Code 源代码管理面板里出现这些内容，先不要提交，找 Codex 检查 `.gitignore` 或清理索引。

## 日常同步流程

### 第一步：打开源代码管理面板

点击 VS Code 左侧的“源代码管理”图标。

检查“更改”列表：

- 文件数量是否合理
- 是否包含 `.tmp`、`node_modules`、`dist`
- 是否包含很大的二进制文件，例如 `.exe`、`.pdb`、`.zip`
- 是否有你不认识的删除文件

如果文件列表看不懂，先不要提交。

### 第二步：确认改动含义

每个提交应该只表达一个清晰目的，例如：

- 修复数据导出面板
- 清理控制台调试日志
- 更新项目管理文档
- 修复类型检查错误

不要把“功能修复 + 临时文件 + 研究脚本 + 构建产物”混在同一个提交里。

### 第三步：填写提交信息

在源代码管理面板的消息框里写一句清楚的提交信息。

推荐格式：

```text
fix: 修复数据导出面板
docs: 添加 VS Code 同步操作手册
chore: 清理本地工作区忽略规则
refactor: 优化回测引擎结构
```

常用前缀：

- `fix:` 修 bug
- `feat:` 新功能
- `docs:` 文档
- `chore:` 工程配置、清理
- `refactor:` 重构
- `test:` 测试

### 第四步：点击提交

点击“提交”按钮。

如果 VS Code 提示没有暂存文件，可以选择“全部暂存并提交”，但前提是你已经确认文件列表没有垃圾文件。

### 第五步：点击同步更改

提交成功后，再点击左下角同步按钮。

同步按钮会做两件事：

- 把 GitHub 上的新提交拉下来
- 把你的本地提交推上去

正常情况：同步完成后，左下角不会再显示待同步数字。

## VS Code 提交卡住时的命令行救场

这一节只处理“提交没有成功、VS Code GUI 卡住、提交按钮没反应”这类问题。它不处理拉取、合并、冲突、变基、覆盖本地文件。遇到那些问题，先停手找 Codex。

### 第一原则：不要反复点提交或同步

看到 VS Code 一直显示“正在提交更改...”，先不要连续点击。

正确动作：

1. 停止点击提交、同步、拉取。
2. 打开 VS Code 终端。
3. 确认终端目录是项目根目录，例如 `D:\dragon-board`。
4. 先执行只读检查命令。

PowerShell 里可以用：

```powershell
git status
```

如果终端不是项目根目录，先进入项目目录：

```powershell
cd D:\dragon-board
```

### 先确认是不是提交信息卡住

如果 VS Code 打开了 `.git/COMMIT_EDITMSG`，通常表示 Git 正在等提交信息。

处理方式：

1. 看文件第一行是否有真正的提交标题。
2. 以 `#` 开头的行都是注释，不算提交信息。
3. 在第一行写一条提交信息，例如：

```text
docs: 补充 VS Code Git 提交中断处理
```

4. 保存 `.git/COMMIT_EDITMSG`。
5. 关闭这个编辑器标签页。
6. 等几秒，再看源代码管理面板是否完成提交。

如果文件里只有 `#` 注释，没有提交标题，Git 会把这次提交当成空消息并中断。

### 查看当前 Git 状态

提交卡住后，先用下面命令看真实状态：

```powershell
git status
```

常见输出含义：

- `Changes to be committed`：文件已经暂存，下一步可以提交。
- `Changes not staged for commit`：文件改了，但还没有暂存。
- `Untracked files`：新增文件还没有纳入本次提交。
- `nothing to commit, working tree clean`：当前没有可提交内容，可能刚才已经提交成功。
- `You are in the middle of a merge`：正在合并中，不要自己继续处理，找 Codex。
- `rebase in progress`：正在变基中，不要自己继续处理，找 Codex。

更短的状态命令：

```powershell
git status --short
```

常见标记含义：

- `M`：文件被修改。
- `A`：新增文件。
- `D`：删除文件。
- `??`：Git 还没跟踪的新文件。

如果突然看到大量 `D` 删除，或者出现 `.tmp`、`node_modules`、`dist`，先不要提交。

### 看清楚哪些文件会被提交

提交前先看文件列表，不要盲目 `git add -A`。

查看所有改动的摘要：

```powershell
git diff --stat
```

查看已经暂存、将会进入提交的摘要：

```powershell
git diff --cached --stat
```

查看已经暂存文件的增删状态：

```powershell
git diff --cached --name-status
```

如果 `git diff --cached --stat` 没有输出，说明暂存区为空，还没有文件进入本次提交。

### 用命令行完成提交

只提交单个文件时，优先使用明确路径：

```powershell
git add docs/vscode-git-sync-guide.md
git commit -m "docs: 补充 VS Code Git 提交中断处理"
```

提交多个明确文件时，逐个写路径：

```powershell
git add src/services/dataLoader.ts
git add docs/attention-manual.md
git commit -m "fix: 优化实时行情字段计算"
```

确认当前所有改动都应该提交时，才使用：

```powershell
git add -A
git diff --cached --stat
git commit -m "fix: 修复实时行情数据合并"
```

`git add -A` 会把修改、新增、删除全部放进提交。它很方便，但也最容易把垃圾文件或误删文件带进去，所以必须先看 `git status --short` 和 `git diff --stat`。

### 提交后确认是否成功

提交后执行：

```powershell
git status
```

如果看到：

```text
nothing to commit, working tree clean
```

说明本地工作区已经干净。

再看最近提交：

```powershell
git log --oneline -5
```

确认最新一条就是刚才的提交，再去 VS Code 点“同步更改”。

### 如果提示 index.lock

如果命令行提示类似：

```text
fatal: Unable to create '.git/index.lock': File exists.
```

通常表示上一次 Git 操作异常中断，留下了锁文件。不要立刻删除它，先确认没有 Git 进程还在运行。

检查 Git 进程：

```powershell
Get-Process git -ErrorAction SilentlyContinue
```

如果有输出，先等一会儿，或者关闭 VS Code 的 Git 操作窗口后再检查。

确认没有 Git 进程后，再检查锁文件是否存在：

```powershell
Test-Path .git/index.lock
```

只有在确认没有 Git 进程、并且锁文件仍然存在时，才删除锁文件：

```powershell
Remove-Item .git/index.lock
```

删除后立刻重新检查：

```powershell
git status
```

如果仍然报错，停止操作，把完整输出发给 Codex。

### 提交中断时不要执行这些命令

下面这些命令不能拿来解决“提交卡住”。它们可能覆盖或丢失本地成果：

```powershell
git pull
git pull --rebase
git reset --hard
git checkout .
git clean -fd
git merge --abort
git rebase --abort
```

说明：

- `git pull` 是从 GitHub 拉代码，不是修复本地提交卡住。
- `git reset --hard` 会丢弃本地未提交改动。
- `git checkout .` 会把文件改动直接还原掉。
- `git clean -fd` 会删除未跟踪文件。
- `git merge --abort` 和 `git rebase --abort` 只适合特定状态，不要凭感觉使用。

如果不确定，宁愿只执行 `git status`，不要执行会改变工作区的命令。

### 最安全的救场模板

当 VS Code 提交按钮没反应，但你确认只是要把当前修改提交，可以按这个顺序检查：

```powershell
cd D:\dragon-board
git status --short
git diff --stat
git diff --cached --stat
```

如果文件列表正常，再提交：

```powershell
git add -A
git diff --cached --stat
git commit -m "docs: 补充 VS Code Git 提交中断处理"
git status
```

如果任何一步出现冲突、覆盖、合并、变基、大量删除、大文件提示，立刻停止。

## 看到这些提示时不要继续点

### “无法推送 refs 到远端”

含义：GitHub 拒绝了这次 push。

常见原因：

- 网络连接中断
- GitHub 上有新提交，本地需要先安全合并
- 历史里包含超过 100MB 的大文件
- 权限或认证失效

处理方式：停止操作，把完整错误信息发给 Codex。

### “Large files detected”

含义：提交历史里有超大文件，GitHub 拒收。

典型错误：

```text
File .tmp/.../xxx.exe is 154.25 MB
exceeds GitHub's file size limit of 100.00 MB
```

处理方式：不要再反复同步。需要清理本地未推送历史，普通删除文件不能解决。

### “Your local changes would be overwritten”

含义：继续操作会覆盖本地改动。

处理方式：立刻停止。不要点确认，不要点丢弃。

### “Merge Conflict” 或“合并冲突”

含义：本地和 GitHub 同时改了同一段代码。

处理方式：不要随意选择“接受当前”或“接受传入”。先找 Codex 判断哪一边该保留。

### 出现大量删除文件

如果源代码管理面板突然出现很多 `D` 删除文件，先不要提交。

可能原因：

- 文件被误删
- 目录被清理工具删除
- 切换分支或同步异常

处理方式：先让 Codex 检查 `git status`。

## 同步前检查清单

每次点击同步按钮前，快速确认：

- 已经完成本地提交
- 这次提交只包含本次任务相关文件
- 没有 `.tmp`
- 没有 `node_modules`
- 没有 `dist`
- 没有 `.exe`、`.pdb` 等构建产物
- 没有不认识的大量删除
- 没有 VS Code 弹出覆盖、冲突、拒绝提示

全部满足，才点击同步。

## 推荐工作节奏

小步提交，不要攒太久。

建议节奏：

1. 修完一个明确问题
2. 运行必要检查
3. 提交一次
4. 同步一次
5. 再开始下一个问题

这样即使后续出问题，也能回到最近的安全点。

## 什么时候必须找 Codex

以下情况不要自己处理：

- 同步失败并出现英文错误
- GitHub 拒收 push
- 出现冲突
- 出现大文件提示
- 出现大量文件删除
- VS Code 提示要覆盖本地更改
- 不确定某个文件该不该提交
- 想清理工作区但不确定哪些文件能删

直接把 VS Code 弹窗截图或终端输出贴出来即可。

## 自动防线

当前仓库没有可用的 `git:preflight` 脚本，也没有提交随仓库分发的 Git hook。

同步前按本文的 `git status --short`、`git diff --stat`、`git diff --cached --stat`、`git diff --cached --name-status` 手工检查。后续如果恢复自动检查，必须先提交真实脚本，再把对应命令写回本文档。

## 当前项目基线

当前项目使用以下本地基线引用：

- `baseline/clean-workspace-20260428`
- `baseline-clean-20260428`

这两个引用用于标记“灾后清理完成后的干净主线”。不要手动删除或改动它们。

如果需要更新基线，由 Codex 检查并执行。
