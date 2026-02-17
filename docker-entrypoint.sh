#!/bin/sh
set -eu

IMAGE_REPO_PATH="${GOOD_BOT_IMAGE_REPO_PATH:-/opt/good-bot-seed}"
RUNTIME_REPO_PATH="${GOOD_BOT_REPO_ROOT:-/workspace/repo}"
ENV_FILE_PATH="${GOOD_BOT_ENV_FILE:-/run/config/good_bot.env}"

log() {
    printf '[entrypoint] %s\n' "$*" >&2
}

is_true() {
    value="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
    case "${value}" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}

ensure_runtime_repo() {
    if [ -d "${RUNTIME_REPO_PATH}/.git" ]; then
        return
    fi
    if [ ! -d "${IMAGE_REPO_PATH}/.git" ]; then
        log "Missing seed git repository at ${IMAGE_REPO_PATH}"
        exit 2
    fi

    mkdir -p "$(dirname "${RUNTIME_REPO_PATH}")"
    log "Cloning internal seed repository into ${RUNTIME_REPO_PATH}"
    git clone --no-hardlinks "${IMAGE_REPO_PATH}" "${RUNTIME_REPO_PATH}"

    remote_url="${GOOD_BOT_REPO_URL:-}"
    if [ -z "${remote_url}" ]; then
        remote_url="$(git -C "${IMAGE_REPO_PATH}" config --get remote.origin.url || true)"
    fi
    if [ -n "${remote_url}" ]; then
        git -C "${RUNTIME_REPO_PATH}" remote set-url origin "${remote_url}"
    fi

    branch="${GOOD_BOT_GIT_BRANCH:-}"
    if [ -n "${branch}" ]; then
        if git -C "${RUNTIME_REPO_PATH}" show-ref --verify --quiet "refs/heads/${branch}"; then
            git -C "${RUNTIME_REPO_PATH}" checkout "${branch}" >/dev/null 2>&1 || true
        elif git -C "${RUNTIME_REPO_PATH}" show-ref --verify --quiet "refs/remotes/origin/${branch}"; then
            git -C "${RUNTIME_REPO_PATH}" checkout -b "${branch}" "origin/${branch}" >/dev/null 2>&1 || true
        fi
    fi
}

configure_origin_with_token_if_enabled() {
    if ! is_true "${GOOD_BOT_GIT_SET_REMOTE_WITH_TOKEN:-false}"; then
        return
    fi
    if [ ! -d "${RUNTIME_REPO_PATH}/.git" ]; then
        return
    fi
    if [ -z "${GOOD_BOT_GITHUB_TOKEN:-}" ] || [ -z "${GOOD_BOT_GITHUB_REPO:-}" ]; then
        log "Skipping tokenized origin: GOOD_BOT_GITHUB_TOKEN and GOOD_BOT_GITHUB_REPO are required."
        return
    fi
    token_remote="https://x-access-token:${GOOD_BOT_GITHUB_TOKEN}@github.com/${GOOD_BOT_GITHUB_REPO}.git"
    git -C "${RUNTIME_REPO_PATH}" remote set-url origin "${token_remote}"
    log "Configured origin to token-authenticated HTTPS URL."
}

ensure_runtime_repo
configure_origin_with_token_if_enabled

export GOOD_BOT_WORKSPACE="${GOOD_BOT_WORKSPACE:-${RUNTIME_REPO_PATH}}"
export PYTHONPATH="${RUNTIME_REPO_PATH}/src"

cd "${RUNTIME_REPO_PATH}"

has_env_flag=0
for arg in "$@"; do
    if [ "${arg}" = "--env-file" ]; then
        has_env_flag=1
        break
    fi
done

if [ "${has_env_flag}" -eq 1 ] || [ ! -f "${ENV_FILE_PATH}" ]; then
    exec python -m good_bot "$@"
fi

exec python -m good_bot --env-file "${ENV_FILE_PATH}" "$@"
