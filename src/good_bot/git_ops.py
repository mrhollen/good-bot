from __future__ import annotations

import base64
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitSyncResult:
    committed: bool
    pushed: bool
    commit_sha: str | None
    summary: str


def _append_git_config_env(
    env: dict[str, str],
    *,
    key: str,
    value: str,
) -> None:
    count_raw = env.get("GIT_CONFIG_COUNT", "0")
    try:
        count = int(count_raw)
    except ValueError:
        count = 0
    env[f"GIT_CONFIG_KEY_{count}"] = key
    env[f"GIT_CONFIG_VALUE_{count}"] = value
    env["GIT_CONFIG_COUNT"] = str(count + 1)


def _auth_env(github_token: str, base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env or os.environ)
    basic = base64.b64encode(f"x-access-token:{github_token}".encode("utf-8")).decode("ascii")
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    # Configure auth at process scope so subprocess git commands (including plain `git push`)
    # can run non-interactively against GitHub HTTPS remotes.
    _append_git_config_env(
        env,
        key="http.https://github.com/.extraheader",
        value=f"AUTHORIZATION: basic {basic}",
    )
    # Keep this for compatibility with older flows/tools that inspect this variable.
    env["GIT_HTTP_EXTRAHEADER"] = f"AUTHORIZATION: basic {basic}"
    return env


def configure_process_git_env(
    *,
    github_token: str | None,
    rewrite_ssh_to_https: bool,
) -> None:
    if github_token:
        os.environ.update(_auth_env(github_token, os.environ))

    if rewrite_ssh_to_https and github_token:
        tokenized_base = f"https://x-access-token:{github_token}@github.com/"
        _append_git_config_env(
            os.environ,
            key=f"url.{tokenized_base}.insteadOf",
            value="https://github.com/",
        )
        _append_git_config_env(
            os.environ,
            key=f"url.{tokenized_base}.insteadOf",
            value="git@github.com:",
        )
        _append_git_config_env(
            os.environ,
            key=f"url.{tokenized_base}.insteadOf",
            value="ssh://git@github.com/",
        )


def _run_git(
    args: list[str],
    *,
    workspace: Path,
    env: dict[str, str] | None = None,
) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(workspace),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise GitSyncError(stderr or f"git {' '.join(args[:2])} failed with code {completed.returncode}")
    return (completed.stdout or "").strip()


def verify_github_token_access(
    *,
    workspace: Path,
    github_token: str,
    github_repo: str,
) -> None:
    auth_env = _auth_env(github_token)
    _run_git(
        ["ls-remote", "--exit-code", f"https://github.com/{github_repo}.git", "HEAD"],
        workspace=workspace,
        env=auth_env,
    )


def commit_and_push_update(
    *,
    workspace: Path,
    remote: str,
    branch: str | None,
    commit_message: str,
    author_name: str | None,
    author_email: str | None,
    github_token: str | None,
    github_repo: str | None,
) -> GitSyncResult:
    _run_git(["rev-parse", "--is-inside-work-tree"], workspace=workspace)
    status = _run_git(["status", "--porcelain"], workspace=workspace)
    has_changes = bool(status)

    commit_sha: str | None = None
    if has_changes:
        _run_git(["add", "-A"], workspace=workspace)

        commit_env = None
        if author_name or author_email:
            commit_env = dict(os.environ)
            if author_name:
                commit_env["GIT_AUTHOR_NAME"] = author_name
                commit_env["GIT_COMMITTER_NAME"] = author_name
            if author_email:
                commit_env["GIT_AUTHOR_EMAIL"] = author_email
                commit_env["GIT_COMMITTER_EMAIL"] = author_email

        _run_git(["commit", "-m", commit_message], workspace=workspace, env=commit_env)
        commit_sha = _run_git(["rev-parse", "--short", "HEAD"], workspace=workspace)

    branch_name = branch or _run_git(["rev-parse", "--abbrev-ref", "HEAD"], workspace=workspace)
    if not branch_name or branch_name == "HEAD":
        raise GitSyncError("Cannot push from detached HEAD. Set GOOD_BOT_GIT_BRANCH.")

    if github_token:
        if not github_repo:
            raise GitSyncError("GOOD_BOT_GITHUB_REPO is required when GOOD_BOT_GITHUB_TOKEN is set.")
        push_env = _auth_env(github_token)
        _run_git(
            ["push", f"https://github.com/{github_repo}.git", f"HEAD:{branch_name}"],
            workspace=workspace,
            env=push_env,
        )
    else:
        _run_git(["push", remote, f"HEAD:{branch_name}"], workspace=workspace)

    if has_changes:
        return GitSyncResult(
            committed=True,
            pushed=True,
            commit_sha=commit_sha,
            summary=f"Committed and pushed update on branch {branch_name} (sha {commit_sha}).",
        )
    return GitSyncResult(
        committed=False,
        pushed=True,
        commit_sha=None,
        summary=f"No local changes to commit; pushed branch {branch_name}.",
    )
