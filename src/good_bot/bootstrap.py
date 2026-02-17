from __future__ import annotations

import os
import shutil
import subprocess
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
    _maybe_pull_latest_on_startup()

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


def _maybe_pull_latest_on_startup() -> None:
    if not _parse_bool_env("GOOD_BOT_GIT_PULL_ON_STARTUP", False):
        return
    if os.environ.get("GOOD_BOT_STARTUP_PULL_DONE") == "1":
        return

    workspace = Path(os.environ.get("GOOD_BOT_WORKSPACE", ".")).resolve()
    remote = os.environ.get("GOOD_BOT_GIT_REMOTE", "origin")
    configured_branch = (os.environ.get("GOOD_BOT_GIT_BRANCH", "") or "").strip() or None

    try:
        _run_git(["rev-parse", "--is-inside-work-tree"], workspace)
    except RuntimeError as exc:
        print(f"[startup] Skipping git pull: {exc}", file=sys.stderr)
        os.environ["GOOD_BOT_STARTUP_PULL_DONE"] = "1"
        return

    try:
        status = _run_git(["status", "--porcelain"], workspace)
        if status.strip():
            print("[startup] Skipping git pull because workspace has uncommitted changes.", file=sys.stderr)
            os.environ["GOOD_BOT_STARTUP_PULL_DONE"] = "1"
            return

        branch = configured_branch or _run_git(["rev-parse", "--abbrev-ref", "HEAD"], workspace)
        if not branch or branch == "HEAD":
            print("[startup] Skipping git pull on detached HEAD.", file=sys.stderr)
            os.environ["GOOD_BOT_STARTUP_PULL_DONE"] = "1"
            return

        _run_git(["fetch", remote, branch], workspace)
        _run_git(["pull", "--ff-only", remote, branch], workspace)
        print(f"[startup] Pulled latest changes from {remote}/{branch}.", file=sys.stderr)
    except RuntimeError as exc:
        print(f"[startup] Git pull skipped due to error: {exc}", file=sys.stderr)
    finally:
        os.environ["GOOD_BOT_STARTUP_PULL_DONE"] = "1"


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


def _run_git(args: list[str], workspace: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(workspace),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or f"exit code {completed.returncode}"
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return (completed.stdout or "").strip()
