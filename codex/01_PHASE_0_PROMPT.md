# P0：只读可行性核验任务

## 目标
在不持有任何交易密钥、不提交任何订单的前提下，确认Binance官方当前API对目标股票相关/能源/贵金属合约的公开可见性、规格、历史K线、数据时效、可能交易时段及衍生品产品族。

## 工作项
1. 初始化monorepo建议目录：`backend/app`, `frontend`, `config`, `docs`, `reports`, `tests`；产生`pyproject.toml`、`.env.example`、`README.md`、基础CI。依赖锁定且可安装。
2. 编写单一只读HTTP客户端，具有限速、超时、退避、请求审计、响应hash和产品族显式参数，禁止任何POST交易接口。
3. 根据官方文档而不是硬编码传说，对`config/instruments.example.yaml`的候选合约逐个查询`exchangeInfo`、K线及WS（仅有条件时），记录`capability_state`和证据。
4. 无权限/不可用/断线时返回UNKNOWN或UNAVAILABLE，并留下原始错误/时间；不能把结果虚构为成功或证明该符号下架。
5. 规范1m bar为Pydantic模型，记录`is_closed`, `exchange_event_at`, `received_at`, `processed_at`, `source`, `raw_hash`，闭合bar保存Parquet；把未收盘bar明确隔离。
6. 增加instrument vs underlying两层模型；数据缺口与可能非标准交易时段的模式支持版本化字段。
7. 生成`reports/instrument_capabilities.json`、CSV、`reports/data_quality_report.md`。
8. 离线单测覆盖去重、closed-bar、UTC/DST、响应不完整、429/5xx和能力状态，能稳定重复运行；可选联网集成测试不得作为默认必通过条件。
9. 建立最简FastAPI只读`/health/live`、`/health/ready`和`/api/v1/instruments`；前端可只显示合约能力表（不要先堆华丽图表）。

## 必要验证
- 运行pytest和frontend最小构建，输出真实命令与结果。
- `LIVE_TRADING_ENABLED`严格false，报告当前工程没有任何实盘下单路径。
- 无法证实的产品列表清楚写出阻塞原因。

## 禁止事项
严禁创建可从.env配置直接触发实盘订单的示例；严禁要求用户提供私钥给聊天；严禁因文档存在symbol例子就把账户权限标YES。
