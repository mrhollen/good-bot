from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, Protocol


class EventSink(Protocol):
    def emit(self, event: str, **payload: Any) -> None:
        pass


class ConsoleEventStream:
    def __init__(self, *, stream=None, use_color: bool | None = None) -> None:
        self._stream = stream or sys.stdout
        self._use_color = self._stream.isatty() if use_color is None else use_color

    def emit(self, event: str, **payload: Any) -> None:
        if event == "cycle_start":
            self._line("cycle", f"goal={payload.get('goal', '')}")
            return
        if event == "step_start":
            max_steps = payload.get("max_steps")
            total = "unbounded" if isinstance(max_steps, int) and max_steps <= 0 else str(max_steps)
            self._line("step", f"{payload.get('step')}/{total}")
            return
        if event == "model_action":
            action = payload.get("action", "unknown")
            summary = (payload.get("summary") or "").strip()
            text = f"action={action}"
            if summary:
                text = f"{text} | {summary}"
            self._line("plan", text)
            return
        if event == "command_start":
            self._line("cmd", payload.get("command", ""))
            return
        if event == "command_output":
            source = payload.get("source", "stdout")
            prefix = "out" if source == "stdout" else "err"
            self._line(prefix, (payload.get("text") or "").rstrip("\n"))
            return
        if event == "command_end":
            self._line(
                "cmd",
                f"done rc={payload.get('returncode')} timeout={payload.get('timed_out')}",
            )
            return
        if event == "agent_message":
            self._line("agent", payload.get("message", ""))
            return
        if event == "status":
            self._line("status", payload.get("message", ""))
            return
        if event == "file_output":
            text = str(payload.get("text", ""))
            if text == "":
                self._line("file", "")
                return
            for line in text.splitlines():
                self._line("file", line)
            return

    def _line(self, tag: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        if self._use_color:
            tag_text = f"\x1b[36m[{tag}]\x1b[0m"
        else:
            tag_text = f"[{tag}]"
        print(f"{timestamp} {tag_text} {message}", file=self._stream, flush=True)
