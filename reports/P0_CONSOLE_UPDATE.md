# P0 操作控制台补充交付

2026-10-10，北京时间 20:18 完成验证。针对原界面只有能力表、缺少操作入口的问题，在 P0 范围内补充本地操作控制台；没有进入 P1 或实现交易工作流。

## 已完成与使用方法

访问 **http://127.0.0.1:5173/#probe**。前后端已在本机启动，浏览器留在只读探测页面。

1. **运行总览**：查看公共能力样本计数、缓存时效、本机服务和最近任务。
2. **合约能力**：输入符号搜索；筛选 WS/公共规格待核验项；点击符号或「详情」打开原生弹窗，查看账户 UNKNOWN、请求来源、UTC 证据对应的北京时间和原始响应哈希。弹窗可关闭或按 Escape 退出。
3. **只读探测**：点击「运行只读探测」，启动固定公共采集程序。运行中按钮禁用，每 2 秒更新进度和日志，完成后自动读取新报告。「刷新报告」仅重读已有快照，不发起新采集。
4. **数据与报告**：查看真实闭合/未闭合样本、累计归档和缺口统计；下载 JSON、CSV、Markdown 报告。
5. **安全与阶段**：查看 LIVE=false、HUMAN、PAPER_BROKER、后续未实现功能、已确认设计与待批准候选边界。

重启与 CLI 采集方法见 README。两个开发服务均只绑定 127.0.0.1，未配置开机启动、持续后台采集或云端部署。窄窗口中导航分行显示，表格支持横向滚动；符号本身也是可见的详情入口。

## 文件变更

- 新增 `backend/app/probe_jobs.py`：固定命令任务、180 秒超时、60 秒启动间隔、跨进程文件锁、持久任务状态与最多 16 KB 日志尾部。状态为 IDLE/RUNNING/SUCCEEDED/FAILED，进程成功不升级账户权限。
- 修改 `backend/app/main.py`：任务状态/启动、经类型校验的质量摘要、固定白名单报告下载。启动仅接受本机可信 Origin、正确 Host、空 JSON 请求；禁止任意命令、URL、路径或交易参数。
- 修改 `backend/app/probe.py`：CLI 与控制台共用整个探测流程的独占锁。
- 修改 `frontend/src/main.tsx`、`style.css`、`vite.config.ts`；新增 `frontend/src/types.ts`：五页导航、实际操作按钮、筛选、弹窗、日志、下载与开发代理。
- 新增 `tests/test_console_jobs.py`（11 项离线用例）和 `contracts/phase0_probe_job.schema.json`、`contracts/phase0_quality_row.schema.json`；更新 README。
- 新增 `console_validation.json`、四份检查输出、界面截图、本报告；实际运行更新能力/质量报告、原始证据、版本化规格与 Parquet，并保留历史运行档案。

## 真实验证结果

| 验证 | 结果 |
|---|---|
| `pytest -m 'not network'` | **69 passed，1 network deselected** |
| `ruff check backend tests` | PASS |
| `mypy backend/app` | PASS，11 个源文件 |
| 前端 `pnpm build` | TypeScript + Vite PASS，28 modules |
| 五页导航 / 搜索 / 筛选 / 详情弹窗 | 浏览器实际操作通过；NVDA 搜索 1 行、WS 待核验筛选 4 行 |
| 页面启动真实探测 | 任务 `ede045d4-d8cb-407d-8c3e-3ec1ede209cb`，退出码 0，约 59 秒 |
| 服务重启后的任务状态 | SUCCEEDED 与完整日志保留 |
| HTTP 路由及拒绝行为 | 页面/状态/报告 200；交易 ready 503；不可信 Origin 403；额外命令参数 422；订单 404；修改能力报告 405 |
| 报告下载 | 4 个下载响应与源文件字节完全相同；CSV 从浏览器实际下载至 Downloads，SHA256 与源文件一致 |
| 并发/超时/中断/非法请求 | 离线故障注入通过，包括跨 Runner 与 CLI 锁、超时、不合法参数、来源/Host/客户端限制 |

真实报告 run_id：`dd660897-b5c2-49f3-8707-c86a8008e23d`，生成时间 **2026-10-10 20:09:42（北京时间）**。

- 9/9 公共规格和历史 K 线已观测。
- TSLAUSDT、METAUSDT、CLUSDT、XAUUSDT、XAGUSDT 收到有效 WS 帧；NVDAUSDT、GOOGLUSDT、NATGASUSDT、BZUSDT 本次窗口未取得有效帧，保留未知。
- 47 条审计 HTTP 请求全部为 Binance 公共 GET；69 个报告原始证据引用的 SHA256 校验一致。
- 账户权限、地区资格、账户最大杠杆、逐仓与订单语义仍未核验。

## 遗留与运行限制

`LIVE_TRADING_ENABLED=false` 保持不变，没有真实下单路径。微资金 50% 本金亏损容忍、常规单仓 10–20x、最高 25x 设计保留；其他风险阈值仍是未批准的研究/模拟候选。

控制台不是完整交易终端。回测、策略、账户认证、2FA、人审、纸面交易与真实执行继续按交接路线分阶段实现。探测为短窗口采样，不保证完整长期历史或持续 WS 可用性。

本地任务入口不具备云端认证与部署能力；不能直接作为公网服务部署。控制进程中断后，采集子进程可能继续运行，状态明确报告中断，采集锁防止重叠；重启后的失败状态不能被理解为交易所不支持。

PyArrow 产生 CPU 缓存 sysctl 沙箱警告，采集和 Parquet 写入仍成功；离线测试有一条 Starlette/httpx 弃用警告。以上原始日志保留，没有将警告或超时伪装成成功能力。
