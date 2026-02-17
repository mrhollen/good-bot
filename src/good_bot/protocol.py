from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def handshake_file(runtime_dir: Path, token: str) -> Path:
    return runtime_dir / f"handshake_{token}.json"


def write_handshake(runtime_dir: Path, token: str, *, instance_id: str) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "token": token,
        "pid": os.getpid(),
        "instance_id": instance_id,
        "timestamp": _utc_now_iso(),
    }
    path = handshake_file(runtime_dir, token)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def wait_for_handshake(
    runtime_dir: Path, token: str, *, timeout_seconds: float = 20.0, poll_seconds: float = 0.2
) -> dict[str, Any] | None:
    path = handshake_file(runtime_dir, token)
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        time.sleep(poll_seconds)
    return None


def terminate_current_instance(exit_code: int = 0) -> None:
    raise SystemExit(exit_code)
