# 数据库模型、后端API及订单生命周期

## 数据字典（PostgreSQL事务真相；行情归档Parquet）
| 表 | 关键字段及约束 | 职责 |
|---|---|---|
|underlyings|id,asset_class,symbol,exchange,tz|底层经济标的|
|instruments|id,underlying_id,venue,symbol,product_family,status,current_spec_version|可用合约映射|
|instrument_spec_versions|instrument_id,version,effective_at,filters JSON, leverage_tiers JSON, raw_hash|合约规则有时间效力，不覆盖旧规格|
|market_snapshots|id,instrument_id,event_at,received_at,mark,index,spread,funding,quality|交易时点核验|
|events|event_id,type,source,published_at,available_at,revision_id,payload_hash,license|事件数据point-in-time|
|strategy_versions|strategy_id,version,code_sha,parameter_sha,data_sha,approved_by,approved_at,release_state|不可篡改版本|
|research_runs|id,strategy_version,dataset_sha,split_manifest,metrics,code_sha,created_at|可复现研究|
|signals|id,strategy_version,instrument_id,side,score,stage,feature_json,explanation_json,expires_at,created_at|信号独立评分与状态|
|risk_profiles|id,type,config_sha,approval_state,approved_at|标准/微资金独立配置|
|risk_snapshots|id,account_id,equity,initial_capital,flow_adjustment,daily_baseline,hwm,all_risk_fields,lock_state,created_at|独立损失指标|
|risk_locks|account_id,scope,reason,created_at,cleared_by,cleared_at|DB持久锁，不因重启消失|
|approval_requests|id,signal_id,immutable_order_sha,nonce,expires_at,status,approved_by,approved_at|严格人审|
|orders|id,account_id,client_order_id UNIQUE,approval_id,exchange_id NULL,status,order_payload_sha,updated_at|订单幂等根|
|order_events|id,order_id,event_id UNIQUE,event_at,received_at,kind,payload_sha|append-only事件记录|
|fills|id,order_id,venue_fill_id UNIQUE,qty,price,commission,commission_asset,at|成交去重|
|positions|account_id,instrument_id,position_side,quantity,average_entry,mark,updated_at|和交易所对账|
|equity_ledger|id,account_id,kind,asset,amount,flow_class,at,exchange_ref|入金出金/盈亏/资金费|
|system_incidents|id,severity,state,trigger,opened_at,closed_at,correlation_id|故障轨迹|
|audit_logs|id,actor,action,before_sha,after_sha,at,request_id|安全审计|
|outbox_events|id,type,payload,created_at,published_at,attempts|事务一致性消息|

数值：PostgreSQL `NUMERIC`、Python `Decimal`；时间：`TIMESTAMPTZ` UTC；不可变事件主键/unique；JSON字段验证版本schema。索引：(instrument_id,timeframe,open_time)，(account_id,at)，(client_order_id)，(order_id,event_at)，(strategy_id,created_at)。启用迁移和备份/恢复演练。

## API v1（单人账户仍需鉴权）
| 方法路径 | 含义 | 安全约束 |
|---|---|---|
|GET /health/live|进程存活|不能把live当交易就绪|
|GET /health/ready|交易就绪、外部依赖、风控锁状态|失败明确原因|
|GET /api/v1/instruments|合约能力与版本|标识已验证/未知|
|GET /api/v1/market/bars|K线与质量标记|时间区间与权限|
|GET /api/v1/signals|候选/已确认信号|策略独立展示|
|GET /api/v1/risk/status|风控阈值、两种损失指标、锁|不会隐去锁|
|GET /api/v1/portfolio|权益、持仓、名义杠杆|显示数据时间|
|GET /api/v1/orders/{id}|订单及对账状态|未知状态不得标成功|
|GET /api/v1/research/runs|回测与样本外|包含成本和数据hash|
|GET /api/v1/incidents|异常与恢复|审计|
|POST /api/v1/signals/{id}/prepare-order|生成方案|交易前风控/模拟可用|
|POST /api/v1/approvals|绑定订单快照|expires/nonce/hash|
|POST /api/v1/approvals/{id}/approve|人工授权|2FA、原子CAS、幂等key|
|POST /api/v1/approvals/{id}/reject|人工拒绝|审计|
|POST /api/v1/orders/{id}/cancel|请求撤单|要回查是否已成交|
|POST /api/v1/risk/kill-switch|锁定新风险|需要额外权限与审计|
|POST /api/v1/risk/recovery|启动对账恢复|需要人工批准|
|POST /api/v1/research/runs|运行异步研究|不改线上策略|
|POST /api/v1/strategy-versions/{id}/approve|审批新策略|代码/参数/数据hash|
|WS /api/v1/stream|实时只读状态|认证和订阅限制|

## 订单工作流
1. 策略确认后产生`TradePlan`：包含entry范围、止损、退出策略、qty、杠杆、保证金、预测手续费/滑点/资金费、强平参考、风险、报价时间、spec_version。
2. 风控预审核通过产生`ApprovalRequest`，保存trade plan规范化JSON的SHA256、nonce、expires_at。
3. Mac或iPhone调用`approve`，2FA通过，数据库原子转换`PENDING->APPROVED`，重复调用返回同一结果。
4. 投递outbox；execution_worker读取后重新查报价/持仓/风控并校验所有不可变关键字段；若不符则取消旧审批。
5. 只有审批且允许live的部署才可走真实下单适配层；模拟阶段使用PaperBroker且不得拥有实际API交易权限。
6. 写`client_order_id`唯一记录；提交超时 => `UNKNOWN_SUBMISSION`，先查询原ID/成交/持仓并核对；不得盲目生成新order id。
7. 保留部分成交、取消请求竞态、止损被拒、退出后仓位残留等状态，风险系统根据真实仓位重算。

## 订单状态机建议
`PREPARED -> AWAITING_APPROVAL -> APPROVED -> SEND_PENDING -> ACKED -> PARTIALLY_FILLED -> FILLED`;
`SEND_PENDING -> UNKNOWN_SUBMISSION -> RECONCILING -> ACKED|REJECTED|MANUAL_REVIEW`;
`ACKED/PARTIALLY_FILLED -> CANCEL_REQUESTED -> CANCELLED|FILLED|RECONCILING`。
所有状态改变要有数据库事务、事件流水、幂等键。真实发单失败不能自动推断未成交。

## 安全
2FA+合理超时/设备管理；敏感操作再次确认；API密钥仅云端最小权限secret管理、IP白名单、**禁止提币权限**；不能把密钥写入前端、日志、示例或版本控制；HTTPS/WSS；依赖扫描、审计、备份、异常自动锁定。
