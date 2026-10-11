# P0 数据质量报告

生成时间（UTC）：2026-10-10T12:21:51.839803Z
运行 ID：fcb410a6-cec4-4f81-9716-e0ce793ad598；能力状态：{'VERIFIED_PUBLIC': 9}

公共可见性不能证明账户或地区权限。当前工程无下单接口，LIVE=false。

| 符号 | 最近 REST 闭合 bar | 未收盘样本 | 缺口段数 | 质量 |
|---|---:|---:|---:|---|
| NVDAUSDT | 59 | 1 | 0 | VALID |
| TSLAUSDT | 60 | 0 | 0 | VALID |
| METAUSDT | 60 | 0 | 0 | VALID |
| GOOGLUSDT | 59 | 1 | 0 | UNAVAILABLE |
| CLUSDT | 59 | 2 | 0 | VALID |
| NATGASUSDT | 59 | 2 | 0 | VALID |
| BZUSDT | 59 | 1 | 0 | VALID |
| XAUUSDT | 59 | 2 | 0 | VALID |
| XAGUSDT | 59 | 1 | 0 | VALID |

金额使用 Decimal；Parquet 数值列保存精确十进制字符串，时间列为 UTC。
REST 无事件时间字段，exchange_event_at=null；闭合判断依据请求前服务器时间。
未收盘样本仅在 data/open；闭合档案在 data/closed，按源去重，冲突拒绝覆盖。
当前为小样本探测，不能证明持续行情稳定性、完整长期历史或策略有效性。
缺口仅为观测；时段归属、非传统资产时段定价、合约乘数尚未确认。
history_start_at 是 startTime=0 查询返回的首个时间，不承诺数据完整覆盖。

## 未完成的账户核验

9 个品种的账户交易资格、最大杠杆、逐仓、保护单/reduceOnly、费率均 UNVERIFIED。
P0 不使用凭证；待 P4 通过授权只读核验。保持本金损失容忍 50%、常规 10–20x、
单仓最高 25x 的设计要求；其余微资金阈值仍是研究/模拟候选。

## 异常记录

- NVDAUSDT：Public specification only. Account/region/leverage/margin/order semantics unverified.; Ignored requiredMarginPercent/maintMarginPercent: not leverage permission evidence.; UNAVAILABLE: TimeoutError: 
- TSLAUSDT：Public specification only. Account/region/leverage/margin/order semantics unverified.; Ignored requiredMarginPercent/maintMarginPercent: not leverage permission evidence.
- METAUSDT：Public specification only. Account/region/leverage/margin/order semantics unverified.; Ignored requiredMarginPercent/maintMarginPercent: not leverage permission evidence.; UNAVAILABLE: TimeoutError: 
- GOOGLUSDT：Public specification only. Account/region/leverage/margin/order semantics unverified.; Ignored requiredMarginPercent/maintMarginPercent: not leverage permission evidence.; UNAVAILABLE: TimeoutError: ; Archive rejected: conflicting closed bar; requires reviewed revision
- CLUSDT：Public specification only. Account/region/leverage/margin/order semantics unverified.; Ignored requiredMarginPercent/maintMarginPercent: not leverage permission evidence.
- NATGASUSDT：Public specification only. Account/region/leverage/margin/order semantics unverified.; Ignored requiredMarginPercent/maintMarginPercent: not leverage permission evidence.
- BZUSDT：Public specification only. Account/region/leverage/margin/order semantics unverified.; Ignored requiredMarginPercent/maintMarginPercent: not leverage permission evidence.; UNAVAILABLE: TimeoutError: 
- XAUUSDT：Public specification only. Account/region/leverage/margin/order semantics unverified.; Ignored requiredMarginPercent/maintMarginPercent: not leverage permission evidence.
- XAGUSDT：Public specification only. Account/region/leverage/margin/order semantics unverified.; Ignored requiredMarginPercent/maintMarginPercent: not leverage permission evidence.; UNAVAILABLE: TimeoutError: 
