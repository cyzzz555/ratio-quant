# 合约行情搜索与中文展示增量 · 2026-10-11

当前阶段仍为 P1 开发中，本次仅完成行情目录及搜索增量，不代表 P1 验收。

## 已完成

- 从审计的 Binance FAPI exchangeInfo 读取全部当前 TRADING 合约；本次真实响应 789 个，覆盖当前响应中的报价与保证金币种，不再限定九个候选或 USDT/USDC。
- 搜索匹配合约代码、baseAsset 和中文展示别名，不区分英文大小写；支持多词、无匹配提示和清空。
- 搜索结果选择后自动读取逐品种当前规格、交易所时间、K 线及标记价；失效或未知合约停止请求下游价格。
- 美光：MUUSDT · 美光科技（Micron／镁光）。SPCXUSDT / SPCXUSD1：SpaceX 太空探索技术公司。
- 报价旁显示实际 quoteAsset；未知资金费率显示“—”。中文代码也能传给只读公共客户端。
- 自动目录缓存 300 秒；「刷新合约目录」立即重新核验，保留原始响应、UTC 时间和 SHA256。
- 股票名称按 underlyingType + baseAsset 限定别名，避免将 F/C 等同名币种误显示为股票。中文为展示别名，不作为底层资产或账户权限认证。

## 文件变更

- 新增 backend/app/market_catalog.py：目录类型、解析、缓存与本地名称映射。
- 新增 config/market_names.zh.json：可维护的中文名称和公司英文名称。
- backend/app/research_api.py：本地 POST /api/v1/market/catalog、显式刷新参数。
- backend/app/research_data.py：行情由当前交易所逐品种规格核验，返回实际报价币种；历史研究仍保留 P0 候选约束。
- backend/app/public_client.py：支持目录中真实存在的中文代码，保持公共 GET 白名单。
- frontend/src/ResearchDesk.tsx、researchTypes.ts、main.tsx、style.css：搜索、中文结果、目录刷新、真实行情与响应式布局。
- 新增 tests/test_market_catalog.py，更新 README.md；证据见 market_search_validation_2026-10-11.json。

## 运行

本次已在本机启动后端 127.0.0.1:8000 和前端 127.0.0.1:5173。
打开 http://127.0.0.1:5173/#market，搜索“美光”或“SPCX”，在结果下拉框选择合约即可加载行情。

重启网页服务（分别在两个终端进入项目根目录；数据库启动说明仍见 README）：

```sh
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

```sh
cd frontend
pnpm dev
```

若 PATH 中没有 pnpm，使用 README 的 Mac 内置运行时路径。自动目录缓存期间，使用「刷新合约目录」获取交易所即时目录。

## 真实验证

- pytest 默认离线研究套件：120 passed，3 deselected，1 warning（现有 Starlette/httpx 弃用提示），耗时 1.32s。
- Ruff 全部通过；mypy 22 个源文件通过；TypeScript 与 Vite 构建通过，31 个模块。
- 浏览器实测：比特币/BTC 搜索、MUUSDT 美光行情、SPCX 及 SpaceX/太空探索别名、SPCXUSDT 行情、空结果和清空恢复 789 项。
- MUUSDT 与 SPCXUSDT 均读到 98 根闭合 1m K 线，未闭合样本隔离。公共请求失败及重试均保存真实结果。
- 离线新增覆盖：目录结构/重复/路径攻击、中文代码、缓存副本和强制刷新、失效刷新不覆盖证据、同名币股区分、USDC/USD1/中文代码行情、失效合约禁止下游请求、本地来源限制与无订单路由。

## 遗留

本次有 204 个合约具备已收录展示别名，其余显示「中文名待补充」，可继续维护名称文件；不编造中文映射。
P1 PostgreSQL 验收和后续纸面订单流程仍待完成。本次没有改变风险参数或账户权限，LIVE_TRADING_ENABLED=false；账户权限始终 UNKNOWN。

目录文档：https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data
SPCX 命名参考（Binance 官方）：https://www.binance.com/en/blog/markets/8537494775843598839
