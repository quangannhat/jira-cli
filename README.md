# jira-cli

CLI tool to create, edit, and search Jira Cloud tickets via the REST API v3.

## Setup

```bash
uv sync
uv run jira-cli configure
```

`configure` prompts for your Jira base URL (e.g. `https://yourcompany.atlassian.net`),
account email, and an API token (create one at
https://id.atlassian.com/manage-profile/security/api-tokens). Credentials are saved to
`~/.config/jira-cli/config.json` (mode 0600).

Alternatively, set environment variables instead of running `configure`:

```bash
export JIRA_BASE_URL=https://yourcompany.atlassian.net
export JIRA_EMAIL=you@company.com
export JIRA_API_TOKEN=your-api-token
```

## Usage

```bash
# Create a ticket
uv run jira-cli create -p PROJ -s "Fix login bug" -d "Steps to reproduce..." -t Bug -a you@company.com

# Edit a ticket
uv run jira-cli edit PROJ-123 -s "New summary" --status "In Progress"

# Show a ticket
uv run jira-cli show PROJ-123

# Search with JQL
uv run jira-cli search 'project = PROJ AND status = "To Do"'
```
