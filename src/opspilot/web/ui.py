from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


def run_ui_app() -> None:
    root = Path(__file__).resolve().parents[3]
    frontend_dir = root / "frontend"
    npm_executable = shutil.which("npm.cmd") or shutil.which("npm")

    if npm_executable is None:
        raise RuntimeError("未找到 npm，请先安装 Node.js 20+。")
    if not frontend_dir.exists():
        raise RuntimeError(f"未找到前端工程目录：{frontend_dir}")
    if not (frontend_dir / "node_modules").exists():
        raise RuntimeError("前端依赖未安装，请先执行 `cd frontend && npm install`。")

    subprocess.run(
        [npm_executable, "run", "dev", "--", "--host", "0.0.0.0", "--port", "8080", "--strictPort"],
        cwd=frontend_dir,
        check=True,
    )
