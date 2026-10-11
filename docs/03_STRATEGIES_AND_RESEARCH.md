# 三套量化策略、评分与研究方法

## 核心哲学
平台盈利**仅在长期扣成本后正向期望成立时才可能产生**；高胜率、漂亮回测、高评分都不构成有利可图的证据。交易三策略独立，市场状态只分配优先级与允许暂停，冲突不强制抵消。

## 通用输入输出
`MarketContext`: 时间点、symbol/instrument_spec_version、收盘确认的OHLCV (1m/5m/15m/1h/1d)、原始成交量、价格结构、历史特征、市场状态、标记/指数/资金费率/价差、事件available_at、数据质量。
`CandidateSignal`: `strategy_id/version`, `instrument_id`, `direction`, `score [0,100]`, `feature_snapshot`, `explanation[]`, `discovery_at`, `confirmation_rule`, `expiry_at`, `invalidation_rule`, `data_quality`。
评分只是排序/模型条件契合度；不得显示“87分=87%盈利概率”。

## 策略A：Trend Pullback（趋势回调）
研究结构：1D/1H识别趋势及局部高低点 → 5m/15m判定回撤位置与结构 → 已闭合K线/可验证价格事件确认原趋势恢复 → 结构止损/波动率校准 → 交易计划。
研究特征候选：EMA/MA斜率、价格相对均线、最近结构高低点、回调深度（ATR或前波段比例）、MACD等辅助。避免重复指标增加虚假共识。
**未定**：具体窗口/趋势判别、合法回调范围、确认条件、评分权重、隔夜规则。程序初期生成指标及观察信号，不擅自把样例值当交易参数。

## 策略B：Mean Reversion（均值回归）
研究结构：在稳定或震荡市场估计条件统计分布（可用Z-score等）→ 评估离群程度与波动机制 → 在价格行为确认时建立候选 → 目标均值附近部分退出+移动止损框架。
严格避免：任意“跌够多就买”、在结构性跳变后使用过期均值、不检验分布稳定性。
**未定**：滚动窗口、分布稳定性检验、Z-score阈值、反转确认定义、事件期间暂停规则。

## 策略C：Event Driven（事件驱动）
覆盖：美股财报、CPI、FOMC、EIA库存及重大公告。事件必须记录`event_type/source/original_published_at/first_available_at/revision_id/source_license`；价格响应依赖实际可得行情。事件没有可靠授权数据源时，仅保留界面预告/禁止自动可执行信号。
重要：时点对齐要考虑新闻供应商延迟/数据修订；非股票时段传统资产指数价格形成模式可能不同。
**未定**：事件供应商、预期值/实际值字段、惊喜阈值、波动过滤、事件后信号有效期。

## Regime识别
分类 `TREND / RANGE / EVENT_SHOCK / UNKNOWN`。状态算法只用当前历史可用特征，可以返回`UNKNOWN`及不交易；不可强制把矛盾信号合并成一个方向。

## 信号生命周期
`DISCOVERED → WATCHING → CONFIRMED → RISK_CHECKED → AWAITING_APPROVAL → APPROVED → SENT → PARTIAL|FILLED|REJECTED|CANCELLED`；旁支`EXPIRED/INVALIDATED/CONFLICTED/BLOCKED_BY_RISK/UNKNOWN_ORDER_STATUS`。所有转移有审计时间/原因，确认价格发生有意义变化必须重审风控并废弃旧批准。

## 止损、止盈、退出
- 初始保护：结构失效点+经ATR等校正的噪声缓冲；止损理论风险包含手续费/滑点，强平优先于止损的场景拒单。
- V1统一退出：分批止盈 + trailing stop；`2R/50%`仅测试范例，非确认值。
- 逻辑衰减时间退出：观察价格推进、动量/结构变化、事件影响；固定隔夜/合约时段规则仍是独立安全条件。
- 风控单自动减仓/保护性平仓可在**预先审批原交易管理计划**范围内按交易所能力执行；不得把自动开新方向仓位伪装成止损。

## 研究验证管线
1. 数据清洗、去重、时间对齐、版本快照、是否包含已退市历史标的的样本检查。
2. Train/Validation/Holdout严格时间划分；walk-forward在历史每个时点重新估计，只对未来窗口测量。
3. 按合约真实fee/funding/index/交易时段、滑点、订单限制、partial fills进行成交模拟；缺少关键真实成本时标注不具备正式有效性。
4. 绩效：扣成本净收益、单笔期望、盈亏比、win rate、profit factor、交易量、max drawdown、风险暴露、坏场景测试、regime分层表现。
5. 不重复使用最终holdout调参；统计不确定性及与简单基准比较，避免数据挖掘偏差。
6. 每周参数研究并生成候选版本、代码hash、参数hash、数据hash、结果与差异；人审后才可部署。

## 入场分数阈值与权重的批准流程
阶段1可以用“研究基线配置”（显式status=RESEARCH_ONLY）做回测与评分可视化，**不能从示例权重/阈值自动解锁实盘**。回测筛选出的参数也需要冻结、样本外验证、风险审批与书面批准记录。
