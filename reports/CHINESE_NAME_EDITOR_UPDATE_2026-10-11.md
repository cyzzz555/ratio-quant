# 中文名补充写入窗口 · 2026-10-11

本次完成 P1 行情 UI 的局部增量。P1 阶段仍在开发中，不表示阶段验收完成。

## 使用方法

打开 http://127.0.0.1:5173/#market，点击搜索栏右侧「补充中文名」。
在窗口内搜索合约，可勾选「仅显示中文名待补充的合约」，选择结果，填写中文展示名称，然后点击「保存中文名」。
可填写中文加英文公司名或常用别名，最多 80 个字符。保存前窗口显示会更新的合约范围。
保存后窗口关闭并显示成功提示；名称即时用于行情标签和搜索，刷新页面后仍保留。取消、关闭及 Escape 不写入。
当前已在 Mac 运行后端 127.0.0.1:8000 和前端 127.0.0.1:5173，并打开补充窗口。

重新启动网页服务时，在两个终端进入工程根目录，分别执行：

```sh
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

```sh
cd frontend
pnpm dev
```

Mac 内置 pnpm 的路径及完整研究环境启动见 README.md。

## 文件变更

- 新增 frontend/src/MarketNameDialog.tsx：原生 modal dialog、合约搜索、缺失筛选、中文输入、保存与取消。
- frontend/src/ResearchDesk.tsx：窗口入口、保存提示、即时更新行情目录和搜索。
- frontend/src/researchTypes.ts、style.css：输入/保存响应类型及窗口样式。
- backend/app/market_catalog.py：名称更新模型、校验、文件锁、原子写入、并发冲突检测、修改日志及缓存名称同步。
- backend/app/research_api.py：本地 POST /api/v1/market/names。Origin/Host/JSON/本地来源检查保持有效。
- 新增 tests/test_market_names.py，更新 README.md 和 .gitignore。
- config/market_names.zh.json：浏览器实际验证将美光补充为「美光科技（Micron Technology／镁光）」。
- reports/market/name_updates.jsonl：真实修改记录；完整验证结果见 chinese_name_editor_validation_2026-10-11.json。

## 保存范围与可追溯性

名称保存到固定本地文件 config/market_names.zh.json，不接收用户提交的文件路径。
按已观测 underlyingType + baseAsset 同步更新同资产同类型合约；类型未知时只更新所选合约，避免币种与股票同名混淆。
使用文件锁保护读取与原子写入，保存前校验 expected_name；其他窗口已修改时返回 409，避免覆盖新名称。
日志记录 UTC 时间、修改前后名称、影响合约及目录响应哈希。缓存读取重新应用本地名称，其他服务实例的本地修改也能生效。

## 实际验证

- pytest：129 passed，3 deselected，1 warning，4.53s。3 项为显式启用的网络/PostgreSQL 测试；warning 是现有 Starlette/httpx 弃用提示。
- Ruff 全通过；mypy 22 个源文件通过；TypeScript 和 Vite 构建通过，32 个模块。
- 新增 9 项离线用例覆盖：持久化与重启读取、同资产同步及币股隔离、保留其他名称、缓存更新、不额外联网、并发冲突、未知合约拒绝、非法名称、本地来源保护和请求路径字段拒绝。
- 浏览器实测缺失筛选返回 585 个合约，英文名称保存按钮禁用。
- 实际保存 MUUSDT 为「美光科技（Micron Technology／镁光）」，立即搜索新英文名称匹配 1 个；刷新后仍匹配且名称保留。
- 在 0GUSDT 编辑未保存名称后按 Escape，名称文件 SHA256 完全不变，无试验名称留存。
- 浏览器错误日志为空。截图位于 outputs/chinese-name-editor-2026-10-11.png。

## 遗留

已收录名称是本地展示别名，不会因此认证真实底层资产或账户权限。未填写项仍显示「中文名待补充」。
此窗口面向本机控制台，尚未增加云端多用户名称管理。P1 PostgreSQL 验收及后续模拟订单流程仍待完成。
LIVE_TRADING_ENABLED=false，账户权限 UNKNOWN，本次没有修改任何风险参数或真实订单路径。
