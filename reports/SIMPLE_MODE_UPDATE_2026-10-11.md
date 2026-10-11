# 历史采集、TrendPullback 与风险试算简化模式

日期：2026-10-11，Mac 本地实际运行验证。阶段：P1 研究界面增量；P1 整体验收仍待 PostgreSQL。

## 已完成与文件变更

- `frontend/src/WorkflowMode.tsx`：通用模式选择弹窗、简化/完整单选、确认/取消/Esc、原生模态焦点隔离、关闭后返回入口按钮；通用带约束数字输入和附加参数摘要。
- `frontend/src/workflowForms.ts`：类型化字段、既有研究初值和请求序列化。Decimal 保持字符串，仅窗口根数和单仓杠杆转换整数。界面模式不进入请求，不改变参数和批准状态。
- `frontend/src/ResearchDesk.tsx`：三个区域默认简化模式；采集支持 1/7/14 天和完整模式自填；切换保留自填天数。采集成功自动选择新数据集。回测显示数据集、周期、权益和风险，成本/乘数/窗口摘要和折叠编辑保留。风险保留本金/净权益/最高权益等常用输入，净入金/已有仓位/规格假设摘要及折叠编辑；改动参数后清除旧试算结果。任务运行中禁用参数修改和模式入口。
- `frontend/src/style.css`：模式卡片、选中状态、参数折叠区和响应式窗口样式。
- `frontend/tests/workflowForms.test.mjs`、`frontend/package.json`：5 项自动测试及 `pnpm test`，无新增依赖。
- `.github/workflows/ci.yml`：现有 Node 24 构建之后运行前端参数测试。
- `README.md`：中文使用步骤、模式生命周期、测试方法。
- 本报告：记录真实验证和阶段遗留问题。

## 使用与运行方法

当前本地 API `http://127.0.0.1:8000` 与前端 `http://127.0.0.1:5173` 已运行。前端服务已重启以刷新旧开发服务缓存。

1. 打开 `http://127.0.0.1:5173/#research`。历史采集点击「选择历史采集模式」，研究回测点击「选择研究回测模式」。选择简化/完整并确认；取消或 Esc 保留原模式。
2. 简化采集：搜索代码/中文名 → 选择合约 → 选择天数 →「采集历史数据」。完成后新数据集自动进入回测选择框。
3. 简化回测：数据集 → 周期 → 权益和单笔风险 →「运行研究回测」。成本与窗口当前值仍显示，可展开「更多回测参数」修改。
4. 打开 `http://127.0.0.1:5173/#risk`，点击「选择风险试算模式」。填写资金、入场、止损等，再点击「计算模拟仓位」；净入金、仓位和规格参数可展开修改。

模式和表单值仅在当前页面组件期间保留。切换简化/完整不会重置；刷新或离开页面后仍用原有研究示例初值。选择模式本身不会开始任何任务。

手动启动（工程根目录，分别在两个终端运行）：

```bash
PYTHONPATH=backend LIVE_TRADING_ENABLED=false APPROVAL_MODE=HUMAN TRADE_ADAPTER=PAPER_BROKER .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd frontend
pnpm dev
```

## 真实测试结果

自动验证，2026-10-11 本机实际执行：

```text
cd frontend && pnpm build                                      PASS（TypeScript + Vite，36 modules）
cd frontend && pnpm test                                       5 passed，0 failed
.venv/bin/ruff check backend/app tests migrations               PASS
.venv/bin/mypy backend/app                                     PASS（24 source files）
.venv/bin/pytest -m 'not network and not postgres' -q            167 passed，3 deselected
git diff --check                                               PASS
```

pytest 有 1 条现有 Starlette/httpx 弃用警告。未运行被排除的网络/PostgreSQL 集成用例；下面公共采集为真实联网操作。

浏览器通过界面实际验证：

- 风险完整模式填写权益 650、本金 1000、后续净入金 100、最高权益 1300；切回简化并计算，显示本金损失 **45%**、高水位回撤 **57.6923%**，本金模拟锁定提示仍保留。
- 修改输入后，旧「开仓检查」及结果清除。
- 26x 显示「单仓杠杆超过 25x 用户上限」；未自动降为 25x。账户上限和强平信息仍未核验。
- 恢复权益/本金/最高权益 1000、净入金 0、入场 100、止损 98、风险 1%、杠杆 20x、步长 0.001：风险预算 **10**、数量 **5**、名义金额 **500**、理论保证金 **25**、有效杠杆 **0.5**；未解锁交易。
- 清空折叠区数量步长、折叠后提交：原生必填校验阻止提交，并自动展开对应区域定位错误输入。
- 模式选择后按 Esc：不应用未确认选择。最终版本实际读到关闭后焦点是「选择研究回测模式」按钮，打开模态数量为 0。
- 完整采集自填 3 天切回简化：仍显示「3 天 · 沿用已填写数值」。搜索「美光」匹配 MUUSDT，目录含 789 个公共合约。
- 研究完整模式手续费填写 **7.125 bps**，切回简化，摘要与实际报告均保留此值。使用新采集数据集 `ed09da64-c866-4263-b7c4-e343e3145a15`，回测 `e7b5dc5a-3958-4543-afcf-b31ba758c870` 成功、Holdout 4 笔模拟交易。
- 最终版本简化采集 MUUSDT 1 天成功，**1440 根闭合 1m K 线、3 条 funding、0 缺口、完整范围为 true**。数据集 `b22e9844-eeaa-4084-83c3-7d396febaeb6` 在完成后自动选中；直接点击回测成功，运行 `f7f595fa-4ef0-492d-857d-6e9f152dd2d3`，状态 `RESEARCH_ONLY`。Train / Validation / Holdout 模拟交易笔数 **1 / 3 / 4**；Holdout 净收益 **-11.9793775741125000 USDT**。此结果用于验证流程，不构成策略有效性证据。
- 原有 6 条回测记录保留；本轮增加 2 条独立验证回测，没有删除或覆盖原报告。
- `/health/live` 实际返回 `alive=true`、`live_trading_enabled=false`。

本机截图位于工程上一级 `outputs/`：`quant-simple-risk-2026-10-11.png`、`quant-simple-research-2026-10-11.png`、`quant-simple-mode-window-2026-10-11.png`。研究行情原始数据、运行结果、审计和截图不随源码上传。

## 遗留问题与安全边界

- PostgreSQL 仍返回未就绪，研究元数据为 `FILE_STAGING_PENDING_POSTGRESQL`。本次 UI 功能完成不代表 P1 全阶段验收通过。
- 账户权限、真实费率、逐品种历史规格、最大杠杆、强平参考价仍未完成账户核验。公共合约目录和采集时规格核验不能代替账户权限。
- 风险表单沿用原有纯函数接口：未输入的单日亏损/组合风险示例为 0，已在界面说明，不能理解为真实账户风险状态；持久风控状态和真实账户对账等待后续阶段。
- 50% 本金损失容忍预算、常规 10–20x、最高 25x 保留；其余候选仍仅模拟。简化模式未新增例外批准、账户能力或订单路由。
- `LIVE_TRADING_ENABLED=false`、人工批准模式和密钥上传防护保留；P3 纸面订单/审批/持仓尚未实现。
