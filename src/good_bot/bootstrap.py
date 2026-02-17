from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


def _parse_bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def maybe_reexec_with_frozen_code(argv: list[str] | None = None) -> None:
    if not _parse_bool_env("GOOD_BOT_FREEZE_CODE", True):
        return

    frozen_pid = os.environ.get("GOOD_BOT_CODE_FROZEN_PID")
    if frozen_pid == str(os.getpid()):
        return

    package_dir = Path(__file__).resolve().parent
    source_root = package_dir.parent
    snapshot_root = _create_snapshot(source_root)

    env = os.environ.copy()
    env["GOOD_BOT_CODE_FROZEN_PID"] = str(os.getpid())
    env["GOOD_BOT_CODE_SNAPSHOT_ROOT"] = str(snapshot_root)
    previous_pythonpath = env.get("PYTHONPATH", "")
    if previous_pythonpath:
        env["PYTHONPATH"] = f"{snapshot_root}{os.pathsep}{previous_pythonpath}"
    else:
        env["PYTHONPATH"] = str(snapshot_root)

    args = [sys.executable, "-m", "good_bot", *(argv if argv is not None else sys.argv[1:])]
    os.execvpe(sys.executable, args, env)


def _create_snapshot(source_root: Path) -> Path:
    runtime_dir = Path(os.environ.get("GOOD_BOT_RUNTIME_DIR", ".good_bot/runtime"))
    snapshots_dir = runtime_dir / "snapshots"
    try:
        snapshots_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        snapshots_dir = Path(tempfile.gettempdir()) / "good_bot_snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

    snapshot_root = Path(tempfile.mkdtemp(prefix="code_", dir=str(snapshots_dir)))
    shutil.copytree(source_root / "good_bot", snapshot_root / "good_bot")
    return snapshot_root
