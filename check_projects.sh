#!/usr/bin/env bash
# Directly queries the Jira project/search endpoint with curl, bypassing the CLI,
# to check whether "no projects found" is a permissions issue or a CLI bug.
#
# Usage:
#   ./check_projects.sh
#
# Reads JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN from the environment,
# falling back to ~/.config/jira-cli/config.json if set there via `jira-cli configure`.

set -euo pipefail

CONFIG_FILE="$HOME/.config/jira-cli/config.json"

if [ -z "${JIRA_BASE_URL:-}" ] && [ -f "$CONFIG_FILE" ]; then
    JIRA_BASE_URL=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['base_url'])")
fi
if [ -z "${JIRA_EMAIL:-}" ] && [ -f "$CONFIG_FILE" ]; then
    JIRA_EMAIL=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['email'])")
fi
if [ -z "${JIRA_API_TOKEN:-}" ] && [ -f "$CONFIG_FILE" ]; then
    JIRA_API_TOKEN=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['api_token'])")
fi

: "${JIRA_BASE_URL:?Set JIRA_BASE_URL or run 'jira-cli configure' first}"
: "${JIRA_EMAIL:?Set JIRA_EMAIL or run 'jira-cli configure' first}"
: "${JIRA_API_TOKEN:?Set JIRA_API_TOKEN or run 'jira-cli configure' first}"

curl -s -u "${JIRA_EMAIL}:${JIRA_API_TOKEN}" \
    "${JIRA_BASE_URL%/}/rest/api/3/project/search" \
    | python3 -m json.tool
