# 官方资料入口与核验说明（截至2026-10-10）

- Binance Developer Docs 产品目录：https://developers.binance.com/en/docs/catalog
- Binance Derivatives API 入口：https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/Introduction
- USDⓈ-M REST行情目录：https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data
- USDⓈ-M REST交易目录（只阅读，勿在阶段0执行）：https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade
- USDⓈ-M WS市场流订阅：https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Live-Subscribing-Unsubscribing-to-streams
- USDⓈ-M用户流（需账户资格和认证，先mock）：https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-api/user-data-streams
- 现行账户/杠杆/产品公告与地区规定，以Binance官网当期产品页及账户自身权益为准；不得把其它市场产品相同字段定义直接搬来。

**重要审计提醒**：部分旧档示例链接、历史公告与合约符号可能更新。Codex必须在接入阶段记录文档页面核查日期、实际调用接口、HTTP状态、原始响应摘要和权限差异。外部网络不可达时记录`UNKNOWN`，而不是编造已验证成功。
