# Quant System V1.2 · P0 工程约束

默认以简体中文沟通。交接来源约束见 `codex/AGENTS.md`、`00_START_HERE.md` 与 `docs/`。

- 当前仅 P0；未经阶段验收不进入后续开发。
- `LIVE_TRADING_ENABLED=false`、`APPROVAL_MODE=HUMAN`、`TRADE_ADAPTER=PAPER_BROKER`。
- 本工程不包含执行适配层，不接收账户密钥，不实现订单调用。
- 公共行情可见不代表账户/地区/杠杆能力。未核验项不得填 YES/0/假价格。
- 保留微资金 50% 本金损失容忍、常规单仓 10–20x、最高 25x；其余候选风险参数状态不变。
- 数值使用 Decimal，时间为 UTC-aware，报告保留原始响应、哈希与错误。
- 新增模块必须提供类型与必要测试。默认测试离线；联网测试必须显式启用。
- 验证命令：`uv run ruff check backend tests`、`uv run mypy backend/app`、
  `uv run pytest -m 'not network'`、`cd frontend && pnpm build`。
