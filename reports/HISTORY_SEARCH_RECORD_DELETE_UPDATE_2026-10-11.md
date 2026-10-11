# 历史合约搜索与回测记录删除增量报告

日期：2026-10-11（Asia/Shanghai）。本次为 P1 研究工作台局部增量，未宣称 P1 阶段验收完成。

## 已完成

- 行情和历史采集共用 `ContractSearch` 组件、Binance 公共目录和中文名持久文件；支持合约代码、中文和名称中英文别名搜索、清空、目录刷新、名称补充。
- 当前实测目录为 789 个 TRADING 合约；历史搜索“美光”匹配 MUUSDT，SPCX 在行情和历史两页都匹配 SPCXUSD1 / SPCXUSDT。目录会随交易所响应变化。
- 采集不再限于 P0 原九个候选。后台先实际读取 exchangeInfo 并逐品种验证当前 TRADING 规格，再请求历史 K 线和资金费；下架或未知品种失败，不补造数据，不修改原 P0 报告。
- 搜索排除当前选择时，采集按钮禁用，必须明确选中匹配合约。数据集和回测记录显示共用中文名。
- 新数据集、报告记录实际 quote_asset；模拟金额以数据集报价币种计量，不进行跨币种账户资金折算。
- 回测记录支持全部、7 / 30 / 90 天前筛选、逐条删除确认、回收站和恢复。以创建时间筛选，不自动判断策略是否失效，也不自动删除。
- 删除用固定 UUID 文件路径、预期结果哈希和跨进程研究工作锁，原子移动结果报告到 `reports/research/trash`。保留数据集、Parquet、资金费、规格和原始响应。恢复校验归档字节 SHA256；不覆盖已有报告。
- 删除和恢复写入 `reports/research_record_actions.jsonl`，包含时间、请求/完成状态、run_id、dataset_id、结果哈希和文件哈希。中断后的实际文件位置决定记录状态。
- PostgreSQL 同步读取回收站，保存 DELETED 标记；数据库记录查询排除该标记，恢复后标记 ACTIVE。数据库不可用时文件状态有效，数据库同步保持待完成；未用 SQLite 替代。

## 文件变更

新增：

- `frontend/src/ContractSearch.tsx`：共用目录搜索和名称补充入口。
- `frontend/src/RecordDeleteDialog.tsx`：回测删除确认窗口。
- `backend/app/research_records.py`：可恢复删除、哈希校验、锁和审计。
- `tests/test_research_records.py`：删除恢复及接口防护测试。

修改：

- `frontend/src/ResearchDesk.tsx`：两页共用搜索；历史采集选择防误操作；回测记录筛选、删除、回收站、恢复和币种显示。
- `frontend/src/main.tsx`：研究页去掉九个候选的固定属性。
- `frontend/src/researchTypes.ts`：报价币种、回收站类型。
- `frontend/src/style.css`：删除按钮、回收站响应式布局。
- `backend/app/research_api.py`：删除/恢复和回收站路由；全部回测记录查询；采集校验交由后台逐品种核验。
- `backend/app/research_data.py`、`research_models.py`：目录外旧限制移除；安全中文符号支持；记录 quote_asset、UNKNOWN 账户权限。
- `backend/app/backtest.py`：新报告记录报价币种。
- `backend/app/research_ledger.py`、`research_db.py`：删除标记同步与查询过滤。
- `tests/test_market_catalog.py`：新增非原九个标的的历史分页、规格下架拒绝和中文合约测试。

另生成前端 dist、真实历史数据集、一个验证用回测结果、审计日志和 `history_record_validation_2026-10-11.json`。三个原有回测报告未改动。

## 运行和使用

当前本机 API 8000 和前端 5173 已启动。访问 <http://127.0.0.1:5173/#research>。

1. 历史数据采集：搜索代码或中文，选中合约，填写 1–14 天，再点击“采集历史数据”。采集期间禁止记录删除/恢复；不完整数据集禁止回测。
2. 可复查结果：先选择记录时间筛选和回测记录，再点击“删除此回测记录”并确认。需要恢复时打开“回收站”，点击对应“恢复记录”。删除不回收底层历史文件空间，回收站继续保留报告。
3. 重新启动可双击项目内 `启动研究工作台.command`。若仅需前后端，可分别在项目目录和 frontend 目录执行下列命令；终端服务保持运行。

```sh
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

```sh
pnpm dev
```

## 实际测试结果

- `.venv/bin/pytest -m 'not network and not postgres' -q`：137 passed、3 deselected、1 warning，4.32 秒。警告为既有 Starlette TestClient httpx 弃用提示。
- `.venv/bin/ruff check backend/app tests migrations`：通过。
- `.venv/bin/mypy backend/app`：23 个源文件通过。
- `cd frontend && pnpm build`：TypeScript 检查与 Vite 构建通过，34 个模块。
- 离线新增覆盖：MUUSDT / SPCXUSD1 / 币安人生USDT 不依赖 P0 候选；1440 根分页和数据哈希读取；逐品种变为 SETTLING 时仅请求规格并拒绝后续历史请求。
- 删除测试覆盖：删除后列表和下载隐藏、完整字节恢复、数据集保留、重复操作/错误预期哈希/目标冲突、研究任务锁、报告结果哈希篡改、回收站字节篡改、无效 UUID、本地 Origin 校验、额外请求字段拒绝、数据库同步失败提示。
- 浏览器真实采集 MUUSDT 1 天：数据集 `88825a16-6364-4549-ad72-478c7f02cfd7`，1440 根闭合 1m K 线、3 条资金费记录、0 段缺口、完整范围 true。
- 浏览器用该数据集运行研究回测：`5c276475-ab41-4ca1-bdf2-a85edac2b0bd`，按现有默认研究参数实际计算，训练/验证/Holdout 分别 1 / 3 / 3 笔模拟交易。此记录为本次功能验证新建，不用于盈利证明。
- 浏览器实测删除取消、7 天前空状态、删除确认、回收站、恢复。删除后原下载返回 404；恢复后返回 200。报告原字节 SHA256、底层数据文件 SHA256及三个原报告 SHA256均保持一致；最终回收站为空，新报告已恢复。
- 行情 SPCX 搜索、历史 SPCX 搜索均为 2 个匹配；历史名称补充窗口正常打开并取消，未写入测试名称。浏览器错误日志为空。
- 截图位于工作区 `outputs/history-search-2026-10-11.png`、`outputs/backtest-delete-window-2026-10-11.png`、`outputs/backtest-trash-2026-10-11.png`、`outputs/backtest-restored-2026-10-11.png`。

## 遗留问题及边界

- PostgreSQL 本机当前仍未就绪；删除标记的真实 PostgreSQL 同步未实测，P1 数据库验收仍待完成。此次实测为文件暂存路径，未将其宣称为数据库验收通过。
- 公共行情/规格/历史数据不证明账户、地区、杠杆及真实费用权限；新符号保持账户 UNKNOWN，研究 RESEARCH_ONLY。
- LIVE_TRADING_ENABLED=false；没有新增真实订单路径，没有修改 50% 本金损失容忍、常规单仓 10–20x / 最高 25x 偏好或未批准风险参数。
