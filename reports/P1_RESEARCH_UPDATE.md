# P1 研究工作台更新 · 2026-10-10

状态：**P1 开发中，未完成验收。** 已接入真实行情、历史数据采集、研究回测和风险试算。
原 P0 页面只有公共能力核验，无法满足行情、回测和交易操作需求。本次增加实际研究流程；没有把静态展示或回测成交当作纸面订单。

## 文件变更

| 文件 | 变更与用途 |
|---|---|
| `backend/app/research_models.py` | UTC、Decimal、研究 K 线、MarketContext、CandidateSignal、历史事件 available_at、参数校验 |
| `research_data.py` | 逐品种证据前置核验，公共 1m 历史分页、资金费，冻结 Parquet 与哈希，DuckDB，闭合多周期聚合 |
| `strategies.py` | TrendPullback 研究基准；MeanReversion/EventDriven 插件接口与测试样本，无正式启用策略 |
| `backtest.py` | 时间顺序 60/20/20 分段，下一根开盘、分钟出场、成本和资金费、部分成交、滑点情景、结果哈希 |
| `risk.py` | 独立风险纯函数、数量向下取整、保证金、有效杠杆、两种回撤、候选规则优先级和一次性模拟审批 |
| `research_db.py`、`research_ledger.py` | PostgreSQL 模型及显式文件暂存入库；数据库运行仍未验证 |
| `research_api.py`、`main.py` | 本机研究 API、异步进度、跨进程任务锁、审计；未创建订单路由 |
| `local_postgres.py`、`local_workspace.py`、`启动研究工作台.command` | 用户私有 socket 数据库及 Mac 启动脚本 |
| `migrations/`、`alembic.ini` | Alembic 001_research 迁移；已生成 PostgreSQL SQL，未执行数据库迁移验收 |
| `frontend/src/ResearchDesk.tsx`、`ResearchChart.tsx`、`api.ts`、`researchTypes.ts` | 可操作研究表单、行情蜡烛、净权益曲线、指标、模拟成交与风险结果 |
| `frontend/src/main.tsx`、`style.css`、`index.html` | 新增 3 个入口，保留 5 个 P0 入口，小窗口布局、中文阻断原因、阶段标签 |
| `tests/test_research.py` | 40 个离线研究测试，包括实际成本、资金费方向、数据哈希、未来数据、部分成交和任务锁 |
| `tests/test_research_postgres.py` | 2 个待实际运行的隔离 schema 数据库集成测试 |
| `pyproject.toml`、`uv.lock`、`.gitignore`、`README.md` | 锁定研究依赖，忽略本机数据库连接配置与运行目录，更新运行说明 |

原交接 `docs/`、`config/` 中的风险授权状态保持不变。

## 运行与界面操作

网页：[行情](http://127.0.0.1:5173/#market) / [历史与回测](http://127.0.0.1:5173/#research) / [交易准备](http://127.0.0.1:5173/#risk)。
在 Finder 双击工程内 `启动研究工作台.command`；已提供现有虚拟环境和 Node/pnpm 路径支持。
也可进入工程目录，在 Mac 终端执行：

```sh
PYTHONPATH=backend .venv/bin/python -m app.local_workspace
```

脚本已通过 `zsh -n`。PostgreSQL 必须在 Mac 终端验证启动；当前 Codex 沙箱执行失败，不能宣称脚本端到端通过。
当前 API 与前端已运行，可直接使用明确标记的文件研究模式。PostgreSQL 就绪后脚本会执行迁移并将暂存研究元数据入库。

使用步骤：选择行情合约和周期 → 刷新行情；研究页选择天数 → 采集历史 → 选择完整数据集 → 运行研究回测 → 切换三段结果并下载报告；交易准备页 → 计算模拟仓位。
P3 纸面订单操作尚未实现。前期真实订单始终禁用。

## 真实测试结果

| 项目 | 结果 |
|---|---|
| 离线 pytest | **109 passed, 3 deselected**，1 条现有 Starlette/httpx 弃用警告 |
| Ruff | 通过：backend/app、tests、migrations |
| mypy | 21 个源文件通过 |
| TypeScript / Vite | 通过，31 个构建模块 |
| Alembic 离线 PostgreSQL SQL 生成 | 通过；这不是数据库迁移执行成功 |
| Mac 启动脚本 shell 语法 | 通过；数据库端到端启动未通过 |
| PostgreSQL 初始化 | 两次实际执行均失败：`shmget ... Operation not permitted`；改为 mmap 后仍需要小段 SysV 共享内存 |
| PostgreSQL 集成测试 | **未运行 2 个**，不能算作通过 |
| 可选 P0 公共联网 pytest | 本轮未运行 1 个；下列历史采集为另行实际联网执行 |
| 真实 XAUUSDT 历史 | 两份 7 天快照，每份 **10,080 根闭合分钟 K 线、42 条资金费记录、0 缺口** |
| 真实历史请求审计 | 共 **210 次**，全部为公共 GET，无认证账户或订单请求 |
| 浏览器操作 | 实际点击行情、回测与风险计算；小时周期167根、日线6根完整闭合聚合；未闭合样本隔离；浏览器错误日志0条 |
| 同参重复回测 | 两个 run ID 不同，数据/参数/代码/结果哈希全部一致 |
| 风险试算 | 权益1000、入场100、止损98、风险1%、20x：数量5，名义500，理论保证金25；未知杠杆与强平价阻断开仓 |
| 订单与安全 API | `POST /orders` 404，非本机 Origin 风险请求403，`/health/ready` 503、交易未就绪，LIVE=false |

实际回测记录：

- `84e219c7-b6e5-4382-851a-9b59a9e7860f`
- `f55a7fc2-ef07-4ca4-bdc4-f5325226cad3`
- result hash：`38cc671f6c6ee40296847e960e7be78715500cc95d7bb3ecf9722574000473e7`

最近研究 Holdout：模拟净收益 **-180.29 USDT（-18.03%）**，最高净值回撤 **18.54%**，**28 笔**。
该亏损结果保留。没有据此优化参数、宣称盈利或授权交易。

原始验证结果：`p1_validation.json`；执行输出：`p1_tests.txt`、`p1_ruff.txt`、`p1_mypy.txt`、`p1_frontend_build.txt`；UI截图：`p1_market_ui.png`。

## 已完成与验收边界

完成：带证据的公共行情、完整历史采集、Parquet/DuckDB、闭合聚合、研究契约、时点模型、TrendPullback 基准、费用/资金费/滑点、时间分段、复现哈希、纯风控数学、模拟审批预算与实际研究界面。
已编写但尚未验收：PostgreSQL/Alembic 运行、元数据事务写入和数据库持久锁重启/注资集成测试。
因此 **不得把本更新标记为 P1 全部验收通过，也不跳转到 P2/P3**。

## 遗留问题与后续阶段

1. 在 Mac 终端运行启动脚本完成 PostgreSQL 启动和迁移；再运行 `QUANT_TEST_POSTGRES=1 .venv/bin/pytest -m postgres -q`。数据库 job 表尚未接为任务权威台账，当前任务状态以加锁文件暂存。
2. 历史规格、乘数、真实账户手续费、强平模型、时段/指数映射和账户权限仍未知。历史发布延迟只有研究假设；没有真实事件供应商。
3. MeanReversion/EventDriven 尚无研究策略实现，只提供插件接口与离线样本。
4. 数据仅短历史，不证明长期有效性；2x/5x 滑点情景会重新定仓，收益变化并非固定仓位成本比较。
5. P2 持续行情/安全降级、P3 纸面订单与审批持仓工作流尚未实现；认证只读核验在P4；真实执行只可在P5独立明确授权后开发。

保留 50% 初始本金亏损容忍和常规10–20x/最高25x单仓杠杆。2x整体有效杠杆、40%提前锁定等仍为研究/模拟候选；没有改成实盘配置。
