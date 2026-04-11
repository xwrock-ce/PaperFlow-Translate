from __future__ import annotations

import shutil
import socket
import subprocess
from pathlib import Path

import uvicorn

from pdf2zh_next.http_api import create_app
from pdf2zh_next.web_schema import get_frontend_dist_dir


def _frontend_root_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "frontend"


def _ensure_port_available(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError as exc:
            raise RuntimeError(
                f"Port {port} is already in use. Start the GUI with --server-port <free-port>."
            ) from exc


def _ensure_frontend_build() -> None:
    dist_dir = get_frontend_dist_dir()
    if (dist_dir / "index.html").exists():
        return

    frontend_root = _frontend_root_dir()
    if not frontend_root.exists():
        raise RuntimeError("The React frontend sources were not found.")
    npm_path = shutil.which("npm")
    if npm_path is None:
        raise RuntimeError(
            "npm is required to build the React WebUI. Install Node.js and retry."
        )

    if not (frontend_root / "node_modules").exists():
        subprocess.run([npm_path, "install"], cwd=frontend_root, check=True)
    subprocess.run([npm_path, "run", "build"], cwd=frontend_root, check=True)


async def setup_gui(
    server_host: str = "127.0.0.1",
    server_port: int = 7860,
) -> None:
    _ensure_port_available(server_host, server_port)
    _ensure_frontend_build()
    config = uvicorn.Config(
        create_app(serve_frontend=True),
        host=server_host,
        port=server_port,
    )
    server = uvicorn.Server(config)
    await server.serve()
