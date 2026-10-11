# ratio-quant · Quant System V1.2 本地研究工作台

一个量化交易程序。

当前为 **P1 开发中，尚未完成阶段验收**。行情、历史采集、研究回测和风险试算已经接入真实运行路径。
PostgreSQL 初始化被 Codex 沙箱的系统共享内存权限阻断，数据库迁移与持久风控锁的数据库集成验收仍待完成。
研究结果明确标为文件暂存，未使用 SQLite 冒充 PostgreSQL；启动数据库后可显式写入元数据台账。

`LIVE_TRADING_ENABLED=false`、`HUMAN`、`PAPER_BROKER` 保留。没有真实订单或认证账户访问路径。
P3 的纸面订单、审批、持仓管理尚未开发；当前「交易准备」仅为纯模拟风控计算。
42 轮决策及原始技术规格在 `docs/`；微资金本金亏损容忍 50%、常规单仓 10–20x、最高 25x 保留。
其余微资金风险参数保持研究/模拟候选，不能当作实盘授权。

## 在这台 Mac 运行

当前网页：[行情](http://127.0.0.1:5173/#market)、[历史与回测](http://127.0.0.1:5173/#research)、[交易准备](http://127.0.0.1:5173/#risk)。

工程目录：
`/Users/zhantaorui/Documents/Codex/2026-10-10/quant-system-v1-2-1-00/outputs/quant-system`

在 Finder 双击工程内 **启动研究工作台.command**，脚本使用已有虚拟环境，依次启动/检查本地 PostgreSQL、执行 Alembic、写入暂存研究元数据、启动 API 和前端并打开浏览器。
它只复用已就绪的本机服务，不终止其他进程。保持终端窗口打开；Ctrl+C 停止本脚本创建的服务。
该脚本已通过 shell 语法检查；本轮无法在 Codex 沙箱内验证 PostgreSQL 启动成功，需在 Mac 终端运行验证。
数据库仅使用用户私有 Unix socket，不开放 TCP；数据在 `.runtime/`，本地连接配置在忽略的 `config/local_runtime.json`。

也可在 Mac 终端手动运行（进入工程目录）：

```sh
PYTHONPATH=backend .venv/bin/python -m app.local_workspace
```

若只需要当前已可运行的文件研究模式，分别打开两个终端：

```sh
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```sh
cd frontend
pnpm dev
```

文件研究模式的页面会持续显示数据库未就绪；这不代表 P1 已验收。
本机使用 Python 3.12.14、Node.js 24、pnpm 11.25；若终端未找到 pnpm，可使用现有 Codex 运行时：

```sh
export PATH="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH"
"$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm" dev
```

## 如何操作

1. 「合约行情」进入时读取一次 XAUUSDT 公共行情。搜索交易所当前 USD-M 合约代码或中文别名（如 BTC、比特币、黄金、英伟达），在下拉结果中选择合约即可读取行情；也可选择周期后点击「刷新行情」。目录自动缓存 5 分钟；「刷新合约目录」会立即重新核验，不再局限于原九个候选合约。目录按当前 FAPI 响应读取报价币种（包括 USDT、USDC、USD1 等），价格旁显示实际报价币种。支持美光 / Micron / 镁光和 SPCX / SpaceX / 太空探索搜索。中文为 `config/market_names.zh.json` 本地展示别名；未收录项显示「中文名待补充」，不代表底层资产或账户权限核验。图中仅使用闭合 K 线；未闭合样本隔离，悬停查看 OHLCV。1h/1d 可结合已采集历史；缺口不补造价格。行情为手动更新快照，P2 持续行情还未开发。
   - 点击「补充中文名」打开写入窗口，可搜索合约或勾选「仅显示中文名待补充的合约」，选中后填写中文展示名称并保存。名称保存到 `config/market_names.zh.json`，立即用于显示和搜索；同资产、同类型合约同步更新，窗口会展示范围。关闭/取消不会写入。多个窗口同时修改同一名称时会提示冲突，需刷新后编辑；日志位于 `reports/market/name_updates.jsonl`。
2. 「历史与回测」与行情页共用当前合约目录、搜索和中文名称补充窗口。搜索并选中合约及 1–14 天，点击「采集历史数据」，后台重新逐品种核验当前规格后采集。进度自动更新。完整历史才能运行回测；这台 Mac 上的采集数据保存在 `data/`，新克隆仓库需要重新采集。
3. 选择数据集，编辑研究窗口、费用等假设，点击「运行研究回测」。完成后切换训练/验证/Holdout，查看权益曲线、指标、模拟成交、滑点情景，下载完整 JSON 报告。
   - 回测记录可筛选 7 / 30 / 90 天前的记录，选择后点击「删除此回测记录」并确认。结果移入回收站，可恢复；历史数据集、原始响应和审计证据保留，删除不释放这些文件占用的磁盘空间。
4. 「交易准备」填写模拟入场价、止损价、权益和风险预算，点击「计算模拟仓位」。数量向下取整，显示保证金、有效杠杆、两种回撤指标和开仓阻断原因。它不会发送订单。
5. 原 P0 合约能力、公共接口探测、证据弹窗和报告下载继续保留。

## 研究假设与边界

- 所有窗口、触发条件、成本、参与率和合约乘数均为 `RESEARCH_ONLY`；真实账户费率、乘数、账户杠杆及强平信息未核验。
- 历史发布延迟假设为闭合后 1ms；实际供应商延迟、修订和历史规格未核验。事件契约按 `available_at` 校验，只有明确标注的离线测试样本，无真实事件供应商。
- 1m/5m/15m/1h/1d 聚合仅接受完整连续闭合分钟；UTC 日界仅用于研究。源价冲突拒绝合并。
- TrendPullback 使用已闭合 1h 趋势和低周期回拉恢复，下一根开盘模拟成交。仓位参与率以先前已知成交量限制；未成交剩余取消。
- 出场在 1m OHLC 上模拟；同分钟止盈止损都触及时先止损。没有 tick 级成交顺序证明。资金费在结算所在分钟先于分钟出场计入；与入场同刻结算排除，该顺序属于披露的研究约定。
- 费用、价差、滑点和观察到的资金费纳入损益；三段 60/20/20 分别从初始权益开始，边界平仓。2x/5x 滑点情景重新按成本定仓，不是固定仓位的单项成本对比。
- 模拟保证金限制在现金内，默认研究单仓杠杆 20x；没有模拟真实强平和真实订单簿。回测候选永远 `executable=false`，不属于通过生产风控的交易计划。
- MeanReversion/EventDriven 仅提供插件接口和离线测试样本，未实现研究策略；Redis、持续 Worker、纸面订单和 2FA 按后续阶段实施。
- 最近基准 Holdout 结果为亏损。工程测试与短历史回测不能证明盈利或长期有效性。

## 安装与测试

依赖锁定在 `uv.lock`、`frontend/pnpm-lock.yaml`。首次安装需要网络。

```sh
uv sync --frozen --python 3.12 --group mac
cd frontend
pnpm install --frozen-lockfile
pnpm build
```

在工程根目录：

```sh
.venv/bin/pytest -m 'not network and not postgres' -q
.venv/bin/ruff check backend/app tests migrations
.venv/bin/mypy backend/app
```

数据库启动后，在隔离的一次性测试 schema 中运行集成测试（不清理现有研究表）：

```sh
QUANT_TEST_POSTGRES=1 .venv/bin/pytest -m postgres -q
```

最近验证：137 个离线测试通过；Ruff、mypy（23 个源文件）、TypeScript/Vite 构建通过。2 个 PostgreSQL 集成测试未运行；1 个可选公共网络测试未运行。
真实公共数据采集与界面操作另有实际证据，见 `reports/P1_RESEARCH_UPDATE.md`、`reports/p1_validation.json`。
历史搜索、删除与恢复的最新真实测试记录见 `reports/HISTORY_SEARCH_RECORD_DELETE_UPDATE_2026-10-11.md`。

## Git 同步范围

Git 保存源码、原始需求文档、配置模板、中文名称、依赖锁文件、迁移、自动化测试和技术验证报告。P0 公共只读接口的历史证据保留在 `reports/raw/`、`reports/specs/`，时间属于历史观测，不代表当前账户权限。

`.env`、本地连接配置、虚拟环境、Node 依赖、数据库、缓存、构建产物、采集数据、运行中的行情缓存、回测结果和运行审计均不进入 Git；这些文件继续保留在原 Mac 工程目录。新机器克隆后，先按「安装与测试」安装依赖，再采集历史数据。提交或推送不会启用真实交易。

## 文件与 API

- `backend/app/research_models.py`、`strategies.py`：研究契约、时点校验与插件。
- `research_data.py`：公共历史采集、闭合聚合、内容哈希、Parquet 与 DuckDB。
- `backtest.py`：研究回测、成本、时间分段、压力情景与结果哈希。
- `risk.py`：Decimal 风险纯函数与仅消费一次的模拟审批。
- `research_db.py`、`research_ledger.py`、`migrations/`：PostgreSQL 模型、迁移和显式元数据写入；本轮数据库运行验收未通过。
- `research_api.py`：本机公共研究任务、文件锁、进度与追加审计日志；数据库 job 表尚未接为任务权威台账。
- `local_postgres.py`、`local_workspace.py`、启动脚本：Mac 本地启动。
- `frontend/src/ResearchDesk.tsx`、`ResearchChart.tsx`：可操作的行情、研究与风险界面。
- `data/research/<id>/`：冻结 Parquet、资金费、采集时规格、原始响应、manifest。
- `reports/research/<run_id>.json`：可复查运行报告；`reports/research_jobs.jsonl`：任务审计。

新增 API：`POST /api/v1/market/{symbol}`、`GET /api/v1/research/status`、`GET/POST /api/v1/research/datasets`、`GET /api/v1/research/runs`、`POST /api/v1/research/backtests`、`POST /api/v1/risk/preview`、`GET /api/v1/research/results/{id}`。
所有 POST 仅接受本机可信 Origin、Host、JSON；没有订单路由，不接受密钥、外部 URL 或任意命令。
`/health/ready` 始终交易未就绪、HTTP 503；`/health/live` 只表示 API 存活。

P0 历史交付报告保留在 `reports/PHASE_0_REPORT.md`、`reports/P0_CONSOLE_UPDATE.md`；原 P0 README 另存 `reports/P0_CONSOLE_README_ARCHIVED.md`。
