# 题材模块 V10：迁移 ThemeDataDB 到 themeDATA.db

## 目标

- 找到本机浏览器中 Dragon Board 旧 `ThemeDataDB/theme_mapping` 数据。
- 将旧 `ThemeMappingData` 一次性导入 QuantBoard `themeDATA.db`。
- 用 V9 校验工具确认 SQLite 行数与源数据一致。

## 范围

- 优先使用现有 `POST /api/migrations/themes/import-json` / `verify-themes` 能力。
- 如果 IndexedDB 只能通过 LevelDB 读取，则使用离线解析或补最小 CLI 能力。
- 迁移完成后只校验，不删除浏览器历史 IndexedDB。

## 阶段

1. [x] 定位 Chrome/Edge IndexedDB 源目录。
2. [x] 解析 `ThemeDataDB/theme_mapping` 导出为 `ThemeMappingData` JSON。
3. [x] 导入 `themeDATA.db`。
4. [x] 运行 `verify-themes` 和基础读口检查。
5. [x] 更新进度文档并运行必要验证。

## 结果

- 源 origin：Chrome `http_localhost_5173`。
- 源数据：`ThemeDataDB/theme_mapping/theme_data`，实际大值位于同名 `indexeddb.blob`。
- 导出文件：`quant-board/data/staging/theme_v10_http_localhost_5173_ThemeDataDB_import.json`。
- 目标库：`quant-board/data/warehouse/themeDATA.db`。
- 导入结果：237 个题材、12215 条题材-股票关系、4166 只去重股票。
- 校验结果：`verify-themes` 返回 `ok=true`，无缺失题材、无额外题材、无缺失映射、无额外映射。

## 约束

- 不使用批量删除命令。
- 不删除 IndexedDB 历史数据。
- 不把导出的运行期大文件提交进仓库。
