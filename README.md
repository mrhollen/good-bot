# good-bot

Python MVP for a self-improving agent framework that uses OpenRouter.

## What this MVP includes

- OpenRouter chat-completions client implemented with Python stdlib (`urllib`).
- Agent loop that asks the model for one JSON action per step:
  - `run_command`
  - `respond`
  - `restart`
- Persistent state on disk (`.good_bot/state.json`) so ephemeral sessions can recover context.
- Live CLI event stream (steps, selected action, command output, status).
- Optional autonomous mode that keeps cycling without interactive prompts.
- Self-improvement protocol support:
  1. Spawn a new process.
  2. Child writes a handshake file.
  3. Parent confirms handshake.
  4. Parent commits and pushes changes.
  5. Parent terminates itself with a built-in tool.
- Code-freeze bootstrap: each process can exec from a startup snapshot so runtime code stays stable while files on disk change.
- Unit tests for config parsing, state persistence, and handshake helpers.

## Setup

1. Create and activate a virtual environment:
   - `python -m venv .venv`
   - `source .venv/bin/activate`
2. Set environment variables:
   - `cp .env.example .env`
   - Set `OPENROUTER_API_KEY`
   - Optionally change `OPENROUTER_MODEL`

## Run (local)

Run from repository root:

```bash
PYTHONPATH=src python -m good_bot --goal "Create a minimal Python package layout and tests"
```

Optional flags:

- `--max-steps 0` (`0` means unbounded loop)
- `--state-path .good_bot/state.json`
- `--workspace .`
- `--env-file .env`
- `--once` (run one cycle and exit)
- `--autonomous` (run cycles continuously without user prompts)
- `--stream` / `--no-stream`

## Run in Docker (recommended)

This keeps the agent isolated from your host OS while still allowing repo edits through a bind mount.

1. Build the image:
```bash
docker compose build
```
2. Run one task:
```bash
docker compose run --rm agent --goal "Create a small improvement and restart safely"
```

If your host/container UID/GID differ, set these before running compose:
```bash
export GOOD_BOT_DOCKER_UID=$(id -u)
export GOOD_BOT_DOCKER_GID=$(id -g)
```

The compose service:
- Mounts this repository to `/workspace`.
- Stores runtime state in `/tmp/good_bot` inside the container.
- Drops Linux capabilities.
- Enables `no-new-privileges`.
- Applies basic PID and memory limits.

## Git Commit/Push On Restart

After the restart handshake succeeds, the current instance now performs git sync before exiting:
1. `git add -A`
2. `git commit` (only when there are changes)
3. `git push`
4. terminate current process

If commit/push fails, termination is skipped and the current instance stays alive.

## Startup GitHub Token Check

When PAT auth is configured, startup runs `git ls-remote` against the target repo before any agent work begins.
- Enabled when `GOOD_BOT_GIT_AUTO_PUSH=true`, `GOOD_BOT_GIT_AUTH_CHECK=true`, and `GOOD_BOT_GITHUB_TOKEN` is set.
- If validation fails, process exits early with an error.

## Environment variables

Required:

- `OPENROUTER_API_KEY`

Optional:

- `OPENROUTER_MODEL` (default: `openrouter/auto`)
- `OPENROUTER_BASE_URL` (default: `https://openrouter.ai/api/v1`)
- `GOOD_BOT_MAX_STEPS` (default: `0`, meaning unbounded)
- `GOOD_BOT_HISTORY_EVENTS` (default: `50`)
- `GOOD_BOT_STATE_PATH` (default: `.good_bot/state.json`)
- `GOOD_BOT_RUNTIME_DIR` (default: `.good_bot/runtime`)
- `GOOD_BOT_WORKSPACE` (default: `.`)
- `GOOD_BOT_FREEZE_CODE` (default: `true`)
- `GOOD_BOT_STREAM_EVENTS` (default: `true`)
- `GOOD_BOT_AUTONOMOUS` (default: `false`)
- `GOOD_BOT_AUTONOMOUS_PAUSE_SECONDS` (default: `1.0`)
- `GOOD_BOT_COMMAND_TIMEOUT_SECONDS` (default: `120`)
- `GOOD_BOT_MAX_OUTPUT_CHARS` (default: `8000`)
- `GOOD_BOT_MAX_RESTARTS` (default: `3`)
- `GOOD_BOT_GIT_AUTO_PUSH` (default: `true`)
- `GOOD_BOT_GIT_AUTH_CHECK` (default: `true`)
- `GOOD_BOT_GIT_REMOTE` (default: `origin`)
- `GOOD_BOT_GIT_BRANCH` (default: current branch)
- `GOOD_BOT_GIT_COMMIT_PREFIX` (default: `good-bot`)
- `GOOD_BOT_GIT_AUTHOR_NAME` (optional)
- `GOOD_BOT_GIT_AUTHOR_EMAIL` (optional)
- `GOOD_BOT_GITHUB_TOKEN` (optional PAT; preferred over passwords)
- `GOOD_BOT_GITHUB_REPO` (required with token, format `owner/repo`)

## GitHub auth recommendation

- Do not use GitHub username/password for git push. GitHub removed password auth for git operations.
- Best options:
  - SSH key in container (`git@github.com:owner/repo.git` remote).
  - Fine-grained PAT in `GOOD_BOT_GITHUB_TOKEN` with `GOOD_BOT_GITHUB_REPO`.

### Contributor token setup (non-owner)

1. Contributor creates a token in their own GitHub account:
   - `Settings -> Developer settings -> Personal access tokens`.
2. Prefer a fine-grained token scoped to the target repo.
3. Grant at least repository permission `Contents: Read and write`.
4. If the repo is in an organization with PAT approval policy, request org admin approval.
5. Set in `.env`:
   - `GOOD_BOT_GITHUB_TOKEN=...`
   - `GOOD_BOT_GITHUB_REPO=owner/repo`

If fine-grained PAT cannot be used for that contributor access model, use SSH auth.

## `GOOD_BOT_MAX_STEPS` behavior

- `0` or negative: unbounded agent loop. The model decides when to return a final response.
- Positive integer: hard cap on model/action steps for each cycle.
- After a final response, the CLI stays alive and prompts for next instruction.

## History behavior

- All events are persisted in state.
- Prompt context sent to the model uses a configurable recent window:
  - `GOOD_BOT_HISTORY_EVENTS=50` by default
  - set `<=0` to include all persisted events

## Code freeze behavior

- By default (`GOOD_BOT_FREEZE_CODE=true`), process startup creates a snapshot copy of `src/good_bot` and re-execs from that snapshot.
- This prevents the running process from importing newly modified framework files mid-run.
- On restart, the child process creates a new snapshot, so new code is picked up only at process boundaries.

## Development tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -p "test_*.py"
```

## Notes

- Keep `.env` local and do not commit real API keys.
- The agent can execute shell commands requested by the model; run it only in trusted workspaces.
