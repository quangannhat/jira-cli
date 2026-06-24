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
# Interactive menu: pick an action from a numbered list instead of remembering commands.
# Running jira-cli with no arguments goes straight to this menu.
uv run jira-cli
uv run jira-cli menu

# List projects you can access
uv run jira-cli projects

# Interactively create a ticket: pick a project, fill in a template in $EDITOR (default nvim),
# review, and confirm. The template lists available work types, assignees, priorities, labels,
# and statuses for the project, numbered so you can type an index instead of the full value.
# After creation, you're asked whether to add attachments (see Attachments below).
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

# Search: pick a project, then fill in a filter template in $EDITOR (uncomment the
# Type/Status/Assignee/Priority/Labels/Order-by options you want, or fill in Text/Max results)
# instead of writing JQL by hand. Results open in another template with a copyable link per
# ticket and an Actions field (e.g. "bulk-update" to change statuses for groups of tickets).
uv run jira-cli search

# Search non-interactively with raw JQL (for scripts/agents) instead of the editor template.
# Add --json for machine-readable output: an array of {key, summary, status, assignee, priority, url}.
uv run jira-cli search --jql 'project = PROJ AND status = "In Progress"' --json

# Attach files to a ticket directly
uv run jira-cli attach PROJ-123 ./screenshot.png ./log.txt

# Attach files via a configured file picker
uv run jira-cli attach PROJ-123
```

## Attachments

`attach` takes file paths directly, or with no paths it launches a file picker to choose
them interactively. The picker isn't tied to any particular tool — configure the shell
command you want via `{output}`, a placeholder for a file the picker should write the
selected paths to, one per line:

```bash
# yazi's --chooser-file writes the chosen path(s) to a file. You'll be prompted for the
# directory the picker should start in (defaults to ~).
uv run jira-cli config set-file-picker "yazi --chooser-file={output}"

# clear it to fall back to typing paths manually
uv run jira-cli config set-file-picker
```

If no picker is configured, or the configured command isn't found on `PATH`, `attach`
falls back to prompting for comma-separated file paths.

After attaching files during `new`, you're asked whether to update the description to
mention them. If yes, the description reopens in `$EDITOR` with a numbered `{{n}}` token
per attachment listed in the comments — move a token to wherever in the text you want
that attachment mentioned, save and quit, and it's replaced with `[Attached: filename]`.

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
