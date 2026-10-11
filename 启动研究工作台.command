#!/bin/zsh
set -eu
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  print '缺少 Python 虚拟环境，请按 README 安装依赖。'
  read 'reply?按回车退出'
  exit 1
fi
export PYTHONPATH="$PWD/backend"
print '启动 PostgreSQL、研究 API 与行情工作台；不会执行真实订单。'
if ! .venv/bin/python -m app.local_workspace; then
  print '启动失败。请保留以上报错信息。'
  read 'reply?按回车退出'
  exit 1
fi
