# 给 Codex 的首轮开发任务（直接复制使用）

你是资深Python量化系统架构师、TypeScript全栈工程师和交易风控工程师。请按照随附的 `Quant_System_V1_1_Blueprint.md` 和 `Quant_System_V1_1_MicroCapital_Risk_Addendum.md` 开始 Quant System V1.0 开发。 **不要一次生成完整实盘交易软件。** 先完成“第0阶段：交易品种/API只读可行性核验”与“第1阶段基础工程骨架”的最小可验证成果。

## 不可更改的约束
1. 前后端采用Python/FastAPI + TypeScript/React；Mac研究、云端运行；PostgreSQL + Parquet/DuckDB + Redis分层存储。
2. 以Binance为平台，研究对象是美股相关、能源、贵金属；实际可执行品种必须逐一通过账户地区、产品权限及官方接口规则核验。不得把永续合约等同真实股票/传统期货。
3. 采用半自动交易，**默认禁用真实交易**：`LIVE_TRADING_ENABLED=false`；未收到后续明确授权，不编写会从示例环境或测试脚本中自动提交真实订单的流程。
4. 实现双模式风控：`standard`维持原42轮阈值；`micro_capital`记录用户确认的本金500–1000元与50%最大可承受初始本金损失，其他微资金阈值按修订提案仅进行研究/模拟。新增本金损失、最高净值回撤、日内3%/5%、单笔1%/2%、账户杠杆/保证金及最小下单额拒绝交易的纯函数测试。未经批准不得实盘。
5. 所有密钥、凭证使用环境变量或受控secrets，绝不写入仓库、日志或浏览器存储；公开行情优先使用只读接口。需要认证API时，先设计模拟实现并记录所需权限。
6. 研究标的、交易合约、市场交易时段和价格指数模式必须分离建模，数据时间使用UTC+来源可用时间，禁止未来函数。
7. 初版采用模块化单体+独立Worker，不引入复杂分布式微服务。

## 本次要交付
- [ ] 初始化monorepo：`backend/`、`frontend/`、`docs/`、`config/`、`tests/`，锁定依赖版本，提供README中文使用说明。
- [ ] 基于架构文档实现 Pydantic `Instrument`、`MarketBar`、`EventRecord`、`MarketContext`、`CandidateSignal`、`RiskSnapshot` 模型。
- [ ] Binance **只读**适配器：接口限流/超时/断线重连/重试保护；读取交易所合约规则（如`GET /fapi/v1/exchangeInfo`）、历史K线、交易时段（如`GET /fapi/v1/tradingSchedule`）；每个接口先与当期官方文档核对。
- [ ] `instrument_capability_report`：对于目标合约（NVDAUSDT、CLUSDT、NATGASUSDT、XAUUSDT、XAGUSDT等）报告在当前公共接口上“已验证/不可用/需要身份权限核验”，不能把HTTP失败解释为一定下架。
- [ ] 行情规范化管线：保存raw payload hash、exchange/received/processed timestamps，1m K线、闭合标记、去重、缺口检查，导出Parquet。
- [ ] 基础研究后端与最简可运行Web页：显示数据源状态和合约可用性，不需要先做漂亮仪表盘。
- [ ] Unit tests：量化金额使用Decimal、bar未收盘不触发信号、重复事件幂等、缺失数据标记UNAVAILABLE、时区与DST测试。
- [ ] Docker Compose：本地PostgreSQL、Redis、API；Mac开发说明；`.env.example`不得含任何密钥。
- [ ] 给出README里的可运行命令、测试命令、已验证功能、不可用功能、下一阶段待办。

## 工作方式
请先读取蓝图，列出技术风险和未确认点；生成架构决策记录（ADR），然后逐文件实现。每完成一个小里程碑运行测试并汇报结果。不能从文档推断个人账户已开通API，也不要要求我直接提供API密钥到聊天窗口。任何未决参数都使用安全配置并标注TODO，需要真实交易授权时停止推进该步骤。

**本次完成定义**：能够本地启动API和前端、运行只读合约清单与K线采集测试、成功写入带时间戳的Parquet、测试全部通过、真实下单模块始终关闭。


## V1.1本轮开发新增任务（只有模拟与只读验证）
- [ ] 设计 `RiskProfile` 配置管理：标准/微资金参数不能混用；默认交易权限始终关闭。
- [ ] 建立 `principal_0`、外部资金流调整后的权益、初始本金损失、高水位回撤四套可审计计算口径。
- [ ] 实现最小订单、价格/数量精度检查及手续费/资金费/滑点预算；无法满足单笔风险时拒单，严禁向上凑单。
- [ ] 风控单元测试：20%预警、30%减额、40%停机、50%最终预算；充值/重启无法解除；峰值盈利后亏损独立测试。
- [ ] 演示：账户1000人民币，若普通交易拟亏损超过10元，必须调整数量或拒单；真实币安合约规则尚未核验时绝不提交订单。
