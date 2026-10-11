# Mac 本地试运行

2026-10-10 13:40（北京时间）完成 P0 只读试运行，控制台已在 Mac 的 Codex 浏览器中打开。没有进入 P1，没有启用真实交易。

## 访问

- 控制台：http://127.0.0.1:5173/
- FastAPI 文档：http://127.0.0.1:8000/docs
- 服务存活：http://127.0.0.1:8000/health/live

现有前后端开发进程继续运行。未配置开机启动或定时采集；报告是一次探测的快照。重启、重新采集的标准命令见工程 README。

本次探测使用工程目录执行：

```sh
PYTHONPATH=backend .venv/bin/python -m app.probe
```

## 真实结果

- 探测进程退出码 0；run_id：`c798184b-4f79-4989-8db4-31f6306010b0`。
- 9/9 候选合约公共规格与历史 K 线已观测。
- WebSocket：NVDAUSDT、XAUUSDT 收到有效帧；其余 7 个在本次短采样窗口内没有有效帧，状态仍为未知，不能据此断言交易所不支持。
- 前端页面、后端存活、合约 API、前端代理合约 API 均返回 HTTP 200。
- `/health/ready` 返回 HTTP 503，`service_ready=true`、`trading_ready=false`、`allow_new_risk=false`；这是 P0 的预期交易就绪禁用行为。
- 合约 API 的 POST 返回 405；订单路径 POST 返回 404。
- 页面显示全部 9 行、最新证据时间和 `LIVE=false`；证据说明可展开。
- 没有修改代码，本次未重复运行上一阶段已通过的单元测试。
- PyArrow 输出 CPU 缓存 sysctl 查询受沙箱限制的警告；采集与 Parquet 写入完成，探测退出正常。

## 文件变更与遗留

更新 `reports/instrument_capabilities.json`、CSV、数据质量报告、规格/时段证据、探测原始记录与 Parquet 数据；保留历史运行档案。新增 `mac_trial_results.json`、`mac_trial_screenshot.png` 和本报告。原交付 ZIP 保持为上一阶段的发布快照。

账户权限、地区适用性、账户最大杠杆和订单语义仍未核验。`LIVE_TRADING_ENABLED=false`、`HUMAN`、`PAPER_BROKER` 保持不变；本阶段没有真实订单执行适配器。
