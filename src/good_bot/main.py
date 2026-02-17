from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

from .agent import Agent
from .config import Config
from .git_ops import GitSyncError, verify_github_token_access
from .openrouter import OpenRouterClient
from .state import StateStore
from .ui import ConsoleEventStream


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run good-bot agent.")
    parser.add_argument("--goal", type=str, default="", help="Goal for the agent.")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Maximum number of model/action loop steps.",
    )
    parser.add_argument(
        "--state-path",
        type=str,
        default=None,
        help="Path to the persistent state JSON file.",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="Workspace directory used for shell commands.",
    )
    parser.add_argument(
        "--env-file",
        type=str,
        default=".env",
        help="Path to .env file with OpenRouter configuration.",
    )
    parser.add_argument(
        "--child-token",
        type=str,
        default=None,
        help="Internal token used for restart handshake.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single agent cycle and exit without interactive prompt.",
    )
    parser.add_argument(
        "--autonomous",
        action="store_true",
        help="Keep running cycles without prompting for user input.",
    )
    parser.add_argument(
        "--stream",
        dest="stream",
        action="store_true",
        default=None,
        help="Stream step/action/command progress to stdout.",
    )
    parser.add_argument(
        "--no-stream",
        dest="stream",
        action="store_false",
        help="Disable progress streaming.",
    )
    return parser


def _validate_git_auth_if_enabled(config: Config) -> None:
    if not (config.git_auto_push and config.git_auth_check and config.github_token):
        return
    if not config.github_repo:
        raise ValueError("GOOD_BOT_GITHUB_REPO is required when GOOD_BOT_GITHUB_TOKEN is set.")
    try:
        verify_github_token_access(
            workspace=Path(config.workspace).resolve(),
            github_token=config.github_token,
            github_repo=config.github_repo,
        )
    except GitSyncError as exc:
        raise ValueError(f"GitHub token auth check failed: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = Config.from_env(
            env_path=Path(args.env_file),
            state_path=Path(args.state_path) if args.state_path else None,
            workspace=Path(args.workspace) if args.workspace else None,
            max_steps=args.max_steps,
        )
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        _validate_git_auth_if_enabled(config)
    except ValueError as exc:
        print(f"Startup check failed: {exc}", file=sys.stderr)
        return 2

    goal = args.goal.strip()
    if not goal:
        print("No --goal provided.", file=sys.stderr)
        return 2

    max_steps = args.max_steps if args.max_steps is not None else config.max_steps
    autonomous = args.autonomous or config.autonomous
    stream_enabled = config.stream_events if args.stream is None else bool(args.stream)
    event_stream = ConsoleEventStream() if stream_enabled else None

    store = StateStore(config.state_path)
    client = OpenRouterClient(
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
    )
    agent = Agent(
        config=config,
        store=store,
        client=client,
        instance_id=str(uuid.uuid4()),
        events=event_stream,
    )

    current_goal = goal
    child_token = args.child_token
    try:
        while True:
            result = agent.run(
                current_goal,
                max_steps=max_steps,
                child_token=child_token,
            )
            child_token = None
            print(result)

            if args.once:
                return 0
            if autonomous:
                if config.autonomous_pause_seconds > 0:
                    time.sleep(config.autonomous_pause_seconds)
                continue
            if not sys.stdin.isatty():
                return 0

            try:
                follow_up = input(
                    "Next instruction (Enter to continue, new text for a new goal, 'exit' to quit): "
                ).strip()
            except EOFError:
                return 0

            if follow_up.lower() in {"exit", "quit", "q"}:
                return 0
            if follow_up:
                current_goal = follow_up
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130

    return 0
