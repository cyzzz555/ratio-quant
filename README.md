# ratio-quant · Quant System V1.2 本地研究工作台

一个量化交易程序。

当前为 **P3 离线纸面交易开发中，完整 P2 / P3 尚未验收**。行情、历史采集、研究回测和风险试算已经接入真实运行路径。
PostgreSQL 初始化被 Codex 沙箱的系统共享内存权限阻断，数据库迁移与持久风控锁的数据库集成验收仍待完成。
研究结果明确标为文件暂存，未使用 SQLite 冒充 PostgreSQL；启动数据库后可显式写入元数据台账。

`LIVE_TRADING_ENABLED=false`、`HUMAN`、`PAPER_BROKER` 保留。没有真实订单或认证账户访问路径。
P3 的离线纸面订单、模拟审批与持仓台账已接入；「交易准备」继续保留纯模拟风控计算。
42 轮决策及原始技术规格在 `docs/`；微资金本金亏损容忍 50%、常规单仓 10–20x、最高 25x 保留。
其余微资金风险参数保持研究/模拟候选，不能当作实盘授权。

## 在这台 Mac 运行

当前网页：[纸面交易](http://127.0.0.1:5173/#paper)、[实时监控](http://127.0.0.1:5173/#realtime)、[行情](http://127.0.0.1:5173/#market)、[历史与回测](http://127.0.0.1:5173/#research)、[交易准备](http://127.0.0.1:5173/#risk)。

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

1. 「合约行情」进入时读取一次 XAUUSDT 公共行情。搜索交易所当前 USD-M 合约代码或中文别名（如 BTC、比特币、黄金、英伟达），在下拉结果中选择合约即可读取行情；也可选择周期后点击「刷新行情」。目录自动缓存 5 分钟；「刷新合约目录」会立即重新核验，不再局限于原九个候选合约。目录按当前 FAPI 响应读取报价币种（包括 USDT、USDC、USD1 等），价格旁显示实际报价币种。支持美光 / Micron / 镁光和 SPCX / SpaceX / 太空探索搜索。中文为 `config/market_names.zh.json` 本地展示别名；未收录项显示「中文名待补充」，不代表底层资产或账户权限核验。图中仅使用闭合 K 线；未闭合样本隔离，悬停查看 OHLCV。1h/1d 可结合已采集历史；缺口不补造价格。此页为手动更新快照；P2 持续公共行情请进入「实时监控」。
   - 点击「补充中文名」打开写入窗口，可搜索合约或勾选「仅显示中文名待补充的合约」，选中后填写中文展示名称并保存。名称保存到 `config/market_names.zh.json`，立即用于显示和搜索；同资产、同类型合约同步更新，窗口会展示范围。关闭/取消不会写入。多个窗口同时修改同一名称时会提示冲突，需刷新后编辑；日志位于 `reports/market/name_updates.jsonl`。
2. 「历史与回测」与行情页共用当前合约目录、搜索和中文名称补充窗口。搜索并选中合约及 1–14 天，点击「采集历史数据」，后台重新逐品种核验当前规格后采集。进度自动更新。完整历史才能运行回测；这台 Mac 上的采集数据保存在 `data/`，新克隆仓库需要重新采集。
3. 选择数据集，编辑研究窗口、费用等假设，点击「运行研究回测」。完成后切换训练/验证/Holdout，查看权益曲线、指标、模拟成交、滑点情景，下载完整 JSON 报告。
   - 回测记录可筛选 7 / 30 / 90 天前的记录，选择后点击「删除此回测记录」并确认。结果移入回收站，可恢复；历史数据集、原始响应和审计证据保留，删除不释放这些文件占用的磁盘空间。
4. 「交易准备」填写模拟入场价、止损价、权益和风险预算，点击「计算模拟仓位」。数量向下取整，显示保证金、有效杠杆、两种回撤指标和开仓阻断原因。它不会发送订单。
5. 原 P0 合约能力、公共接口探测、证据弹窗和报告下载继续保留。

## P3 纸面交易场景模拟

打开「纸面交易」，创建虚拟 USDT 实验，写入手动模拟场景价，生成方案并在窗口中复核不可变订单 hash。填写页面显示的公开演练码、勾选人工确认，再提交到进程内 PaperBroker；21–25x 另需一个额外模拟码。公开演练码不是密码或真实 2FA，不能用于实盘认证。

订单支持部分成交、取消余量、资金费、减仓、保护止损/止盈和现金台账。故障演练可模拟响应丢失或保护单失败；未知状态只能按原 client order id 对账，不重发。重启后需人工恢复；恢复、追加资金或日界变化不会解除本金/高水位/日内持久锁。普通/优质预算按设计分别限制；优质标签在此仅是演练假设。

当前默认 `QUANT_PAPER_STORE=offline_file`，明确标为本机离线文件模拟，并不代替 PostgreSQL。单实验文件上限 32 MiB，校验失败或写入失败会阻断。数据库验收后可明确配置 `QUANT_PAPER_STORE=postgresql` 使用事务状态、事件、唯一订单与 outbox；该模式启动失败不会回退到文件。新迁移为 `002_paper`，实库集成仍待完成。

本阶段只有手动场景、假设线性 USDT 合约规则与模拟账户上限，不把公开目录价格、杠杆或强平假设当作真实账户能力。没有连接真实订单，尚未将 P2 信号转为持续前向纸面执行。详细文件变更、运行方法、验收结果和遗留项见 [P3 交付记录](reports/P3_PAPER_UPDATE_2026-10-12.md)。

## P2 实时监控首批功能

进入「实时监控」，共用中文搜索添加关注合约，点击「启动实时采集」。可选择启动时 USDT 成交额前 2 名发现池；逐品种重新核验公共规格，无账户权限推断。修改池先停止。当前首批支持 USDT/USDC 永续；其余目录产品启动时会明确拒绝。

持续接收闭合/未闭合分钟 K 线与标记价，断线退避重连并补数；缺口、时效、冲突及规格变化会阻断研究确认。研究候选只以闭合数据生成、下一根闭合低周期 K 线延续方向确认；规则分不是胜率。所有候选不可执行，通知仅页面展示。

MeanReversion / EventDriven 返回未完成状态，文件回放不代替数据库。页面、实际联网与离线回放测试和遗留项见 [P2 首批交付记录](reports/P2_FIRST_INCREMENT_2026-10-12.md)。API 与页面关闭后不会自动启动行情；关闭页面不会停止已启动 worker，请点击「停止采集」。

## 研究假设与边界

- 所有窗口、触发条件、成本、参与率和合约乘数均为 `RESEARCH_ONLY`；真实账户费率、乘数、账户杠杆及强平信息未核验。
- 历史发布延迟假设为闭合后 1ms；实际供应商延迟、修订和历史规格未核验。事件契约按 `available_at` 校验，只有明确标注的离线测试样本，无真实事件供应商。
- 1m/5m/15m/1h/1d 聚合仅接受完整连续闭合分钟；UTC 日界仅用于研究。源价冲突拒绝合并。
- TrendPullback 使用已闭合 1h 趋势和低周期回拉恢复，下一根开盘模拟成交。仓位参与率以先前已知成交量限制；未成交剩余取消。
- 出场在 1m OHLC 上模拟；同分钟止盈止损都触及时先止损。没有 tick 级成交顺序证明。资金费在结算所在分钟先于分钟出场计入；与入场同刻结算排除，该顺序属于披露的研究约定。
- 费用、价差、滑点和观察到的资金费纳入损益；三段 60/20/20 分别从初始权益开始，边界平仓。2x/5x 滑点情景重新按成本定仓，不是固定仓位的单项成本对比。
- 模拟保证金限制在现金内，默认研究单仓杠杆 20x；没有模拟真实强平和真实订单簿。回测候选永远 `executable=false`，不属于通过生产风控的交易计划。
- MeanReversion/EventDriven 仅提供插件接口和离线测试样本，未实现研究策略；持续公共 Worker 已作为 P2 首批功能实现；Redis、数据库台账与完整三策略尚未验收，纸面订单和 2FA 按后续阶段实施。
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

最近验证：215 个离线测试通过；Ruff、mypy（34 个源文件）通过；最近 TypeScript/Vite 构建通过。4 个 PostgreSQL 集成测试未运行；1 个可选公共网络测试未运行。
真实公共数据采集与界面操作另有实际证据，见 `reports/P1_RESEARCH_UPDATE.md`、`reports/p1_validation.json`。
历史搜索、删除与恢复的最新真实测试记录见 `reports/HISTORY_SEARCH_RECORD_DELETE_UPDATE_2026-10-11.md`。

## Git 同步范围

Git 保存源码、原始需求文档、配置模板、中文名称、依赖锁文件、迁移、自动化测试和技术验证报告。P0 公共只读接口的历史证据保留在 `reports/raw/`、`reports/specs/`，时间属于历史观测，不代表当前账户权限。

`.env`、本地连接配置、虚拟环境、Node 依赖、数据库、缓存、构建产物、采集数据、运行中的行情缓存、回测结果和运行审计均不进入 Git；这些文件继续保留在原 Mac 工程目录。新机器克隆后，先按「安装与测试」安装依赖，再采集历史数据。提交或推送不会启用真实交易。

### 公开仓库与密钥上传保护

仓库公开，可浏览和克隆；当前 Mac 的本地控制台仍只监听 `127.0.0.1`，公开源码不会开放账户或本地数据。当前阶段不接收账户密钥，不执行真实订单。

真实 API Key、API Secret、币安账户凭据必须保留在本机 `.env` 或 `secrets/`、`credentials/` 中，不得写入源码、中文名称、测试、报告或截图。`.env.example` 只允许空值、占位符和现有安全开关。凭据文件、私钥、GitHub CLI 的 `hosts.yml` 及常见密钥备份已加入忽略规则。

本机已启用提交前暂存区检查和推送前完整 Git 历史检查。新克隆的机器需要先安装 Python 3.12+，再在工程根目录执行：

```bash
chmod +x .githooks/pre-commit .githooks/pre-push
git config --local core.hooksPath .githooks
python3 backend/app/git_secret_guard.py --history
```

检测器直接读取 Git 中将上传的文件，拦截凭据文件、API/币安密钥字段、常见服务令牌、私钥、带密码的连接地址和疑似 64 字符令牌；输出仅包含文件位置和规则，不包含匹配的密钥。即使工作文件中的密钥已删除，只要旧提交仍包含密钥，推送检查仍会拒绝。扫描出错也会阻止操作。

GitHub 的 Secret scanning 和 Push protection 已核验为启用；另有 `credential-guard` 工作流检查完整历史。云端工作流发生在上传之后，本机钩子才负责上传前检查。GitHub 推送保护只覆盖其支持的模式；这些检查无法保证识别所有编码、拆分或未知格式的密钥，不要跳过钩子或强制添加凭据文件。如果真实凭据曾被提交，应先撤销/轮换凭据，再处理历史，不要仅删除当前文件。

## 简化模式与完整模式

历史采集、TrendPullback 回测和纯模拟风险试算默认显示简化模式。点击各区域的「选择历史采集模式」「选择研究回测模式」或「选择风险试算模式」，在窗口中选择模式后确认；取消或 Esc 不应用选择。

- 历史采集：搜索代码或中文名称，选择合约，再选最近 1、7 或 14 天，点击「采集历史数据」。完整模式支持 1–14 天自填；切回简化模式保留自填天数。采集成功后自动选中新数据集，供回测使用。
- 研究回测：选择完整数据集、5m / 15m、模拟初始权益和单笔风险，点击「运行研究回测」。成本、乘数和策略窗口的当前值明确显示，展开「更多回测参数」可编辑，完整模式展开全部参数。
- 风险试算：填写本金、权益、历史最高权益、方向、入场、止损、风险和单仓杠杆，再点击「计算模拟仓位」。净入金、现有与待成交仓位、成本、步长和最小金额在附加参数中显示并可展开编辑。输入改变时清除旧结果，需重新计算。

界面模式仅在当前页面期间保留；切换模式保留当前数值，刷新或离开页面后仍使用既有研究示例初值。简化模式不批准研究参数、不自动核验账户、不发送订单。所有成本、规格和微资金候选仍按研究假设处理。

前端参数测试（Node 24，亦支持带 `--experimental-strip-types` 的 Node 22.6+）：

```bash
cd frontend
pnpm test
pnpm build
```

本轮实际验证见 `reports/SIMPLE_MODE_UPDATE_2026-10-11.md`。

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
