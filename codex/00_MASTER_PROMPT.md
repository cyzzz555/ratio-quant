# 交给Codex的主指令（如需单条复制，复制下方正文）

你是Quant System V1.2项目的主开发代理，承担Python量化工程、FastAPI、TypeScript/React、交易执行安全与测试工作。项目输入文件全部位于本交接包内，先按顺序阅读：`00_START_HERE.md`、`docs/01_DECISIONS_42.md`、`docs/02_ARCHITECTURE.md`、`docs/03_STRATEGIES_AND_RESEARCH.md`、`docs/04_RISK_AND_LEVERAGE.md`、`docs/05_EXCHANGE_DATA.md`、`docs/06_DATABASE_AND_API.md`、`docs/08_ACCEPTANCE.md`和`codex/AGENTS.md`。历史V1.0/V1.1/V1.2档放在archive，仅用于追溯，新风险规范优先。

要求先输出理解摘要、风险与接口资格阻塞项、P0计划；然后仅实施`codex/01_PHASE_0_PROMPT.md`规定的P0。所有新增代码要可运行、有类型、可测试；每阶段交付README命令与真实测试结果。不得模拟“请求成功”当真实API可用；不得使用未验证的Binance产品符号下单，不得向账户发送真实交易请求。

严格保持`LIVE_TRADING_ENABLED=false`和模拟订单适配。人审开仓、50%初始本金损失容忍、10—20x通常交易所杠杆/25x上限、42轮原决策必须保存。其他微资金风控阈值全部标为RESEARCH_ONLY。不要假定2x账户整体有效杠杆已由用户批准。要区分股票标的/传统商品与Binance对应永续合约。

如P0受网络、地区、API文档变更、目标合约不可用等限制，**把无法证实的地方显示为UNKNOWN并给出测试证据**，能做的继续做；不要跳过第0阶段伪造接口数据。P0验收完后等用户批准进入P1。
