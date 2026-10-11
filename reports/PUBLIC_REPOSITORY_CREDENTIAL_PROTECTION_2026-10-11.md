# 公开仓库与凭据上传保护 · 2026-10-11

## 已核验状态

- 仓库：`cyzzz555/ratio-quant`，默认分支 `main`，GitHub API 返回 `visibility=public`；本次无需更改可见性。
- GitHub `secret_scanning`、`secret_scanning_push_protection` 均为 `enabled`。
- GitHub 未处理的密钥告警数：0。此结果只代表服务所支持的检测模式，不能证明不存在未知格式密钥。
- 原有全部可达 Git 历史：470 个不同的文件版本/路径组合完成离线扫描，无凭据发现。
- 当前 Mac 的 `core.hooksPath=.githooks`，两个钩子具备执行权限。
- API 和前端仍监听 `127.0.0.1`；本次不部署公网应用，不接入账户密钥。
- `LIVE_TRADING_ENABLED=false`、`HUMAN`、`PAPER_BROKER` 和既有风险参数保持不变。

## 文件变更

| 文件 | 行为 |
| --- | --- |
| `.gitignore` | 排除真实环境文件、凭据目录、GitHub CLI 认证文件、私钥及常见凭据副本 |
| `backend/app/git_secret_guard.py` | 直接扫描暂存 Git blobs 或所有可达提交；检测凭据路径、API/币安字段、服务令牌、私钥、连接密码和疑似 64 字符令牌；只输出位置/规则，出错阻断 |
| `.githooks/pre-commit` | 提交前扫描实际暂存内容，工作副本已清除密钥也不会误判暂存区安全 |
| `.githooks/pre-push` | 推送前扫描完整可达历史，覆盖非当前分支和旧提交中已删除的密钥 |
| `.github/workflows/credential-guard.yml` | 只读权限，拉取完整历史，在 GitHub 再执行检查，不注入或打印账户凭据 |
| `tests/test_git_secret_guard.py` | 使用合成数据和一次性本地 Git 仓库验证检测、钩子、历史、输出脱敏和失败阻断 |
| `README.md` | 公开源码、克隆后启用钩子的方法、密钥存放和检测边界 |
| 本报告 | 记录真实验证结果和已知边界 |

## 真实验证

运行目录为工程根目录，使用既有虚拟环境：

```bash
.venv/bin/python backend/app/git_secret_guard.py --staged
.venv/bin/python backend/app/git_secret_guard.py --history
.venv/bin/ruff check backend/app tests migrations
.venv/bin/mypy backend/app
.venv/bin/pytest -m 'not network and not postgres' -q
```

- 全量离线测试：**166 passed，3 deselected，1 warning，7.14 秒**。
- 其中新增凭据保护测试 29 项；真实 pre-commit 拒绝强制暂存的 `.env`，未产生提交；真实 pre-push 拒绝含旧密钥的历史，一次性远程仓库未收到分支。
- 暂存区中含合成密钥、工作副本已清除：仍被阻断；输出不包含合成密钥原文。
- 非当前分支中的合成密钥仍被历史扫描检出；中文/含换行文件名正确处理，符号链接目标文件不会被读取。
- 2 MB 文件末尾的合成密钥被检出；大文件测试暴露的 URL 正则扫描性能问题已修复后重新运行全量测试。
- 原公共接口拒绝测试中的固定 `forbidden` 哨兵不是真实凭据，仅对该测试文件的该固定值作窄范围处理；其它值/规则仍扫描，有专门测试。
- Ruff 全部通过；mypy 检查 24 个源文件通过。
- 1 条警告为既有 Starlette/httpx 弃用提示。前端源码未变更，本轮未重复前端构建。
- GitHub 工作流的最终运行结果以该提交对应的 Actions 页面为准。

## 边界与后续

- `.gitignore` 不能清除已跟踪文件；本次额外扫描了历史和暂存区，没有发现需要移除的真实凭据。
- 本机钩子负责上传前拦截；云端工作流在上传后执行，不能替代本机检查。GitHub 推送保护仅覆盖其支持的模式。
- 本地启用的 Git 配置不会随克隆自动安装；新机器需按 README 启用钩子，不要跳过检查或强制添加凭据。
- 检测不能保证识别拆分、编码、图像或未知格式的秘密；真实密钥始终只放本机受控文件，不放在源码、报告、日志、截图或聊天中。
- 真实密钥如曾公开，先撤销/轮换，再处理历史；只删除最新文件无法消除泄漏。
- P1 PostgreSQL 集成验收和后续开发阶段不在本次范围内；保持此前未验收状态。
