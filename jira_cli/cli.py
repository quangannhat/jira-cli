import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

import click

from jira_cli import cache as cache_module
from jira_cli import picker as picker_module
from jira_cli import template
from jira_cli.client import JiraClient, JiraApiError
from jira_cli.config import ConfigError, load_config, load_raw_config, save_cache_ttl, save_config, save_file_picker


def get_config() -> dict:
    try:
        return load_config()
    except ConfigError as e:
        raise click.ClickException(str(e))


def get_client() -> JiraClient:
    cfg = get_config()
    return JiraClient(cfg["base_url"], cfg["email"], cfg["api_token"])


def _pick_files(cfg: dict) -> list[str]:
    """Run the file picker, retrying on failure until it succeeds or the user gives up."""
    while True:
        try:
            return picker_module.pick_files(cfg)
        except Exception as e:
            click.echo(f"File picker failed: {e}")
            if not click.confirm("Try adding attachments again?", default=True):
                return []


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    """CLI tool to create, edit, and search Jira tickets."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(menu)


@main.command()
@click.option("--base-url", prompt="Jira base URL (e.g. https://yourcompany.atlassian.net)")
@click.option("--email", prompt="Jira account email")
@click.option("--api-token", prompt="Jira API token", hide_input=True)
def configure(base_url, email, api_token):
    """Save Jira credentials to ~/.config/jira-cli/config.json."""
    save_config(base_url, email, api_token)
    click.echo("Configuration saved.")


@main.command()
@click.option("--project", "-p", required=True, help="Project key, e.g. PROJ")
@click.option("--summary", "-s", required=True, help="Issue summary/title")
@click.option("--description", "-d", default=None, help="Issue description")
@click.option("--type", "-t", "issue_type", default="Task", help="Issue type, e.g. Task, Bug, Story")
@click.option("--assignee", "-a", default=None, help="Assignee email or display name")
def create(project, summary, description, issue_type, assignee):
    """Create a new Jira ticket."""
    client = get_client()
    try:
        issue = client.create_issue(project, summary, description, issue_type, assignee)
    except JiraApiError as e:
        raise click.ClickException(str(e))
    click.echo(f"Created {issue['key']}: {client.base_url}/browse/{issue['key']}")


@main.command()
@click.argument("issue_key")
@click.option("--summary", "-s", default=None, help="New summary/title")
@click.option("--description", "-d", default=None, help="New description")
@click.option("--assignee", "-a", default=None, help="New assignee email or display name")
@click.option("--status", default=None, help="Transition to this status, e.g. 'In Progress', 'Done'")
def edit(issue_key, summary, description, assignee, status):
    """Edit an existing Jira ticket."""
    if not any([summary, description, assignee, status]):
        raise click.ClickException("Nothing to update: pass at least one of --summary/--description/--assignee/--status")
    client = get_client()
    try:
        client.edit_issue(issue_key, summary, description, assignee, status)
    except JiraApiError as e:
        raise click.ClickException(str(e))
    click.echo(f"Updated {issue_key}: {client.base_url}/browse/{issue_key}")


@main.command()
@click.argument("issue_key")
def show(issue_key):
    """Show details of a Jira ticket."""
    client = get_client()
    try:
        issue = client.get_issue(issue_key)
    except JiraApiError as e:
        raise click.ClickException(str(e))
    fields = issue["fields"]
    assignee = fields.get("assignee") or {}
    click.echo(f"{issue['key']}: {fields['summary']}")
    click.echo(f"  Status:   {fields['status']['name']}")
    click.echo(f"  Type:     {fields['issuetype']['name']}")
    click.echo(f"  Assignee: {assignee.get('displayName', 'Unassigned')}")
    click.echo(f"  URL:      {client.base_url}/browse/{issue['key']}")


def _build_search_jql(cfg: dict, client: JiraClient, default_max_results: int) -> tuple[str, int] | None:
    """Build a JQL query from a filter template, mirroring the `new`/`update` ticket templates."""
    try:
        projs = sorted(cache_module.cached_fetch(cfg, "projects", client.list_projects), key=lambda p: p["key"])
    except JiraApiError as e:
        raise click.ClickException(str(e))

    project = None
    if projs:
        click.echo("0) Any project")
        for i, p in enumerate(projs, start=1):
            click.echo(f"{i}) {p['key']:<10} {p['name']}")
        choice = click.prompt(
            "Select a project to scope status/assignee options (0 for any)",
            type=click.IntRange(0, len(projs)),
            default=0,
        )
        if choice:
            project = projs[choice - 1]

    issue_types, statuses, assignees = [], [], []
    if project:
        try:
            issue_types = cache_module.cached_fetch(
                cfg, "issue_types", lambda: client.list_issue_types(project["key"]), project_key=project["key"]
            )
        except JiraApiError:
            issue_types = []
        try:
            statuses = cache_module.cached_fetch(
                cfg, "statuses", lambda: client.list_statuses(project["key"]), project_key=project["key"]
            )
        except JiraApiError:
            statuses = []
        try:
            assignees = cache_module.cached_fetch(
                cfg, "assignees", lambda: client.list_assignable_users(project["key"]), project_key=project["key"]
            )
        except JiraApiError:
            assignees = []
    try:
        priorities = cache_module.cached_fetch(cfg, "priorities", client.list_priorities)
    except JiraApiError:
        priorities = []
    try:
        labels = cache_module.cached_fetch(cfg, "labels", client.list_labels)
    except JiraApiError:
        labels = []

    fd, path = tempfile.mkstemp(suffix=".jira.md")
    os.close(fd)
    try:
        with open(path, "w") as f:
            f.write(
                template.build_search_template(
                    project["key"] if project else None,
                    project["name"] if project else None,
                    assignees=assignees,
                    statuses=statuses,
                    priorities=priorities,
                    labels=labels,
                    issue_types=issue_types,
                    max_results=default_max_results,
                )
            )

        editor = shlex.split(os.environ.get("EDITOR", "nvim"))
        subprocess.call(editor + [path])

        with open(path) as f:
            text = f.read()
    finally:
        os.remove(path)

    filters = template.parse_search_template(text)

    def in_clause(field, values):
        return f"{field} in (" + ", ".join(f'"{v}"' for v in values) + ")"

    clauses = []
    if project:
        clauses.append(f"project = {project['key']}")
    if filters["type"]:
        clauses.append(in_clause("issuetype", filters["type"]))
    if filters["statuses"]:
        clauses.append(in_clause("status", filters["statuses"]))
    if filters["assignee"]:
        frags = []
        for a in filters["assignee"]:
            if a.strip().lower() == "unassigned":
                frags.append("assignee is EMPTY")
            else:
                match = re.search(r"<(.+)>$", a)
                frags.append(f'assignee = "{match.group(1) if match else a}"')
        clauses.append("(" + " OR ".join(frags) + ")")
    if filters["priority"]:
        clauses.append(in_clause("priority", filters["priority"]))
    if filters["labels"]:
        clauses.append(in_clause("labels", filters["labels"]))
    if filters["text"]:
        clauses.append(f'text ~ "{filters["text"].replace(chr(34), chr(92) + chr(34))}"')

    if not clauses:
        click.echo("No filters specified.")
        return None

    order_by_jql = dict(template.SEARCH_ORDER_BY_OPTIONS).get(
        filters["order_by"][0] if filters["order_by"] else None, "updated DESC"
    )
    jql = " AND ".join(clauses) + f" ORDER BY {order_by_jql}"
    max_results = filters["max_results"] or default_max_results
    click.echo(f"\nQuery: {jql}")
    if not click.confirm("Run this search?", default=True):
        return None
    return jql, max_results


@main.command()
@click.option("--max", "-m", "max_results", default=25, help="Max number of results")
def search(max_results):
    """Search tickets by building a filter interactively via a template."""
    cfg = get_config()
    client = get_client()
    result = _build_search_jql(cfg, client, max_results)
    if result is None:
        click.echo("Aborted, no search performed.")
        return
    jql, max_results = result
    try:
        issues = client.search_issues(jql, max_results)
    except JiraApiError as e:
        raise click.ClickException(str(e))
    if not issues:
        click.echo("No issues found.")
        return

    fd, path = tempfile.mkstemp(suffix=".jira.md")
    os.close(fd)
    try:
        with open(path, "w") as f:
            f.write(template.build_results_template(issues, client.base_url))

        editor = shlex.split(os.environ.get("EDITOR", "nvim"))
        subprocess.call(editor + [path])

        with open(path) as f:
            text = f.read()
    finally:
        os.remove(path)

    action = template.parse_results_template(text)
    if action is None:
        return

    if action.lower() == "bulk-update":
        project_keys = sorted({issue["key"].split("-")[0] for issue in issues})
        available_statuses = set()
        for pk in project_keys:
            try:
                available_statuses.update(
                    cache_module.cached_fetch(cfg, "statuses", lambda pk=pk: client.list_statuses(pk), project_key=pk)
                )
            except JiraApiError:
                pass

        fd, path = tempfile.mkstemp(suffix=".jira.md")
        os.close(fd)
        try:
            with open(path, "w") as f:
                f.write(template.build_bulk_update_template(issues, sorted(available_statuses)))
            editor = shlex.split(os.environ.get("EDITOR", "nvim"))
            subprocess.call(editor + [path])
            with open(path) as f:
                bulk_text = f.read()
        finally:
            os.remove(path)

        original_status = {issue["key"]: issue["fields"]["status"]["name"] for issue in issues}
        positions = template.parse_bulk_update_template(bulk_text)
        changes = {
            key: (original_status[key], new_status)
            for key, new_status in positions.items()
            if key in original_status and new_status != original_status[key]
        }
        if not changes:
            click.echo("No status changes, nothing to update.")
            return

        click.echo("\nAbout to change:")
        for key, (old_status, new_status) in changes.items():
            click.echo(f"  {key}: {old_status} -> {new_status}")
        if not click.confirm(f"\nApply these {len(changes)} status change(s)?", default=False):
            click.echo("Aborted, no changes applied.")
            return

        succeeded, failed = 0, 0
        for key, (old_status, new_status) in changes.items():
            try:
                client.edit_issue(key, status=new_status)
            except JiraApiError as e:
                click.echo(f"{key}: failed — {e}")
                failed += 1
            else:
                click.echo(f"{key}: updated")
                succeeded += 1
        click.echo(f"\nDone: {succeeded} succeeded, {failed} failed.")
    else:
        click.echo(f"Unknown action '{action}', nothing was done.")


@main.command()
def projects():
    """List all Jira projects you can access (key and name)."""
    cfg = get_config()
    client = JiraClient(cfg["base_url"], cfg["email"], cfg["api_token"])
    try:
        projs = cache_module.cached_fetch(cfg, "projects", client.list_projects)
    except JiraApiError as e:
        raise click.ClickException(str(e))
    if not projs:
        click.echo("No projects found.")
        return
    for p in sorted(projs, key=lambda p: p["key"]):
        click.echo(f"{p['key']:<10} {p['name']}")


@main.group()
def config():
    """Manage jira-cli configuration."""


@config.command("set-file-picker")
@click.argument("command_template", required=False)
def config_set_file_picker(command_template):
    """Set the shell command used to pick files for `attach`.

    Use {output} as a placeholder for a file the picker should write selected paths to,
    one per line, e.g. yazi --chooser-file={output}. Omit the argument to clear the
    setting and fall back to typing paths manually.
    """
    start_dir = ""
    if command_template:
        start_dir = click.prompt("Directory to start the picker in", default="~")
    save_file_picker(command_template or "", start_dir)
    if command_template:
        click.echo(f"File picker set to: {command_template} (starting in {start_dir})")
    else:
        click.echo("File picker cleared; `attach` will prompt for paths manually.")


@main.command()
@click.argument("issue_key")
@click.argument("files", nargs=-1, type=click.Path(exists=True))
def attach(issue_key, files):
    """Attach files to a ticket. Pass file paths directly, or omit them to use the
    configured file picker (see `jira-cli config set-file-picker`)."""
    cfg = get_config()
    client = JiraClient(cfg["base_url"], cfg["email"], cfg["api_token"])

    paths = list(files) if files else _pick_files(cfg)
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        raise click.ClickException(f"File(s) not found: {', '.join(missing)}")
    not_files = [p for p in paths if not Path(p).is_file()]
    if not_files:
        raise click.ClickException(f"Not a file: {', '.join(not_files)}")
    if not paths:
        click.echo("No files to attach.")
        return

    try:
        client.add_attachment(issue_key, paths)
    except JiraApiError as e:
        raise click.ClickException(str(e))
    click.echo(f"Attached {len(paths)} file(s) to {issue_key}: {client.base_url}/browse/{issue_key}")


@main.group()
def cache():
    """Manage the on-disk cache of project metadata (projects, issue types, assignees, statuses, priorities, labels)."""


@cache.command("configure")
def cache_configure():
    """Set per-category cache TTLs, in seconds."""
    current = load_raw_config().get("cache_ttl", {})
    ttl = {}
    for category in cache_module.ALL_CATEGORIES:
        ttl[category] = click.prompt(
            f"TTL for {category} (seconds)", default=current.get(category, cache_module.DEFAULT_TTL), type=int
        )
    save_cache_ttl(ttl)
    click.echo("Cache TTL settings saved.")


@cache.command("clear")
@click.argument("project", required=False)
def cache_clear(project):
    """Clear cached metadata. Pass a project key to clear just that project's cache, or omit to clear everything."""
    removed = cache_module.clear(project)
    if not removed:
        click.echo("Nothing to clear.")
        return
    for path in removed:
        click.echo(f"Removed {path}")


@main.command()
def new():
    """Interactively create a ticket: pick a project, edit a template, confirm."""
    cfg = get_config()
    client = JiraClient(cfg["base_url"], cfg["email"], cfg["api_token"])
    try:
        projs = sorted(cache_module.cached_fetch(cfg, "projects", client.list_projects), key=lambda p: p["key"])
    except JiraApiError as e:
        raise click.ClickException(str(e))
    if not projs:
        click.echo("No projects found.")
        return

    for i, p in enumerate(projs, start=1):
        click.echo(f"{i}) {p['key']:<10} {p['name']}")
    choice = click.prompt("Select a project", type=click.IntRange(1, len(projs)))
    project = projs[choice - 1]

    try:
        issue_types = cache_module.cached_fetch(
            cfg, "issue_types", lambda: client.list_issue_types(project["key"]), project_key=project["key"]
        )
    except JiraApiError:
        issue_types = []
    try:
        assignees = cache_module.cached_fetch(
            cfg, "assignees", lambda: client.list_assignable_users(project["key"]), project_key=project["key"]
        )
    except JiraApiError:
        assignees = []
    try:
        statuses = cache_module.cached_fetch(
            cfg, "statuses", lambda: client.list_statuses(project["key"]), project_key=project["key"]
        )
    except JiraApiError:
        statuses = []
    try:
        priorities = cache_module.cached_fetch(cfg, "priorities", client.list_priorities)
    except JiraApiError:
        priorities = []
    try:
        labels = cache_module.cached_fetch(cfg, "labels", client.list_labels)
    except JiraApiError:
        labels = []

    assignee_options = [u.get("emailAddress") or u["displayName"] for u in assignees]

    fd, path = tempfile.mkstemp(suffix=".jira.md")
    os.close(fd)
    try:
        with open(path, "w") as f:
            f.write(
                template.build_template(
                    project["key"], project["name"], assignees, statuses, priorities, labels, issue_types
                )
            )

        editor = shlex.split(os.environ.get("EDITOR", "nvim"))
        subprocess.call(editor + [path])

        with open(path) as f:
            text = f.read()
    finally:
        os.remove(path)

    try:
        fields = template.parse_template(text)
        if fields["type"]:
            fields["type"] = template.resolve_choice(fields["type"], issue_types)
        if fields["assignee"]:
            fields["assignee"] = template.resolve_choice(fields["assignee"], assignee_options)
        if fields["priority"]:
            fields["priority"] = template.resolve_choice(fields["priority"], priorities)
        if fields["status"]:
            fields["status"] = template.resolve_choice(fields["status"], statuses)
        fields["labels"] = [template.resolve_choice(label, labels) for label in fields["labels"]]
    except ValueError as e:
        raise click.ClickException(str(e))

    click.echo("\nReview ticket:")
    click.echo(f"  Project:     {project['key']}")
    click.echo(f"  Summary:     {fields['summary']}")
    click.echo(f"  Type:        {fields['type'] or 'Task'}")
    click.echo(f"  Assignee:    {fields['assignee'] or '(none)'}")
    click.echo(f"  Priority:    {fields['priority'] or '(none)'}")
    click.echo(f"  Labels:      {', '.join(fields['labels']) or '(none)'}")
    click.echo(f"  Status:      {fields['status'] or '(workflow default)'}")
    click.echo(f"  Description: {fields['description'] or '(none)'}")

    if not click.confirm("\nCreate this ticket?", default=True):
        click.echo("Aborted, ticket not created.")
        return

    try:
        issue = client.create_issue(
            project_key=project["key"],
            summary=fields["summary"],
            description=fields["description"] or None,
            issue_type=fields["type"] or "Task",
            assignee=fields["assignee"] or None,
            priority=fields["priority"] or None,
            labels=fields["labels"] or None,
        )
    except JiraApiError as e:
        raise click.ClickException(str(e))
    click.echo(f"Created {issue['key']}: {client.base_url}/browse/{issue['key']}")

    if fields["status"]:
        try:
            client.transition_issue(issue["key"], fields["status"])
        except JiraApiError as e:
            click.echo(f"Warning: ticket created but could not transition to '{fields['status']}': {e}")

    if click.confirm("\nAdd attachments?", default=False):
        paths = []
        while True:
            picked = _pick_files(cfg)
            not_files = [p for p in picked if not Path(p).is_file()]
            if not_files:
                click.echo(f"Not a file: {', '.join(not_files)}")
                if click.confirm("Try adding attachments again?", default=True):
                    continue
                break
            paths = picked
            break
        if paths:
            try:
                attachments = client.add_attachment(issue["key"], paths)
            except JiraApiError as e:
                click.echo(f"Warning: could not attach files: {e}")
                attachments = []
            else:
                click.echo(f"Attached {len(attachments)} file(s) to {issue['key']}")

            if attachments and click.confirm("\nUpdate description to position these attachments?", default=False):
                fd, path = tempfile.mkstemp(suffix=".jira.md")
                os.close(fd)
                try:
                    with open(path, "w") as f:
                        f.write(template.build_attachment_placement_template(fields["description"], attachments))

                    editor = shlex.split(os.environ.get("EDITOR", "nvim"))
                    subprocess.call(editor + [path])

                    with open(path) as f:
                        text = f.read()
                finally:
                    os.remove(path)

                new_description = template.resolve_attachment_placements(text, attachments)
                try:
                    client.edit_issue(issue["key"], description=new_description)
                except JiraApiError as e:
                    click.echo(f"Warning: could not update description: {e}")
                else:
                    click.echo("Description updated.")


@main.command()
def update():
    """Interactively edit a ticket: pick a project and issue, edit a template, confirm."""
    cfg = get_config()
    client = JiraClient(cfg["base_url"], cfg["email"], cfg["api_token"])
    try:
        projs = sorted(cache_module.cached_fetch(cfg, "projects", client.list_projects), key=lambda p: p["key"])
    except JiraApiError as e:
        raise click.ClickException(str(e))
    if not projs:
        click.echo("No projects found.")
        return

    for i, p in enumerate(projs, start=1):
        click.echo(f"{i}) {p['key']:<10} {p['name']}")
    choice = click.prompt("Select a project", type=click.IntRange(1, len(projs)))
    project = projs[choice - 1]

    try:
        recent_issues = client.search_issues(f"project = {project['key']} ORDER BY updated DESC", max_results=25)
    except JiraApiError as e:
        raise click.ClickException(str(e))

    for i, issue in enumerate(recent_issues, start=1):
        f = issue["fields"]
        click.echo(f"{i}) {issue['key']:<12} [{f['status']['name']:<12}] {f['summary'][:60]}")
    selection = click.prompt("Select an issue number, or type an issue key directly")
    if selection.isdigit() and 1 <= int(selection) <= len(recent_issues):
        issue_key = recent_issues[int(selection) - 1]["key"]
    else:
        issue_key = selection

    try:
        issue = client.get_issue(issue_key)
        issue_types = []  # not editable in this workflow
        assignees = cache_module.cached_fetch(
            cfg, "assignees", lambda: client.list_assignable_users(project["key"]), project_key=project["key"]
        )
    except JiraApiError as e:
        raise click.ClickException(str(e))
    try:
        # Transitions depend on the issue's current status, so they aren't cached.
        statuses = client.get_transitions(issue_key)
    except JiraApiError:
        statuses = []
    try:
        priorities = cache_module.cached_fetch(cfg, "priorities", client.list_priorities)
    except JiraApiError:
        priorities = []
    try:
        labels = cache_module.cached_fetch(cfg, "labels", client.list_labels)
    except JiraApiError:
        labels = []

    assignee_options = [u.get("emailAddress") or u["displayName"] for u in assignees]

    current_fields = issue["fields"]
    current_assignee = current_fields.get("assignee") or {}
    current_priority = current_fields.get("priority") or {}
    prefill = {
        "summary": current_fields["summary"],
        "assignee": current_assignee.get("emailAddress") or current_assignee.get("displayName", ""),
        "priority": current_priority.get("name", ""),
        "labels": ", ".join(current_fields.get("labels", [])),
        "description": template.adf_to_text(current_fields.get("description")),
    }

    fd, path = tempfile.mkstemp(suffix=".jira.md")
    os.close(fd)
    try:
        with open(path, "w") as f:
            f.write(
                template.build_template(
                    project["key"],
                    project["name"],
                    assignees,
                    statuses,
                    priorities,
                    labels,
                    issue_types,
                    prefill=prefill,
                    issue_key=issue_key,
                    current_status=current_fields["status"]["name"],
                )
            )

        editor = shlex.split(os.environ.get("EDITOR", "nvim"))
        subprocess.call(editor + [path])

        with open(path) as f:
            text = f.read()
    finally:
        os.remove(path)

    try:
        fields = template.parse_template(text)
        if fields["assignee"]:
            fields["assignee"] = template.resolve_choice(fields["assignee"], assignee_options)
        if fields["priority"]:
            fields["priority"] = template.resolve_choice(fields["priority"], priorities)
        if fields["status"]:
            fields["status"] = template.resolve_choice(fields["status"], statuses)
        fields["labels"] = [template.resolve_choice(label, labels) for label in fields["labels"]]
    except ValueError as e:
        raise click.ClickException(str(e))

    click.echo("\nReview changes:")
    click.echo(f"  Issue:       {issue_key}")
    click.echo(f"  Summary:     {fields['summary']}")
    click.echo(f"  Assignee:    {fields['assignee'] or '(none)'}")
    click.echo(f"  Priority:    {fields['priority'] or '(none)'}")
    click.echo(f"  Labels:      {', '.join(fields['labels']) or '(none)'}")
    click.echo(f"  Status:      {fields['status'] or '(unchanged)'}")
    click.echo(f"  Description: {fields['description'] or '(none)'}")

    if not click.confirm("\nApply these changes?", default=True):
        click.echo("Aborted, ticket not updated.")
        return

    try:
        client.edit_issue(
            issue_key,
            summary=fields["summary"],
            description=fields["description"] or None,
            assignee=fields["assignee"] or None,
            priority=fields["priority"] or None,
            labels=fields["labels"] or None,
        )
        if fields["status"]:
            client.transition_issue(issue_key, fields["status"])
    except JiraApiError as e:
        raise click.ClickException(str(e))
    click.echo(f"Updated {issue_key}: {client.base_url}/browse/{issue_key}")


def _menu_show(ctx):
    issue_key = click.prompt("Issue key")
    ctx.invoke(show, issue_key=issue_key)


def _menu_search(ctx):
    ctx.invoke(search)


def _menu_attach(ctx):
    issue_key = click.prompt("Issue key")
    raw = click.prompt("File path(s), comma-separated, or leave blank to use the file picker", default="", show_default=False)
    files = tuple(p.strip() for p in raw.split(",") if p.strip())
    ctx.invoke(attach, issue_key=issue_key, files=files)


def _menu_set_file_picker(ctx):
    command_template = click.prompt(
        "File picker command (use {output} as a placeholder), blank to clear", default="", show_default=False
    )
    ctx.invoke(config_set_file_picker, command_template=command_template or None)


def _menu_cache(ctx):
    while True:
        click.echo("\n1) Configure cache TTLs\n2) Clear cache\n3) Back")
        choice = click.prompt("Select", type=click.IntRange(1, 3))
        if choice == 1:
            ctx.invoke(cache_configure)
        elif choice == 2:
            project = click.prompt("Project key to clear (blank for all)", default="", show_default=False)
            ctx.invoke(cache_clear, project=project or None)
        else:
            return


@main.command()
@click.pass_context
def menu(ctx):
    """Interactive menu: pick an action instead of remembering commands."""
    actions = [
        ("New ticket", lambda: ctx.invoke(new)),
        ("Update ticket", lambda: ctx.invoke(update)),
        ("Show ticket", lambda: _menu_show(ctx)),
        ("Search tickets", lambda: _menu_search(ctx)),
        ("Attach files to a ticket", lambda: _menu_attach(ctx)),
        ("List projects", lambda: ctx.invoke(projects)),
        ("Configure Jira credentials", lambda: ctx.invoke(configure)),
        ("Set file picker", lambda: _menu_set_file_picker(ctx)),
        ("Cache settings", lambda: _menu_cache(ctx)),
        ("Exit", None),
    ]

    while True:
        click.echo("\n=== jira-cli ===")
        for i, (label, _) in enumerate(actions, start=1):
            click.echo(f"{i}) {label}")
        choice = click.prompt("Select an action", type=click.IntRange(1, len(actions)), default=len(actions))
        label, action = actions[choice - 1]
        if action is None:
            return
        try:
            action()
        except click.ClickException as e:
            click.echo(f"Error: {e.format_message()}")
        except JiraApiError as e:
            click.echo(f"Error: {e}")
        except click.Abort:
            click.echo("Cancelled.")


if __name__ == "__main__":
    main()
