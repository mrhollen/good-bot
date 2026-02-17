from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_env_file(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            values[key] = value
    return values


@dataclass(frozen=True)
class Config:
    api_key: str
    model: str
    base_url: str
    state_path: Path
    runtime_dir: Path
    workspace: Path
    max_steps: int
    command_timeout_seconds: int
    max_output_chars: int
    max_restarts: int
    git_auto_push: bool
    git_auth_check: bool
    git_remote: str
    git_branch: str | None
    git_commit_prefix: str
    git_author_name: str | None
    git_author_email: str | None
    github_token: str | None
    github_repo: str | None

    @classmethod
    def from_env(
        cls,
        *,
        env_path: Path | None = None,
        state_path: Path | None = None,
        workspace: Path | None = None,
        max_steps: int | None = None,
    ) -> "Config":
        env_path = env_path or Path(".env")
        env_values = _parse_env_file(env_path)

        def get(name: str, default: str | None = None) -> str | None:
            if name in os.environ:
                return os.environ[name]
            return env_values.get(name, default)

        api_key = get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is required. Set it in .env or the environment."
            )

        state_path_value = state_path or Path(
            get("GOOD_BOT_STATE_PATH", ".good_bot/state.json")
        )
        workspace_value = workspace or Path(get("GOOD_BOT_WORKSPACE", "."))
        steps_value = max_steps if max_steps is not None else int(get("GOOD_BOT_MAX_STEPS", "0"))

        return cls(
            api_key=api_key,
            model=get("OPENROUTER_MODEL", "openrouter/auto") or "openrouter/auto",
            base_url=get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
            or "https://openrouter.ai/api/v1",
            state_path=Path(state_path_value),
            runtime_dir=Path(get("GOOD_BOT_RUNTIME_DIR", ".good_bot/runtime") or ".good_bot/runtime"),
            workspace=Path(workspace_value),
            max_steps=steps_value,
            command_timeout_seconds=int(get("GOOD_BOT_COMMAND_TIMEOUT_SECONDS", "120") or "120"),
            max_output_chars=int(get("GOOD_BOT_MAX_OUTPUT_CHARS", "8000") or "8000"),
            max_restarts=int(get("GOOD_BOT_MAX_RESTARTS", "3") or "3"),
            git_auto_push=_parse_bool(get("GOOD_BOT_GIT_AUTO_PUSH"), default=True),
            git_auth_check=_parse_bool(get("GOOD_BOT_GIT_AUTH_CHECK"), default=True),
            git_remote=get("GOOD_BOT_GIT_REMOTE", "origin") or "origin",
            git_branch=(get("GOOD_BOT_GIT_BRANCH", "") or "").strip() or None,
            git_commit_prefix=get("GOOD_BOT_GIT_COMMIT_PREFIX", "good-bot") or "good-bot",
            git_author_name=(get("GOOD_BOT_GIT_AUTHOR_NAME", "") or "").strip() or None,
            git_author_email=(get("GOOD_BOT_GIT_AUTHOR_EMAIL", "") or "").strip() or None,
            github_token=(get("GOOD_BOT_GITHUB_TOKEN", "") or "").strip() or None,
            github_repo=(get("GOOD_BOT_GITHUB_REPO", "") or "").strip() or None,
        )
