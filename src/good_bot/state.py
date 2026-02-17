from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StateStore:
    path: Path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default_state()
        with self.path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if "events" not in data:
            data["events"] = []
        if "restarts" not in data:
            data["restarts"] = 0
        return data

    def save(self, data: dict[str, Any]) -> None:
        data["updated_at"] = utc_now_iso()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        tmp_path.replace(self.path)

    def append_event(
        self,
        data: dict[str, Any],
        *,
        kind: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "timestamp": utc_now_iso(),
            "kind": kind,
            "content": content,
        }
        if metadata:
            event["metadata"] = metadata
        data.setdefault("events", []).append(event)
        self.save(data)

    def _default_state(self) -> dict[str, Any]:
        now = utc_now_iso()
        return {
            "schema_version": 1,
            "agent_id": str(uuid.uuid4()),
            "created_at": now,
            "updated_at": now,
            "restarts": 0,
            "events": [],
        }
