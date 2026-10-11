# Binance 合约适配、数据规范与第0阶段核验

## 不可混淆的产品
原始投资方向：美股、能源期货、贵金属期货。实际交易平台最终指定Binance，开发应把**标的underlying**与**交易合约instrument**分开：美股相关永续 ≠ 股票所有权；传统商品相关永续 ≠ 交易所传统到期期货。不要混用同名品种的K线、分红、交易时段、结算或保证金逻辑。

## 目标研究名单（仅作为探测，非可交易性保证）
- 股票价格相关候选：NVDAUSDT、TSLAUSDT、GOOGLUSDT、METAUSDT（能否返回/开放以实时能力报告为准）。
- 能源候选：CLUSDT、BZUSDT、NATGASUSDT。
- 贵金属候选：XAUUSDT、XAGUSDT。
- 标的名称、是否币安某产品线、listing date、价格指数类型、实际交易许可均为`UNVERIFIED`直到公共API和账户权限核验。

## 不应预先假定的权限
地区适用性、开户资格、TradFi产品权利、测试网覆盖、是否所有API可用于某合约、最大杠杆、逐仓/全仓、单向/双向持仓、保护止损条件单支持、reduceOnly语义，都必须先查当期官方规格且对真实账户只读核验。HTTP403/404不能直接解释为“合约已下架”，可能是权限/地理/接口差异。

## 参考官方接口（仅作为候选，开发时再核对）
- 官方产品API目录：https://developers.binance.com/en/docs/catalog
- USDⓈ-M产品文档：https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/Introduction
- USDⓈ-M行情合约清单：`GET https://fapi.binance.com/fapi/v1/exchangeInfo`（按现行文档复核）
- USDⓈ-M历史K线：`GET /fapi/v1/klines`，需核查周期与单次条数；币安WS市场流配合收盘标志处理。
- USDⓈ-M资金费率/标记价格：需确认`/fapi/v1/fundingRate`等具体接口当前可用，取样快照入库。
- USDⓈ-M订单、账户及用户流：当前阶段**仅阅读官方文档并通过Mock编写适配器，不用真实交易凭证测试提交。**
- 切勿将Spot `/api/v3/`、COIN-M `/dapi/v1/`、Stocks Trading产品`/equity/`与USDⓈ-M `/fapi/v1/`直接视为同一个接口族。
- 非标准商品/股票交易时段的指数价格机制会影响回测；必须采集并版本化产品当期规则。

## P0能力报告字段
`venue,product_family,symbol,underlying,public_exchangeinfo_visible,trading_status,first_verified_at,verified_at,max_exchange_leverage_public,max_exchange_leverage_account,isolated_supported,stop_type_supported,mark_price_available,funding_data_available,history_start_at,websocket_works,account_permission,eligibility,notes,documentation_url,raw_payload_hash,capability_state`。
状态只能取：`VERIFIED_PUBLIC`, `VERIFIED_ACCOUNT`, `NEEDS_AUTHORIZED_CHECK`, `UNAVAILABLE`, `UNKNOWN`。公开可见不等于账户可交易。

## 数据落库约束
- 1m原始闭合bar为主，5m/15m/1h/1d只聚合闭合bar；区分exchange event time、received、available、processed time。
- `market_bars`: instrument_id, timeframe, open_time_utc, close_time_utc, OHLCV字符串/Decimal, is_closed, provider, quality, session_type, raw_hash, spec_version。
- 质量检查：OHLC合理性、精度、重复消息去重、闭合bar缺口、跨源差异、异常时间戳/时钟漂移、标记价与指数价差异、资金费率可用性。
- 不能用已修订的未来CPI/财报结果伪装事件公布时数据；历史事件表必须保留first_available_at和revision。
- 实盘报价陈旧、WS断线、合约暂停、规格更新=>禁止相关新增风险，进行订单状态/权益对账。
- 网络重试尊重429和官方权重限制，退避/限速；不要把网络超时自动重试写操作。

## 第0阶段交付
`reports/instrument_capabilities.json`和CSV，逐候选符号说明已验证事实、接口、时间、不可用的具体原因；小样本1m闭合K线Parquet；数据质量/缺口报告；合约规则版本快照；P1可接入候选列表。若所有目标合约不可用，明确阻塞并停在模拟/研究，不能编造替代币种交易。
