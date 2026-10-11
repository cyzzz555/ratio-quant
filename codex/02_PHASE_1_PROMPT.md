# P1：数据 + 策略研究 + 回测基座（须在P0验收后）

先阅读P0真实合约能力报告。对确有可靠数据的一个或多个合约建立研究基座：PostgreSQL/Alembic数据库表、带hash的Parquet数据目录和DuckDB查询、closed-bar多周期聚合、事件的available_at时点接入、统一MarketContext/CandidateSignal模型与策略插件接口。

先实现TrendPullback基准研究策略与可复现回测，再给MeanReversion/EventDriven提供接口及研究测试样本。所有未经数据证明的指标窗口/触发阈值标RESEARCH_ONLY，不进入真实下单。回测必须有交易成本、资金费率模型与滑点压力情景，分离训练/验证/holdout，生成可复查run id、参数hash、数据hash和绩效报告。

实现`risk`纯函数库，按`docs/04_RISK_AND_LEVERAGE.md`计算标准账户和微资金：单笔风险预算、数量向下舍入、有效杠杆、保证金、初始本金亏损/最高权益回撤的不同口径与无成交则不重下单的模拟审批框架。使用包内`reference/risk_math.py`和测试做数学回归对照，不把参考代码直接当作生产风控。

实现测试用例`docs/08_ACCEPTANCE.md`中P1适用部分。输出开放问题、缺数据和真实测试报告。不连接真实账户交易服务，`LIVE_TRADING_ENABLED=false`。
