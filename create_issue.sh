#!/usr/bin/env bash
# Directly hits POST /rest/api/3/issue with curl, bypassing the CLI, using
# credentials saved by `jira-cli configure` (or env vars if set).
#
# Usage:
#   ./create_issue.sh

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

curl --request POST \
    --url "${JIRA_BASE_URL%/}/rest/api/3/issue" \
    --user "${JIRA_EMAIL}:${JIRA_API_TOKEN}" \
    --header 'Accept: application/json' \
    --header 'Content-Type: application/json' \
    --data '{
    "fields": {
      "project": {
        "key": "ACD"
      },
      "summary": "Tiêu đề task tự động từ API",
      "description": {
        "type": "doc",
        "version": 1,
        "content": [
          {
            "type": "paragraph",
            "content": [
              {
                "type": "text",
                "text": "Đây là nội dung mô tả chi tiết của task."
              }
            ]
          }
        ]
      },
      "issuetype": {
        "name": "Task"
      }
    }
  }' | python3 -m json.tool
