# P2 首批公共实时研究功能 · 2026-10-12

状态：**首批功能已实现并真实试运行，完整 P2 未验收**。用户已授权 P2 开发；P1 PostgreSQL 与另外两套策略仍有未完成项。没有新增账户查询、密钥输入、订单、实盘执行或外部消息发送路径。

## 文件变更

- `backend/app/realtime_models.py`：关注池、事件、研究信号、分级通知契约。
- `realtime_engine.py`：经济分钟去重、闭合聚合、时效/缺口/冲突阻断、研究趋势状态、观察/确认/失效/过期。
- `realtime_worker.py`：独占进程锁、公共 WS、重连退避、REST 预热/补数、每 5 分钟重新核验规格、停止与失败处理。
- `realtime_store.py`：同步落盘哈希链、空间预算、确定性回放与决策检查点。
- `realtime_api.py`、`main.py`：本地启动/停止/状态与只读推送，关闭服务时清理 worker。
- `research_models.py`、`strategies.py`：抽取共用研究窗口，保留原有历史回测契约与假设。
- `public_client.py`：增加公共全市场 24h ticker GET，按 40 权重计费；订单请求继续被拒绝。
- `frontend/src/RealtimeDesk.tsx`、`realtimeTypes.ts`、`main.tsx`、`ContractSearch.tsx`、`style.css`、`vite.config.ts`：实时监控页面、共享中文搜索、关注/发现池、启停、质量、研究候选与本机通知；已有行情/历史/风险页面保留。
- `tests/test_realtime.py`：20 项新增离线测试。

## 运行方法

已有本机 API 和前端服务正在运行，打开 http://127.0.0.1:5173/#realtime 。搜索代码或中文名称，添加最多 4 个关注合约，可选择 5m / 15m 研究周期，点击「启动实时采集」。默认发现池关闭；打开后额外选取启动时 USDT 滚动 24 小时成交额前 2 名，同一会话不自动换池。修改设置先停止采集。

重新运行时，在工程根目录和 frontend 目录分别启动：

```sh
PYTHONPATH=backend LIVE_TRADING_ENABLED=false APPROVAL_MODE=HUMAN TRADE_ADAPTER=PAPER_BROKER .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```sh
cd frontend
pnpm dev
```

服务重启默认 STOPPED，不会恢复旧会话的健康状态或自动开新连接。停止后数据保留但显示已停止；研究候选失效。关闭页面不会停止后台采集，需使用「停止采集」或关闭后端。

## 实际测试证据

- 全部离线后端测试 **187 passed**；2 个 PostgreSQL 集成测试、1 个可选联网测试被显式排除。现有 Starlette/httpx 弃用提示 1 条。
- 新增 20 项覆盖：REST/WS 重复三次不重复计算成交量/候选、未闭合 K 线不确认、补数不补发信号、断线/延迟/冲突/规格变化阻断、重连必须有两条新鲜数据流、实际 TrendPullback 两阶段确认、候选过期、确认后失效、哈希链篡改拒绝、空间预算、进程互斥、本地 Origin/Host 与只读推送控制、模拟 worker 断线/补数/重连/停止。
- Ruff 通过，mypy **29 个源文件**通过；TypeScript/Vite 构建 **38 模块**通过；现有前端参数测试 **5 passed**。
- 真实试运行一：BTCUSDT / MUUSDT 公共 K 线、标记价均收到，逐品种 781 根闭合分钟、0 缺口；1689 个记录事件、5 个回放检查点一致，启停成功。
- 最终版本真实试运行二：MUUSDT 关注池，真实 ticker 排出的 BTCUSDT / ETHUSDT 发现池，逐品种 **784 根闭合分钟、0 缺口**。观察到 MUUSDT 与 ETHUSDT 多头研究候选，均 `executable=false`；没有等待后续闭合确认，停止时两者失效。**2743 个事件、10 个检查点**回放一致。摘要见 `p2_first_increment_validation.json`。
- 真实会话记录、公共 HTTP 原始响应与截图在本机 `.runtime/realtime/` 及工程上一级 `p2-evidence/`，不上传运行数据。完整回放可在工程根目录运行：

```sh
PYTHONPATH=backend .venv/bin/python -m app.realtime_store .runtime/realtime/64002a5e-9ec2-4dd2-bbab-2ed1b15b7ae8/events.jsonl
```

## 已完成与运行边界

只消费固定 Binance `/market/stream` 的 USD-M kline/markPrice 公共流，不发送业务 WS 消息；协议 ping/pong 由客户端库处理。首次公共规格核验限定 TRADING、已识别 USD-M 保证金币种和合约类型；显式 COIN-M `st=2` 事件阻断。**逐品种账户权限仍为 UNKNOWN**。当前首批仅支持 USDT/USDC 永续，搜索目录中其他产品不会隐式订阅；启动时会拒绝不满足条件的合约。

预热 780 分钟；REST 单页 99、公共加权预算 120/min。WS 未闭合/标记价按每品种每类最多 5 秒一条研究采样，闭合消息不丢采样。保留消费输入的实际收到/处理/可用时点与原始 WS 文本；每个经济分钟只计算一次，同一分钟 OHLCV 不同则冻结该品种。补数仅作为历史上下文，不会伪造历史信号。重连后清空旧连接的时效证据，补数完成仍必须等两条新鲜 WS 流。公共来源可用不等于账户、地区资格或交易就绪。

信号仅使用完整连续闭合 1h 和 5m/15m。默认研究窗口 6/12、回拉 6；初次满足条件进入 WATCHING，下一根完整低周期收盘延续方向才 CONFIRMED。候选最多观察 2 根；延迟/缺口/规格变化/停止可使观察或已确认信号失效。独立规则分 60 是既有研究规则分，不是概率或胜率。市场状态是 1h 均线的研究标签，不是已验证的完整生产 Regime 模型。

**`LIVE_TRADING_ENABLED=false`、`allow_new_risk=false`、`trading_ready=false` 始终保留**；50% 本金亏损容忍预算、常规单仓 10–20x、上限 25x 与所有待批准风险参数保持原状态。行情健康不提供交易许可。

## 遗留项 / 完整 P2 验收条件

1. PostgreSQL 本机初始化本次仍因 `shmget: Operation not permitted` 失败。文件哈希链仅研究暂存，不代替 PostgreSQL 交易事实库。数据库持久台账、事务通知 outbox、重启恢复与 Redis 分层未验收。
2. MeanReversion 尚未实现，EventDriven 无核验过的许可事件供应商。独立栏位返回 null 与原因，未虚构零分或供应商事件；完整三策略评分和成熟 Regime 优先级待开发。
3. 发现池仅启动时两级筛选（全市场成交额 → 逐品种规格与细数据），动态重排/换池、时段模型及 TradFi 更细能力规则待开发。时段缺口未分类，保守阻断。
4. 分级通知仅本机页面；外部通知渠道、可靠投递与重试待选择并实现。
5. 当前是分钟 K 线研究流，没有生产级逐笔/深度行情、跨品种水位调度和长期 24h 轮转实测。短时真实公共行情成功不代表持续稳定；断流与恢复已离线验证，尚未做云端长时前向验收。
6. 单会话 journal 上限 128 MiB，含 HTTP 审计的会话总量上限 256 MiB；磁盘不可写会停止并显示失败。多会话长期保留/备份策略待实现，不自动删除历史证据。

Binance 接入依据（本轮核对官方文档）：[USD-M 路由连接](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Connect)、[公共市场 WS](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/market)、[公共 REST 与权重](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)。
