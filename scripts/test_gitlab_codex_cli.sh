#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/test_gitlab_codex_cli.sh --pr-url <gitlab_mr_url> [options]

Options:
  --pr-url <url>         GitLab merge request URL to test. Required.
  --gitlab-url <url>     GitLab base URL. Defaults to the scheme + host from --pr-url.
  --gitlab-token <token> GitLab personal access token. Falls back to env.
  --commands <list>      Comma-separated commands to run. Default: review,describe,improve
  --model <model>        Model passed to PR-Agent/Codex backend. Default: gpt-5.4
  --auth-type <type>     GitLab auth type: oauth_token or private_token. Default: oauth_token
  --ssl-verify <value>   true, false, or a CA bundle path. Optional.
  --publish <bool>       Whether PR-Agent should publish comments. Default: true
  --python <path>        Python interpreter to use. Defaults to ./.venv/bin/python if present.
  -h, --help             Show this help.

Environment fallbacks:
  GITLAB__PERSONAL_ACCESS_TOKEN / GITLAB_PERSONAL_ACCESS_TOKEN
  GITLAB__URL / GITLAB_URL
  GITLAB__AUTH_TYPE / GITLAB_AUTH_TYPE
  GITLAB__SSL_VERIFY / GITLAB_SSL_VERIFY
  CODEX_HOME

Examples:
  scripts/test_gitlab_codex_cli.sh \
    --pr-url "https://gitlab.example.com/group/project/-/merge_requests/123"

  scripts/test_gitlab_codex_cli.sh \
    --pr-url "https://gitlab.example.com/group/project/-/merge_requests/123" \
    --commands review \
    --auth-type private_token \
    --ssl-verify false
EOF
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

derive_gitlab_url() {
  local pr_url="$1"
  python3 - "$pr_url" <<'PY'
from urllib.parse import urlsplit
import sys

parsed = urlsplit(sys.argv[1])
if not parsed.scheme or not parsed.netloc:
    raise SystemExit(1)
print(f"{parsed.scheme}://{parsed.netloc}")
PY
}

PR_URL=""
GITLAB_URL="${GITLAB__URL:-${GITLAB_URL:-}}"
GITLAB_TOKEN="${GITLAB__PERSONAL_ACCESS_TOKEN:-${GITLAB_PERSONAL_ACCESS_TOKEN:-}}"
COMMANDS="review,describe,improve"
MODEL="${CONFIG__MODEL:-gpt-5.4}"
AUTH_TYPE="${GITLAB__AUTH_TYPE:-${GITLAB_AUTH_TYPE:-oauth_token}}"
SSL_VERIFY="${GITLAB__SSL_VERIFY:-${GITLAB_SSL_VERIFY:-}}"
PUBLISH_OUTPUT="${CONFIG__PUBLISH_OUTPUT:-true}"
PYTHON_BIN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pr-url)
      PR_URL="${2:-}"
      shift 2
      ;;
    --gitlab-url)
      GITLAB_URL="${2:-}"
      shift 2
      ;;
    --gitlab-token)
      GITLAB_TOKEN="${2:-}"
      shift 2
      ;;
    --commands)
      COMMANDS="${2:-}"
      shift 2
      ;;
    --model)
      MODEL="${2:-}"
      shift 2
      ;;
    --auth-type)
      AUTH_TYPE="${2:-}"
      shift 2
      ;;
    --ssl-verify)
      SSL_VERIFY="${2:-}"
      shift 2
      ;;
    --publish)
      PUBLISH_OUTPUT="${2:-}"
      shift 2
      ;;
    --python)
      PYTHON_BIN="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$PR_URL" ]]; then
  echo "--pr-url is required." >&2
  usage
  exit 1
fi

require_command codex
require_command python3

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    PYTHON_BIN="python3"
  fi
fi

if [[ -z "$GITLAB_URL" ]]; then
  if ! GITLAB_URL="$(derive_gitlab_url "$PR_URL")"; then
    echo "Failed to derive GitLab base URL from PR URL. Pass --gitlab-url explicitly." >&2
    exit 1
  fi
fi

if [[ -z "$GITLAB_TOKEN" ]]; then
  echo "Missing GitLab token. Pass --gitlab-token or set GITLAB__PERSONAL_ACCESS_TOKEN." >&2
  exit 1
fi

if [[ "$AUTH_TYPE" != "oauth_token" && "$AUTH_TYPE" != "private_token" ]]; then
  echo "--auth-type must be 'oauth_token' or 'private_token'." >&2
  exit 1
fi

echo "Checking Codex authentication..."
codex login status

IFS=',' read -r -a command_list <<<"$COMMANDS"
if [[ ${#command_list[@]} -eq 0 ]]; then
  echo "No commands selected." >&2
  exit 1
fi

echo "Running PR-Agent against:"
echo "  PR URL:         $PR_URL"
echo "  GitLab URL:     $GITLAB_URL"
echo "  Commands:       $COMMANDS"
echo "  Model:          $MODEL"
echo "  Auth type:      $AUTH_TYPE"
echo "  Publish output: $PUBLISH_OUTPUT"
echo "  Python:         $PYTHON_BIN"
if [[ -n "${CODEX_HOME:-}" ]]; then
  echo "  CODEX_HOME:     ${CODEX_HOME}"
fi
if [[ -n "$SSL_VERIFY" ]]; then
  echo "  SSL verify:     $SSL_VERIFY"
fi

for raw_command in "${command_list[@]}"; do
  command_name="$(echo "$raw_command" | xargs)"
  if [[ -z "$command_name" ]]; then
    continue
  fi

  echo
  echo "=== Running $command_name ==="
  env_args=(
    "PYTHONPATH=."
    "CONFIG__AI_HANDLER=codex_cli"
    "CONFIG__GIT_PROVIDER=gitlab"
    "CONFIG__MODEL=$MODEL"
    "CONFIG__PUBLISH_OUTPUT=$PUBLISH_OUTPUT"
    "GITLAB__URL=$GITLAB_URL"
    "GITLAB__PERSONAL_ACCESS_TOKEN=$GITLAB_TOKEN"
    "GITLAB__AUTH_TYPE=$AUTH_TYPE"
  )
  if [[ -n "$SSL_VERIFY" ]]; then
    env_args+=("GITLAB__SSL_VERIFY=$SSL_VERIFY")
  fi

  env "${env_args[@]}" "$PYTHON_BIN" -m pr_agent.cli --pr_url="$PR_URL" "$command_name"
done

echo
echo "Completed GitLab MR smoke test."
