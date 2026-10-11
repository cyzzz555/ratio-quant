"""Mac research database: wheel binaries, owner-only socket, no TCP listening."""

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlencode

from app.settings import ROOT


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["init", "serve"])
    args = parser.parse_args()
    spec = importlib.util.find_spec("pgserver")
    if spec is None or spec.origin is None:
        raise RuntimeError("Mac PostgreSQL runtime missing; uv sync --group mac")
    binary = Path(spec.origin).parent / "pginstall/bin"
    data = ROOT / ".runtime/postgres-research"
    socket = Path("/private/tmp/quant-v12-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:10])
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    socket.mkdir(exist_ok=True, mode=0o700)
    data.chmod(0o700)
    socket.chmod(0o700)
    if args.action == "init":
        if not (data / "PG_VERSION").exists():
            subprocess.run(
                [
                    str(binary / "initdb"),
                    "-D",
                    str(data),
                    "--auth-local=trust",
                    "--auth-host=reject",
                    "-U",
                    "quant_local",
                    "--encoding=UTF8",
                    "--locale=C",
                    "-c",
                    "shared_memory_type=mmap",
                    "-c",
                    "dynamic_shared_memory_type=mmap",
                ],
                check=True,
            )
        url = "postgresql+psycopg://quant_local@/postgres?" + urlencode(
            {
                "host": str(socket),
                "port": "55432",
            }
        )
        (ROOT / "config/local_runtime.json").write_text(
            json.dumps({"database_url": url}) + "\n", encoding="utf-8"
        )
        print("Local research database initialized; no TCP listener configured")
    else:
        os.execv(
            str(binary / "postgres"),
            [
                str(binary / "postgres"),
                "-D",
                str(data),
                "-h",
                "",
                "-k",
                str(socket),
                "-p",
                "55432",
            ],
        )


if __name__ == "__main__":
    main()
