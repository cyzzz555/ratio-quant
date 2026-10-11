"""Launch the Mac research workspace; foreground ownership and explicit DB failures."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

from app.settings import ROOT


def frontend_runtime() -> tuple[str, dict[str, str]]:
    env = dict(os.environ)
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies"
    if (bundled / "node/bin/node").exists():
        env["PATH"] = str(bundled / "node/bin") + os.pathsep + env.get("PATH", "")
    pnpm = shutil.which("pnpm", path=env.get("PATH"))
    fallback = bundled / "bin/fallback/pnpm"
    if pnpm is None and fallback.exists():
        pnpm = str(fallback)
    if pnpm is None:
        raise RuntimeError("Node.js / pnpm 未安装；请按 README 安装前端依赖")
    return pnpm, env


def available(url: str) -> bool:
    try:
        response = httpx.get(url, timeout=1, trust_env=False)
        return response.status_code == 200
    except httpx.RequestError:
        return False


def main() -> None:
    from app.research_db import health
    from app.research_ledger import synchronize

    env = dict(os.environ, PYTHONPATH=str(ROOT / "backend"))
    children: list[subprocess.Popen[bytes]] = []
    try:
        from sqlalchemy import text

        from app.research_db import engine

        def connected() -> bool:
            try:
                with engine(ROOT).connect() as connection:
                    connection.execute(text("select 1"))
                return True
            except Exception:
                return False

        if not connected():
            if os.environ.get("DATABASE_URL"):
                raise RuntimeError("已配置的 PostgreSQL 无法连接；不自动切换数据库")
            subprocess.run(
                [sys.executable, "-m", "app.local_postgres", "init"], cwd=ROOT, env=env, check=True
            )
            process = subprocess.Popen(
                [sys.executable, "-m", "app.local_postgres", "serve"], cwd=ROOT, env=env
            )
            children.append(process)
            for _ in range(30):
                if connected():
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("PostgreSQL 未启动；请保留终端报错")
        subprocess.run(
            [str(ROOT / ".venv/bin/alembic"), "upgrade", "head"], cwd=ROOT, env=env, check=True
        )
        if not health(ROOT)["ready"]:
            raise RuntimeError("PostgreSQL 迁移未通过健康检查")
        print(json.dumps(synchronize(ROOT), ensure_ascii=False))
        if not available("http://127.0.0.1:8000/api/v1/research/status"):
            children.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "app.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "8000",
                    ],
                    cwd=ROOT,
                    env=env,
                )
            )
        if not available("http://127.0.0.1:5173"):
            pnpm, frontend_env = frontend_runtime()
            children.append(
                subprocess.Popen([pnpm, "dev"], cwd=ROOT / "frontend", env=frontend_env)
            )
        for _ in range(40):
            if available("http://127.0.0.1:5173") and available(
                "http://127.0.0.1:8000/api/v1/research/status"
            ):
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("本机服务未就绪；请检查端口与终端日志")
        subprocess.run(["open", "http://127.0.0.1:5173/#market"], check=True)
        print(
            "研究工作台已打开。LIVE=false。保持窗口打开，Ctrl+C 关闭本脚本启动的服务。", flush=True
        )
        while True:
            if any(c.poll() not in (None, 0) for c in children):
                raise RuntimeError("服务进程异常退出；请查看终端日志")
            time.sleep(1)
    except KeyboardInterrupt:
        print("停止本次启动的进程；历史与回测文件保留。")
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()


if __name__ == "__main__":
    main()
