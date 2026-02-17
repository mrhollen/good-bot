from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .git_ops import GitSyncError, GitSyncResult, commit_and_push_update
from .openrouter import OpenRouterClient
from .protocol import terminate_current_instance, wait_for_handshake
from .state import StateStore

SYSTEM_PROMPT = """You are good-bot, a self-improving Python agent framework maintainer.
You operate inside a git repository and can run shell commands.
Goal: complete the user's goal with high-quality, testable changes.

Return exactly one JSON object, no markdown, no commentary.
Schema:
{
  "action": "run_command" | "respond" | "restart",
  "command": "<shell command, required for run_command>",
  "message": "<final user-facing response, required for respond>",
  "reason": "<short reason for restart, required for restart>"
}

Rules:
- Use run_command for concrete progress.
- Use restart only when you have made an improvement and need a clean successor process.
- Keep commands focused and safe.
"""


def _trim(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n...[truncated]..."


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)

    try:
        payload = json.loads(cleaned)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model output.")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Model JSON output was not an object.")
    return payload


@dataclass
class Agent:
    config: Config
    store: StateStore
    client: OpenRouterClient
    instance_id: str

    def run(self, goal: str, *, max_steps: int, child_token: str | None = None) -> str:
        state = self.store.load()
        state["current_instance_id"] = self.instance_id
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
            decision = self._plan_next_action(goal, state, step=step, max_steps=max_steps)
            action = decision["action"]

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
                return self._restart(goal, state, reason=reason, remaining_steps=remaining_steps)

            message = decision.get("message", "").strip()
            if not message:
                message = "No final response produced."
            self.store.append_event(
                state,
                kind="final_response",
                content=message,
                metadata={"step": step},
            )
            return message

        # Reaching this path means a bounded max_steps limit was configured.
        fallback = (
            f"Stopped after {max_steps} steps without a final response. "
            "Increase GOOD_BOT_MAX_STEPS or provide a tighter goal."
        )
        self.store.append_event(state, kind="max_steps_reached", content=fallback)
        return fallback

    def _plan_next_action(
        self, goal: str, state: dict[str, Any], *, step: int, max_steps: int
    ) -> dict[str, str]:
        recent_events = state.get("events", [])[-8:]
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
            "Return only a valid JSON object matching the schema."
        )
        raw = self.client.generate(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
        )

        try:
            payload = _extract_json(raw)
        except Exception:
            return {"action": "respond", "message": _trim(raw, 2000)}

        # Accept either flat schema or nested {"action":{"type":"..."}}
        action: str | None
        command: str | None
        message: str | None
        reason: str | None
        raw_action = payload.get("action")
        if isinstance(raw_action, dict):
            action = str(raw_action.get("type", "")).strip()
            command = str(raw_action.get("command", "")).strip()
            message = str(raw_action.get("message", "")).strip()
            reason = str(raw_action.get("reason", "")).strip()
        else:
            action = str(raw_action or "").strip()
            command = str(payload.get("command", "")).strip()
            message = str(payload.get("message", "")).strip()
            reason = str(payload.get("reason", "")).strip()

        if action not in {"run_command", "respond", "restart"}:
            return {
                "action": "respond",
                "message": _trim(raw, 2000),
            }
        return {
            "action": action,
            "command": command or "",
            "message": message or "",
            "reason": reason or "",
        }

    def _run_command(self, command: str) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.config.workspace),
                shell=True,
                text=True,
                capture_output=True,
                timeout=self.config.command_timeout_seconds,
                check=False,
            )
            return {
                "returncode": completed.returncode,
                "timed_out": False,
                "stdout": _trim(completed.stdout, self.config.max_output_chars),
                "stderr": _trim(completed.stderr, self.config.max_output_chars),
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "returncode": -1,
                "timed_out": True,
                "stdout": _trim((exc.stdout or ""), self.config.max_output_chars),
                "stderr": _trim((exc.stderr or ""), self.config.max_output_chars),
            }

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
