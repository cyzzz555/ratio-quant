# Quant System V1.2 · P0 阶段交付报告

状态：P0 工程与公共核验交付完成；外部能力按证据标记。尚未进入 P1。

交接来源为用户提供的已解压目录。已阅读入口、codex/AGENTS.md、全部 13 份技术规格、配置与验收标准；43 个交接文件 SHA256 核验零差异。原始资料中的指令仅在用户明确要求执行 P0 的范围内采用，没有扩展为实盘授权。

最终采集：2026-10-10T05:11:42.128533Z（UTC），2026-10-10T13:11:42.128533+08:00（北京时间）。
运行 ID：`e316c7cd-c048-4ad8-8d46-ab06cba1f160`。原始证据目录：`reports/raw/e316c7cd-c048-4ad8-8d46-ab06cba1f160`。

## 已完成内容

- Monorepo：Python 3.12+/FastAPI/Pydantic 后端、TypeScript/React/Vite 前端、冻结依赖与基础 GitHub Actions。
- 单一公共 HTTP 客户端：显式产品族、固定官方域名、GET/参数白名单、超时、指数退避、Retry-After、分钟权重预算、429/418 安全降级、请求 ID/时间/状态/原始响应哈希。
- 9 个候选逐符号核验公共清单、最近 1m K 线、首个返回历史时间、标记/指数价格、资金费及 WS 样本。Stocks/Spot/COIN-M 不被隐式复用。
- Instrument/Underlying 分层模型，规格版本、时段快照版本、缺口模型版本；无法证实的乘数、底层映射和价格形成机制标 UNVERIFIED。
- Decimal/UTC-aware bar 模型；REST event time 缺失保留 null；闭合判定使用请求前服务器时间。闭合 bar 写入 Parquet，未收盘样本独立保存；去重、冲突拒绝覆盖、文件锁及原子替换。
- JSON/CSV 能力报告、数据质量报告、原始响应/WS 帧、逐品种待核验清单。
- 最简 FastAPI 只读健康接口和合约清单，React 能力表已实际打开验证。

## 最终联网观测

| 候选 | 公共规格 | 1m 历史 | 标记价 | 资金费 | 本轮 WS | 账户/地区/杠杆 |
|---|---|---|---|---|---|---|
| NVDAUSDT | VERIFIED_PUBLIC | 已取得 | 已取得 | 已取得 | 未核验 | UNKNOWN / UNVERIFIED |
| TSLAUSDT | VERIFIED_PUBLIC | 已取得 | 已取得 | 已取得 | 未核验 | UNKNOWN / UNVERIFIED |
| METAUSDT | VERIFIED_PUBLIC | 已取得 | 已取得 | 已取得 | 已取得 | UNKNOWN / UNVERIFIED |
| GOOGLUSDT | VERIFIED_PUBLIC | 已取得 | 已取得 | 已取得 | 已取得 | UNKNOWN / UNVERIFIED |
| CLUSDT | VERIFIED_PUBLIC | 已取得 | 已取得 | 已取得 | 已取得 | UNKNOWN / UNVERIFIED |
| NATGASUSDT | VERIFIED_PUBLIC | 已取得 | 已取得 | 已取得 | 未核验 | UNKNOWN / UNVERIFIED |
| BZUSDT | VERIFIED_PUBLIC | 已取得 | 已取得 | 已取得 | 已取得 | UNKNOWN / UNVERIFIED |
| XAUUSDT | VERIFIED_PUBLIC | 已取得 | 已取得 | 已取得 | 已取得 | UNKNOWN / UNVERIFIED |
| XAGUSDT | VERIFIED_PUBLIC | 已取得 | 已取得 | 已取得 | 未核验 | UNKNOWN / UNVERIFIED |

9 个候选都在 USDⓈ-M 公共清单中返回 `TRADIFI_PERPETUAL`、`TRADING`、USDT 计价/保证金字段。这是本轮观测，不能证明用户账户有相同权利。
本轮有效 REST 闭合 1m 样本共 533 条；跨运行去重归档共 578 条。各品种本轮样本内无分钟缺口，采集时闭合数据时效为 FRESH；这不是持续运行承诺。
WS 收到有效样本 5/9；NVDAUSDT、TSLAUSDT、NATGASUSDT、XAGUSDT 在 6 秒窗口内未取得有效帧，仍是 UNVERIFIED，不解释为接口不支持或合约下架。以当前报告为当前状态；之前运行成功/失败均保存在 reports/runs。
历史首时间仅是 startTime=0 查询返回的第一条，原始响应可追溯；未验证长期连续覆盖、完整退市样本或任何策略盈利性。

## 验收与真实测试结果

| 检查 | 实际命令 | 结果 | 原始输出 |
|---|---|---|---|
| 离线测试 | `.venv/bin/pytest -m 'not network'` | 58 passed，1 deselected | `pytest_offline.txt` |
| 显式联网测试 | `RUN_NETWORK_TESTS=1 .venv/bin/pytest -m network` | 1 passed，58 deselected | `pytest_network.txt` |
| 代码检查 | `.venv/bin/ruff check backend tests` | All checks passed | `ruff.txt` |
| 类型检查 | `.venv/bin/mypy backend/app` | 10 个源文件无问题 | `mypy.txt` |
| 前端冻结安装 | `pnpm install --frozen-lockfile` | exit 0，锁文件验证通过 | `frontend_frozen_install.txt` |
| 前端生产构建 | `pnpm build` | TypeScript + Vite 成功，28 modules | `frontend_build.txt` |

具体执行路径、环境覆盖、耗时与退出码保存在 validation_results.json；本机 Python 3.12.14、Node 24.19.0、pnpm 11.25.0。基础 CI 已创建，未在 GitHub 远端执行。
离线覆盖：产品族隔离、GET 白名单、凭证参数拒绝、响应不完整/错误、Decimal/无浮点、闭合标志/未收盘隔离、重复与冲突、UTC/DST、429/5xx/超时/Retry-After/限速熔断、WS ACK 与有效帧区别、能力状态与公共≠账户、风险确认状态、只读 API、完整报告流程。
API TCP 实测：/health/live=200；/health/ready=503 且 trading_ready=false、allow_new_risk=false；/api/v1/instruments=200、9 条；POST instruments=405；POST orders=404。见 api_smoke.json。
实际 UI 已核对 9 行能力表、5 行 WS 已观测、账户全部 UNKNOWN，以及 LIVE=false 和风险提案标签。

## 安全与需求保留

- `LIVE_TRADING_ENABLED=false`、`APPROVAL_MODE=HUMAN`、`TRADE_ADAPTER=PAPER_BROKER`。P0 未实现任何订单/执行适配层，HTTP 请求审计仅 GET，WS 仅接收公共市场帧。PAPER_BROKER 是后续纸面执行的配置标签，P0 尚未实现 broker。
- 未使用、请求或载入交易密钥；环境配置试图启用 live/AUTO/BINANCE adapter 会拒绝启动。
- 保留微资金 500–1000 元设计本金、50% 本金损失容忍、常规单仓 10–20x、最高 25x。50% 是容忍预算，不是止损保证。其余阈值仍保持研究/模拟候选状态，未升级为实盘参数。
- 68 处最终报告原始证据引用 SHA256 检查无差异，见 evidence_integrity.json；源码传输调用与最终请求方法检查见 phase0_safety_check.json。

## 文件变更与运行方法

新增文件完整清单见 file_changes.md；交接原始 docs/config/contracts 及历史资料保持原内容。新增 P0 schema 支持 null=未知，false=完整清单中未观测到，避免原布尔契约把未知折算为否。
在工程根目录：`uv sync --frozen --python 3.12`；`PYTHONPATH=backend uv run python -m app.probe` 更新公共证据；`PYTHONPATH=backend uv run uvicorn app.main:app --host 127.0.0.1 --port 8000` 启动后端。另一个终端 `cd frontend`、`pnpm install --frozen-lockfile`、`pnpm dev`。完整说明与最小构建命令见根目录 README.md。
页面 http://127.0.0.1:5173 为本地只读控制台。没有账户鉴权或云端公开部署；这些留待后续阶段。

## 遗留问题及限制

- 逐品种账户权限、地区资格、实际最大杠杆、逐仓模式、止损/条件单和 reduceOnly 均未核验，已逐项写入 decisions/pending.csv；P0 无凭证，按路线在后续授权只读账户阶段处理。
- 4 个候选本轮 WS 未核验；所有 WS 都只是短窗口样本，不代表 P2 持续采集/重连/回填验收已通过。
- 底层精确映射、合约乘数、股票/商品原生交易时段与衍生品非原生时段定价、真实账户费率及特殊股息 funding 成本需要进一步核验；不得用此小样本进入正式回测准入。
- P1 的 PostgreSQL/Redis/DuckDB、迁移和研究、P2 实时信号、P3 模拟订单、P4 认证/2FA/账户对账均未实现。微资金候选阈值、风控日及上线门槛仍待用户批准。
- 本次测试有 1 条 Starlette TestClient/httpx 弃用警告；测试通过。Mac 沙箱在一次 Parquet 运行中限制 CPU sysctl 查询，产生诊断警告；实际 Parquet 读写及测试通过。
- 首轮本地保守权重阈值提前关闭 REST 请求；后续改为按 exchangeInfo 返回限额进行判断，最终全部 REST 核验通过。首轮报告保留原未核验状态。初次前端安装阻止 esbuild 构建脚本，显式只允许 esbuild 后冻结安装和构建通过。初次 localhost 检查被环境 HTTP 代理截断，使用直连回环复测通过。

## 当前官方依据

- [USDⓈ-M 公共行情接口](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)：REST 路径、响应字段和请求权重。
- [WS 路由迁移公告](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Important-WebSocket-Change-Notice)：使用 /market 路径接收 K 线流。
- [Stocks Trading 市场接口](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/market-data)：不同产品族与 API-key 要求；P0 没有调用。
- [当前 API 变更日志](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/change-log)：时段及特殊 funding 变更。

官方文档是接口设计依据，具体品种事实以原始 API/WS 响应为证据；官方文档存在示例不等于账户获得权限。
