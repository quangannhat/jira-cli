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
# List projects you can access
uv run jira-cli projects

# Interactively create a ticket: pick a project, fill in a template in $EDITOR (default nvim),
# review, and confirm. The template lists available work types, assignees, priorities, labels,
# and statuses for the project, numbered so you can type an index instead of the full value.
uv run jira-cli new

# Create a ticket directly with flags
uv run jira-cli create -p PROJ -s "Fix login bug" -d "Steps to reproduce..." -t Bug -a you@company.com

# Interactively edit a ticket: pick a project and issue, edit a template pre-filled with the
# ticket's current Summary/Assignee/Priority/Labels/Description, review, and confirm. Status
# options are limited to transitions actually reachable from the ticket's current status.
uv run jira-cli update

# Edit a ticket directly with flags
uv run jira-cli edit PROJ-123 -s "New summary" --status "In Progress"

# Show a ticket
uv run jira-cli show PROJ-123

# Search with JQL
uv run jira-cli search 'project = PROJ AND status = "To Do"'
```

## Caching

`projects`, `new`, and `update` cache metadata (projects, issue types, assignees, statuses,
priorities, labels) under `~/.config/jira-cli/cache/` so they don't re-fetch it from the API
every run. Each category defaults to a 1 hour TTL.

```bash
# Customize the TTL (in seconds) per category
uv run jira-cli cache configure

# Clear all cached metadata, or just one project's
uv run jira-cli cache clear
uv run jira-cli cache clear PROJ
```
