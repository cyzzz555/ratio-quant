# Quant System V1.2 · Phase 0

本工程完成公开行情接口能力探测、基础 Python/FastAPI + TypeScript/React 工程、
版本化证据与小样本闭合行情归档。当前阶段为 **P0，只读**。
`LIVE_TRADING_ENABLED=false`；没有下单代码、账户认证、策略或真实订单运行路径。

交接文件已按 SHA256 验证。已确认的 42 轮设计要求保存在 `docs/01_DECISIONS_42.md`。
微资金 50% 本金亏损容忍、常规单仓 10–20x、最高 25x 设计要求保留；
`config/settings.example.yaml` 中微资金其余阈值保持 `RESEARCH_ONLY_NOT_USER_APPROVED`。
示例配置仅作为设计/研究配置读取，不能通过环境变量解锁实盘。

## 安装与启动

工具链：Python 3.12+（本次使用 3.12.14）、uv 0.13.0、Node.js 24、pnpm 11.25.0。
Python 完整传递依赖在 `uv.lock`，前端完整传递依赖在 `frontend/pnpm-lock.yaml`。
初次安装需要网络；离线测试不访问交易所。

在工程根目录：

```sh
uv sync --frozen --python 3.12
uv run pytest -m 'not network'
uv run ruff check backend tests
uv run mypy backend/app
```

运行真实公共只读探测（不需要 API key）：

```sh
PYTHONPATH=backend uv run python -m app.probe
# 如当前网络不支持 WS，可跳过并保留 UNVERIFIED：
PYTHONPATH=backend uv run python -m app.probe --no-ws
# 可选联网集成测试，不能作为默认 CI 必通过项：
RUN_NETWORK_TESTS=1 uv run pytest -m network
```

终端 A：

```sh
PYTHONPATH=backend uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

终端 B：

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm build
pnpm dev
```

打开 `http://127.0.0.1:5173` 查看 P0 操作控制台。前端通过 Vite 代理调用本地 API。
导航提供运行总览、合约能力、只读探测、数据与报告、安全与阶段五个页面。
合约页支持搜索、能力筛选和证据详情弹窗；报告页支持 JSON/CSV/Markdown 下载。
点击「只读探测 → 运行只读探测」可启动固定公共探测程序，查看逐品种日志和任务进度。
运行中每 2 秒轮询任务状态，完成后自动加载新报告；「刷新报告」只重读本地快照。
探测最多运行 180 秒，启动至少间隔 60 秒，跨 UI/CLI 使用文件锁禁止并发采集。
开发服务器只绑定回环地址；云端公开部署与认证、HTTPS 属于后续阶段。
`pnpm preview` 仅提供静态构建预览，无开发代理，查看实时 API 应使用 `pnpm dev`。

## API 语义

| 路径 | 行为 |
|---|---|
| `GET /health/live` | 进程存活，HTTP 200；不代表能交易 |
| `GET /health/ready` | P0 始终 HTTP 503、`trading_ready=false`、`allow_new_risk=false`；报告缓存时效单列 `service_ready` |
| `GET /api/v1/instruments` | 返回能力报告；报告缺失/损坏返回 HTTP 503 |
| `GET /api/v1/probe` | 最近本地探测任务状态、进度和最多 16 KB 日志尾部 |
| `POST /api/v1/probe` | 仅本机可信 Origin 的空 JSON 请求可启动固定只读任务；返回 202；并发 409、冷却 429 |
| `GET /api/v1/data-quality` | 经类型校验的最近样本质量；缺失/无效返回 503 |
| `GET /api/v1/reports/{name}` | 固定白名单报告下载：capabilities_json、capabilities_csv、quality_md、quality_json |

GET 接口不会自动访问 Binance；更新证据需显式运行 CLI 探测或点击控制台探测按钮。
本地 POST 仅启动采集任务，交易所流量仍为白名单公共 GET 与 WebSocket 接收。
不接受命令、交易参数、URL、文件路径或账户凭证。页面显示的是带时间戳的快照。
任务状态及日志保存在 `reports/jobs/`；服务中断后不把遗留 RUNNING 状态伪装成正常运行。
证据缓存就绪窗口为 15 分钟，这只是 P0 服务状态检查，不是实盘风险参数。

## 工程与证据

| 目录 | 内容 |
|---|---|
| `backend/app` | 只读 GET 白名单、限速/重试/审计、模型、规范化、Parquet、能力探测、FastAPI |
| `frontend` | React/TypeScript 五页 P0 操作控制台、只读任务与证据详情，无交易按钮或账户凭证 |
| `tests` | 离线测试与显式启用的公共联网测试 |
| `config`、`docs`、`codex` | 原始交接规格与候选配置，保留状态标签 |
| `contracts/phase0*` | P0 版本化类型契约；原始后续阶段契约保留 |
| `reports/raw/<run_id>` | 每次 HTTP 请求记录、原始响应及 SHA256；WS 有效帧或错误证据 |
| `reports/specs`、`reports/sessions` | 按内容哈希版本化的合约过滤规则与底层时段快照 |
| `reports/runs` | 历次能力报告，失败运行不抹去历史证据 |
| `reports/instrument_capabilities.json`、CSV | 当前运行的逐候选能力结果 |
| `reports/data_quality_report.md`、JSON | 闭合/未闭合/缺口/异常/时效报告 |
| `data/closed`、`data/open` | 闭合 Parquet 与隔离的未收盘快照 |
| `decisions/pending.csv` | 逐品种权限核验与待批准问题 |

Decimal 在 Parquet 数值列以精确十进制字符串保存，不转浮点；时间列为 UTC timestamp。
REST 不提供 WS 事件时间，故 `exchange_event_at=null`，不能把 close time 冒充 event time。
REST 闭合判定采用请求前已核验服务器时钟的保守下界；服务器时钟不可核实时不标闭合。
归档按 `(venue,instrument,timeframe,open_time,source)` 去重，已闭合价格冲突拒绝覆盖。
P0 归档为本地单写入流程，文件锁+原子替换；云端持续采集与事务数据库在后续阶段实现。

## 能力范围及阶段边界

目前实现且实际探测的是明确的 USDⓈ-M 公共产品族。
Spot、COIN-M、Stocks API 不被隐式复用；未在该族观测到的符号保持 UNKNOWN。
有效公共规格标 `VERIFIED_PUBLIC`，不能升级为 `VERIFIED_ACCOUNT`。
最大杠杆不从 `requiredMarginPercent` 推算；账户资格、逐仓、保护单和 reduceOnly 均待核验。
WS 只有收到符号/周期匹配且时效合格的数据帧才算样本成功；握手/ACK 不算成功。
超时保留为 UNVERIFIED，不能证明合约没有 WS 或已下架。

P0 契约升级为 `phase0.v2`：公共可见性支持 `null`（未知）与 `false`（完整响应中未观测）
分别表达。原始 `instrument_capabilities.schema.json` 保持不变；不要用其布尔字段把未知变成否。
具体底层标的映射、合约乘数、底层时段与衍生品时段/指数定价机制保持 UNVERIFIED。
`history_start_at` 仅代表 `startTime=0` 查询返回的首个时间；小样本不证明长期数据完整性。

阶段验收与真实执行记录见 `reports/PHASE_0_REPORT.md`、`reports/validation_results.json`。
操作控制台补充交付与最新验证见 `reports/P0_CONSOLE_UPDATE.md`、`reports/console_validation.json`。
本次未进入 P1；PostgreSQL/Redis/DuckDB、持续 Worker、回测、策略、人审和纸面交易闭环按交接路线后续实施。
