# Quant System — Codex 开发交接包（2026-10-10）

**交付目的**：将用户42轮确定的需求、V1.1微资金决策、V1.2杠杆决策，转为Codex可逐阶段执行、可测试、不会擅自开启实盘交易的工程输入。此目录是**规格与参考测试资料**，**不是已开发完成的交易程序**。

## 先读什么
1. `00_START_HERE.md`：最终准则、哪些确定/未确定、启动方法。
2. `docs/01_DECISIONS_42.md`：42轮原始决定及V1.1/V1.2变更。
3. `docs/02_ARCHITECTURE.md`：模块、数据流和进程边界。
4. `docs/04_RISK_AND_LEVERAGE.md`：风险数学、50%实验损失预算、10–20x/25x与强平检查。
5. `docs/05_EXCHANGE_DATA.md`：Binance接口能力核验，不要猜测产品/API可用。
6. `docs/08_ACCEPTANCE.md`：测试与验收。
7. `codex/AGENTS.md` 与 `codex/00_MASTER_PROMPT.md`：交给Codex的指令。

## 如何交给Codex
将本目录放到项目仓库根目录（或把ZIP解压为工作目录），在Codex中先让它读取`00_START_HERE.md`及`codex/AGENTS.md`，再粘贴`codex/01_PHASE_0_PROMPT.md`。完成阶段0并查看能力核验报告后，再运行后续阶段任务。**不要要求它一次性生成六阶段并开启真实交易。**

## 事实层级与规范优先级
`00_START_HERE.md` > `docs/04_RISK_AND_LEVERAGE.md`及`config/settings.example.yaml` > 本包其余有效文档 > `archive/original_files/`历史版文件。
所有新增或待验证参数必须写入决定日志，不能把建议参数写成用户已批准参数。`LIVE_TRADING_ENABLED=false`不可由工具或模型自行改为true。

## 内容目录
- `docs/`：需求、架构、策略、风险、交易所、数据模型、API、UI、验收、路线图、盈利模型、开放决策与资料源。
- `config/`：机器可读的演示/模拟参数，状态字段标识是否已批准。
- `contracts/`：信号/交易计划/合约能力报告 JSON Schema。
- `reference/`：纯标准库Decimal风险数学示例与离线测试，供Codex实现时对照；不是生产风控。
- `codex/`：代码代理工作规范、启动提示词及各阶段任务。
- `templates/`：能力报告、决策记录和交易模型示例。
- `archive/original_files/`：此前V1、V1.1、V1.2的原始文件，提供历史追溯，**不可覆盖新版本配置**。

## 当前状态
未开发；未验证Binance个人账户资格；未接入交易密钥；未证实目标TradFi合约通过某一特定API可交易；未完成数据许可、回测、模拟/实盘准入测试。默认只读和模拟。
