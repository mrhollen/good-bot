from __future__ import annotations

import os
import selectors
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .git_ops import GitSyncError, GitSyncResult, commit_and_push_update
from .openrouter import OpenRouterClient
from .protocol import terminate_current_instance, wait_for_handshake
from .state import StateStore
from .ui import EventSink

SYSTEM_PROMPT = """You are good-bot, a self-improving Python agent framework maintainer.
You operate inside a git repository with shell and file operation tools.
Goal: complete the user's goal with high-quality, testable changes.

Always respond by calling exactly one provided tool.
- Prefer file tools for common read/write/list operations.
- If an exact file path is uncertain, call `list_files` first. Do not guess paths.
- Use `run_command` when shell access is genuinely needed.
- Use `restart` only after completing an improvement that should hand off to a fresh process.
- Use `respond` as final output when you are done and want operator input next.
- If you must emit an interim operator message but continue work in the same cycle, set `respond.continue_cycle=true`.
- Keep actions focused and safe.
"""
AGENTS_FILE_NAME = "AGENTS.md"
AGENTS_PROMPT_MAX_CHARS = 16000


def _trim(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n...[truncated]..."


ACTION_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories under a path inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to workspace. Defaults to '.'.",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Whether to recursively include children. Defaults to true.",
                    },
                    "max_entries": {
                        "type": "integer",
                        "description": "Maximum number of entries to return. Defaults to 200.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Optional short operator-facing status message.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read text from a file inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to workspace.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "1-based start line (inclusive). Optional.",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "1-based end line (inclusive). Optional.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Optional short operator-facing status message.",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write text to a file inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to workspace.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Text content to write.",
                    },
                    "append": {
                        "type": "boolean",
                        "description": "Append to file instead of overwrite. Defaults to false.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Optional short operator-facing status message.",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run one shell command in the workspace and continue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "A shell command to execute.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Optional short operator-facing status message.",
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "respond",
            "description": (
                "Return a response for the operator. By default this ends the current cycle and "
                "the runtime waits for user input (even in autonomous mode). "
                "Set continue_cycle=true only for interim messages when more work remains now."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Operator-facing response text.",
                    },
                    "continue_cycle": {
                        "type": "boolean",
                        "description": (
                            "If true, keep the current cycle running after this response. "
                            "Defaults to false."
                        ),
                    },
                    "summary": {
                        "type": "string",
                        "description": "Optional short operator-facing status message.",
                    },
                },
                "required": ["message"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "restart",
            "description": (
                "Request a protocol restart after a completed improvement so a fresh process takes over."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Short reason for restart and commit message context.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Optional short operator-facing status message.",
                    },
                },
                "required": ["reason"],
                "additionalProperties": False,
            },
        },
    },
]


@dataclass(frozen=True)
class RunResult:
    message: str
    pause_for_user: bool


@dataclass
class Agent:
    config: Config
    store: StateStore
    client: OpenRouterClient
    instance_id: str
    events: EventSink | None = None
    _cached_system_prompt: str | None = None

    def run(self, goal: str, *, max_steps: int, child_token: str | None = None) -> RunResult:
        state = self.store.load()
        state["current_instance_id"] = self.instance_id
        self._emit("cycle_start", goal=goal)
        self.store.append_event(
            state,
            kind="instance_started",
            content=f"instance={self.instance_id}",
            metadata={"child_token": child_token} if child_token else None,
        )

        if child_token:
            self._announce_handshake(child_token)
            self.store.append_event(
                state,
                kind="handshake_sent",
                content=f"child handshake sent for token={child_token}",
            )

        step = 1
        while max_steps <= 0 or step <= max_steps:
            self._emit("step_start", step=step, max_steps=max_steps)
            decision = self._plan_next_action(goal, state, step=step, max_steps=max_steps)
            action = decision["action"]
            self._emit("model_action", action=action, summary=decision.get("summary", ""))

            if action == "list_files":
                path = decision.get("path", ".")
                recursive = decision.get("recursive", "true").lower() == "true"
                try:
                    max_entries = int(decision.get("max_entries", "200"))
                except ValueError:
                    max_entries = 200
                self._emit(
                    "status",
                    message=f"list_files path={path} recursive={recursive} max_entries={max_entries}",
                )
                result = self._list_files(path=path, recursive=recursive, max_entries=max_entries)
                self.store.append_event(
                    state,
                    kind="file_result",
                    content=_trim(result, self.config.max_output_chars),
                    metadata={"step": step, "operation": "list_files", "path": path},
                )
                step += 1
                continue

            if action == "read_file":
                path = decision.get("path", "")
                try:
                    start_line = int(decision["start_line"]) if decision.get("start_line") else None
                except ValueError:
                    start_line = None
                try:
                    end_line = int(decision["end_line"]) if decision.get("end_line") else None
                except ValueError:
                    end_line = None
                self._emit(
                    "status",
                    message=f"read_file path={path} start={start_line} end={end_line}",
                )
                result = self._read_file(path=path, start_line=start_line, end_line=end_line)
                self.store.append_event(
                    state,
                    kind="file_result",
                    content=_trim(result, self.config.max_output_chars),
                    metadata={"step": step, "operation": "read_file", "path": path},
                )
                step += 1
                continue

            if action == "write_file":
                path = decision.get("path", "")
                append = decision.get("append", "false").lower() == "true"
                content = decision.get("content", "")
                self._emit(
                    "status",
                    message=f"write_file path={path} append={append} chars={len(content)}",
                )
                result = self._write_file(path=path, content=content, append=append)
                self.store.append_event(
                    state,
                    kind="file_result",
                    content=_trim(result, self.config.max_output_chars),
                    metadata={"step": step, "operation": "write_file", "path": path},
                )
                step += 1
                continue

            if action == "run_command":
                command = decision.get("command", "").strip()
                if not command:
                    self.store.append_event(
                        state,
                        kind="invalid_action",
                        content="Model returned run_command without command.",
                    )
                    step += 1
                    continue

                result = self._run_command(command)
                content = (
                    f"Command: {command}\n"
                    f"Return code: {result['returncode']}\n"
                    f"Timed out: {result['timed_out']}\n"
                    f"stdout:\n{result['stdout']}\n"
                    f"stderr:\n{result['stderr']}"
                )
                self.store.append_event(
                    state,
                    kind="command_result",
                    content=_trim(content, self.config.max_output_chars),
                    metadata={"step": step},
                )
                step += 1
                continue

            if action == "restart":
                reason = decision.get("reason", "self-improvement")
                remaining_steps = None if max_steps <= 0 else max_steps - step
                message = self._restart(
                    goal,
                    state,
                    reason=reason,
                    remaining_steps=remaining_steps,
                )
                return RunResult(message=message, pause_for_user=False)

            if action == "respond":
                message = decision.get("message", "").strip()
                if not message:
                    message = "No response produced."
                continue_cycle = decision.get("continue_cycle", "false").lower() == "true"
                self._emit("agent_message", message=message)
                self.store.append_event(
                    state,
                    kind="interim_response" if continue_cycle else "final_response",
                    content=message,
                    metadata={"step": step, "continue_cycle": continue_cycle},
                )
                if continue_cycle:
                    step += 1
                    continue
                return RunResult(message=message, pause_for_user=True)

            message = f"Model returned unsupported action '{action}'."
            self.store.append_event(state, kind="invalid_action", content=message)
            step += 1

        # Reaching this path means a bounded max_steps limit was configured.
        fallback = (
            f"Stopped after {max_steps} steps without a final response. "
            "Increase GOOD_BOT_MAX_STEPS or provide a tighter goal."
        )
        self.store.append_event(state, kind="max_steps_reached", content=fallback)
        return RunResult(message=fallback, pause_for_user=False)

    def _plan_next_action(
        self, goal: str, state: dict[str, Any], *, step: int, max_steps: int
    ) -> dict[str, str]:
        all_events = state.get("events", [])
        if self.config.history_events <= 0:
            recent_events = all_events
        else:
            recent_events = all_events[-self.config.history_events :]
        history_lines = []
        for event in recent_events:
            history_lines.append(
                f"- {event.get('timestamp', '')} {event.get('kind', '')}: "
                f"{_trim(str(event.get('content', '')), 1200)}"
            )
        history_text = "\n".join(history_lines) if history_lines else "- (none)"

        step_text = "unbounded" if max_steps <= 0 else str(max_steps)
        user_prompt = (
            f"Goal:\n{goal}\n\n"
            f"Current step: {step}/{step_text}\n"
            f"Recent events:\n{history_text}\n\n"
            "Choose exactly one tool call for the next action."
        )
        completion = self.client.create_chat_completion(
            [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
            tools=ACTION_TOOLS,
            tool_choice="required",
        )

        if not completion.tool_calls:
            message = completion.content.strip() or "Model returned no tool call."
            return {
                "action": "respond",
                "command": "",
                "message": _trim(message, 2000),
                "continue_cycle": "false",
                "reason": "",
                "summary": "No tool call was returned by the model.",
            }

        call = completion.tool_calls[0]
        args = call.arguments
        summary_value = args.get("summary", "")
        summary = summary_value if isinstance(summary_value, str) else str(summary_value)

        if call.name == "list_files":
            path_value = args.get("path", ".")
            recursive_value = args.get("recursive", True)
            max_entries_value = args.get("max_entries", 200)
            path = path_value if isinstance(path_value, str) else str(path_value)
            recursive = recursive_value if isinstance(recursive_value, bool) else bool(recursive_value)
            try:
                max_entries = int(max_entries_value)
            except (TypeError, ValueError):
                max_entries = 200
            return {
                "action": "list_files",
                "path": path.strip() or ".",
                "recursive": str(recursive).lower(),
                "max_entries": str(max_entries),
                "command": "",
                "message": "",
                "reason": "",
                "summary": summary.strip(),
            }
        if call.name == "read_file":
            path_value = args.get("path", "")
            start_line_value = args.get("start_line")
            end_line_value = args.get("end_line")
            path = path_value if isinstance(path_value, str) else str(path_value)
            return {
                "action": "read_file",
                "path": path.strip(),
                "start_line": "" if start_line_value is None else str(start_line_value),
                "end_line": "" if end_line_value is None else str(end_line_value),
                "command": "",
                "message": "",
                "reason": "",
                "summary": summary.strip(),
            }
        if call.name == "write_file":
            path_value = args.get("path", "")
            content_value = args.get("content", "")
            append_value = args.get("append", False)
            path = path_value if isinstance(path_value, str) else str(path_value)
            content = content_value if isinstance(content_value, str) else str(content_value)
            append = append_value if isinstance(append_value, bool) else bool(append_value)
            return {
                "action": "write_file",
                "path": path.strip(),
                "content": content,
                "append": str(append).lower(),
                "command": "",
                "message": "",
                "reason": "",
                "summary": summary.strip(),
            }
        if call.name == "run_command":
            command_value = args.get("command", "")
            command = command_value if isinstance(command_value, str) else str(command_value)
            return {
                "action": "run_command",
                "command": command.strip(),
                "message": "",
                "reason": "",
                "summary": summary.strip(),
            }
        if call.name == "restart":
            reason_value = args.get("reason", "")
            reason = reason_value if isinstance(reason_value, str) else str(reason_value)
            return {
                "action": "restart",
                "command": "",
                "message": "",
                "reason": reason.strip(),
                "summary": summary.strip(),
            }
        if call.name == "respond":
            message_value = args.get("message", "")
            message = message_value if isinstance(message_value, str) else str(message_value)
            continue_cycle_value = args.get("continue_cycle", False)
            continue_cycle = (
                continue_cycle_value
                if isinstance(continue_cycle_value, bool)
                else str(continue_cycle_value).strip().lower() in {"1", "true", "yes", "on"}
            )
            return {
                "action": "respond",
                "command": "",
                "message": message.strip(),
                "continue_cycle": str(continue_cycle).lower(),
                "reason": "",
                "summary": summary.strip(),
            }

        fallback_message = f"Model called unknown tool '{call.name}'."
        if completion.content:
            fallback_message = f"{fallback_message} {completion.content.strip()}"
        return {
            "action": "respond",
            "command": "",
            "message": _trim(fallback_message, 2000),
            "continue_cycle": "false",
            "reason": "",
            "summary": "Unknown tool call returned by model.",
        }

    def _resolve_workspace_path(self, path_value: str) -> Path:
        workspace = Path(self.config.workspace).resolve()
        candidate = (workspace / path_value).resolve()
        if not candidate.is_relative_to(workspace):
            raise ValueError(f"Path escapes workspace: {path_value}")
        return candidate

    def _system_prompt(self) -> str:
        if self._cached_system_prompt is not None:
            return self._cached_system_prompt

        prompt = SYSTEM_PROMPT.rstrip()
        agents_context = self._load_agents_md_context()
        if agents_context:
            prompt = f"{prompt}\n\nContents of AGENTS.md file:\n{agents_context}"

        self._cached_system_prompt = prompt
        return prompt

    def _load_agents_md_context(self) -> str:
        agents_path = Path(self.config.workspace).resolve() / AGENTS_FILE_NAME
        if not agents_path.is_file():
            return ""
        try:
            content = agents_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return ""
        if not content:
            return ""
        return _trim(content, AGENTS_PROMPT_MAX_CHARS)

    def _list_files(self, *, path: str, recursive: bool, max_entries: int) -> str:
        try:
            directory = self._resolve_workspace_path(path or ".")
        except ValueError as exc:
            return f"list_files error: {exc}"
        if not directory.exists():
            return f"list_files error: path does not exist: {path}"
        if not directory.is_dir():
            return f"list_files error: path is not a directory: {path}"

        safe_max = max(1, min(max_entries, 2000))
        workspace = Path(self.config.workspace).resolve()
        entries: list[str] = []

        iterator = directory.rglob("*") if recursive else directory.iterdir()
        for entry in iterator:
            rel = entry.relative_to(workspace)
            suffix = "/" if entry.is_dir() else ""
            entries.append(f"{rel}{suffix}")
            if len(entries) >= safe_max:
                break

        entries.sort()
        if not entries:
            return f"No entries found under {path}"
        if len(entries) >= safe_max:
            return "\n".join(entries) + f"\n...[truncated to {safe_max} entries]..."
        return "\n".join(entries)

    def _read_file(self, *, path: str, start_line: int | None, end_line: int | None) -> str:
        try:
            file_path = self._resolve_workspace_path(path)
        except ValueError as exc:
            return f"read_file error: {exc}"
        if not file_path.exists():
            return f"read_file error: file does not exist: {path}"
        if not file_path.is_file():
            return f"read_file error: path is not a file: {path}"

        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"read_file error: file is not valid utf-8 text: {path}"

        lines = text.splitlines()
        if start_line is None:
            start_idx = 0
        else:
            start_idx = max(start_line - 1, 0)
        if end_line is None:
            end_idx = len(lines)
        else:
            end_idx = min(max(end_line, 0), len(lines))
        if end_idx < start_idx:
            end_idx = start_idx

        selected = lines[start_idx:end_idx]
        numbered = [f"{i + start_idx + 1:>6} {line}" for i, line in enumerate(selected)]
        if not numbered:
            return f"read_file result: no lines selected in {path}"
        return "\n".join(numbered)

    def _write_file(self, *, path: str, content: str, append: bool) -> str:
        try:
            file_path = self._resolve_workspace_path(path)
        except ValueError as exc:
            return f"write_file error: {exc}"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with file_path.open(mode, encoding="utf-8") as fh:
            fh.write(content)

        action = "appended to" if append else "wrote"
        return f"write_file ok: {action} {path} ({len(content)} chars)"

    def _run_command(self, command: str) -> dict[str, Any]:
        self._emit("command_start", command=command)
        started_at = time.time()
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        timed_out = False

        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.config.workspace),
                shell=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
            )
        except OSError as exc:
            self._emit("status", message=f"Command launch failed: {exc}")
            return {
                "returncode": -1,
                "timed_out": False,
                "stdout": "",
                "stderr": _trim(str(exc), self.config.max_output_chars),
            }

        selector = selectors.DefaultSelector()
        assert process.stdout is not None
        assert process.stderr is not None
        selector.register(process.stdout, selectors.EVENT_READ, data="stdout")
        selector.register(process.stderr, selectors.EVENT_READ, data="stderr")

        while selector.get_map():
            if self.config.command_timeout_seconds > 0 and (
                time.time() - started_at
            ) > self.config.command_timeout_seconds:
                timed_out = True
                process.kill()
                break

            ready = selector.select(timeout=0.2)
            if not ready:
                if process.poll() is not None:
                    break
                continue

            for key, _ in ready:
                stream = key.fileobj
                chunk = stream.readline()
                if chunk == "":
                    try:
                        selector.unregister(stream)
                    except Exception:
                        pass
                    continue
                source = str(key.data)
                if source == "stdout":
                    stdout_parts.append(chunk)
                else:
                    stderr_parts.append(chunk)
                self._emit("command_output", source=source, text=chunk)

        try:
            extra_out, extra_err = process.communicate(timeout=0.2)
        except subprocess.TimeoutExpired:
            process.kill()
            extra_out, extra_err = process.communicate()
            timed_out = True

        if extra_out:
            stdout_parts.append(extra_out)
            for line in extra_out.splitlines(keepends=True):
                self._emit("command_output", source="stdout", text=line)
        if extra_err:
            stderr_parts.append(extra_err)
            for line in extra_err.splitlines(keepends=True):
                self._emit("command_output", source="stderr", text=line)

        result = {
            "returncode": -1 if timed_out else int(process.returncode or 0),
            "timed_out": timed_out,
            "stdout": _trim("".join(stdout_parts), self.config.max_output_chars),
            "stderr": _trim("".join(stderr_parts), self.config.max_output_chars),
        }
        self._emit(
            "command_end",
            returncode=result["returncode"],
            timed_out=result["timed_out"],
        )
        return result

    def _announce_handshake(self, child_token: str) -> None:
        from .protocol import write_handshake

        write_handshake(self.config.runtime_dir, child_token, instance_id=self.instance_id)

    def _restart(
        self,
        goal: str,
        state: dict[str, Any],
        *,
        reason: str,
        remaining_steps: int | None,
    ) -> str:
        if int(state.get("restarts", 0)) >= self.config.max_restarts:
            message = (
                f"Restart requested but max restarts reached ({self.config.max_restarts}). "
                "Continuing in current instance."
            )
            self.store.append_event(state, kind="restart_blocked", content=message)
            return message

        token = uuid.uuid4().hex
        child_cmd = [
            sys.executable,
            "-m",
            "good_bot",
            "--goal",
            goal,
            "--max-steps",
            "0" if remaining_steps is None else str(max(1, remaining_steps)),
            "--state-path",
            str(self.config.state_path.resolve()),
            "--workspace",
            str(Path(self.config.workspace).resolve()),
            "--child-token",
            token,
        ]
        child_env = os.environ.copy()
        child_env["GOOD_BOT_RUNTIME_DIR"] = str(self.config.runtime_dir.resolve())
        child_env.pop("GOOD_BOT_CODE_FROZEN_PID", None)
        child_env.pop("GOOD_BOT_CODE_SNAPSHOT_ROOT", None)
        child_env.pop("GOOD_BOT_STARTUP_PULL_DONE", None)
        subprocess.Popen(
            child_cmd,
            cwd=str(Path(self.config.workspace).resolve()),
            env=child_env,
        )
        self.store.append_event(
            state,
            kind="restart_spawned",
            content="Spawned successor instance.",
            metadata={"token": token, "reason": reason},
        )

        handshake = wait_for_handshake(self.config.runtime_dir, token)
        if handshake is None:
            message = "Restart failed: successor did not complete handshake."
            self._emit("status", message=message)
            self.store.append_event(state, kind="restart_failed", content=message)
            return message

        self.store.append_event(
            state,
            kind="restart_confirmed",
            content=f"Handshake confirmed with pid={handshake.get('pid')}",
            metadata={"token": token, "reason": reason},
        )

        try:
            git_sync = self._commit_and_push_after_handshake(reason=reason)
        except GitSyncError as exc:
            message = f"Restart paused: handshake succeeded but git commit/push failed: {exc}"
            self._emit("status", message=message)
            self.store.append_event(
                state,
                kind="git_sync_failed",
                content=message,
                metadata={"token": token, "reason": reason},
            )
            return message

        self.store.append_event(
            state,
            kind="git_sync_completed",
            content=git_sync.summary,
            metadata={
                "token": token,
                "reason": reason,
                "committed": git_sync.committed,
                "pushed": git_sync.pushed,
                "commit_sha": git_sync.commit_sha,
            },
        )

        state["restarts"] = int(state.get("restarts", 0)) + 1
        self.store.append_event(
            state,
            kind="restart_terminating",
            content="Terminating current instance after handshake and git sync.",
            metadata={"token": token, "reason": reason},
        )
        self._emit("status", message="Restart confirmed; terminating current instance.")
        terminate_current_instance(0)
        return "Restarted successfully."

    def _commit_and_push_after_handshake(self, *, reason: str) -> GitSyncResult:
        if not self.config.git_auto_push:
            return GitSyncResult(
                committed=False,
                pushed=False,
                commit_sha=None,
                summary="GOOD_BOT_GIT_AUTO_PUSH is disabled; skipping git commit/push.",
            )

        compact_reason = " ".join(reason.split())
        if not compact_reason:
            compact_reason = "self-improvement update"
        commit_message = f"{self.config.git_commit_prefix}: {compact_reason}"[:180]

        return commit_and_push_update(
            workspace=Path(self.config.workspace).resolve(),
            remote=self.config.git_remote,
            branch=self.config.git_branch,
            commit_message=commit_message,
            author_name=self.config.git_author_name,
            author_email=self.config.git_author_email,
            github_token=self.config.github_token,
            github_repo=self.config.github_repo,
        )

    def _emit(self, event: str, **payload: Any) -> None:
        if self.events is None:
            return
        try:
            self.events.emit(event, **payload)
        except Exception:
            # UI failures should never interrupt agent execution.
            return
