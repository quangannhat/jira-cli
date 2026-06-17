import os
import shlex
import subprocess
import tempfile

import click

from jira_cli import template
from jira_cli.client import JiraClient, JiraApiError
from jira_cli.config import ConfigError, load_config, save_config


def get_client() -> JiraClient:
    try:
        cfg = load_config()
    except ConfigError as e:
        raise click.ClickException(str(e))
    return JiraClient(cfg["base_url"], cfg["email"], cfg["api_token"])


@click.group()
def main():
    """CLI tool to create, edit, and search Jira tickets."""


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


@main.command()
@click.argument("jql")
@click.option("--max", "-m", "max_results", default=25, help="Max number of results")
def search(jql, max_results):
    """Search tickets using JQL, e.g. 'project = PROJ AND status = \"To Do\"'."""
    client = get_client()
    try:
        issues = client.search_issues(jql, max_results)
    except JiraApiError as e:
        raise click.ClickException(str(e))
    if not issues:
        click.echo("No issues found.")
        return
    for issue in issues:
        fields = issue["fields"]
        assignee = fields.get("assignee") or {}
        click.echo(
            f"{issue['key']:<12} [{fields['status']['name']:<12}] "
            f"{fields['summary'][:60]:<60} ({assignee.get('displayName', 'Unassigned')})"
        )


@main.command()
def projects():
    """List all Jira projects you can access (key and name)."""
    client = get_client()
    try:
        projs = client.list_projects()
    except JiraApiError as e:
        raise click.ClickException(str(e))
    if not projs:
        click.echo("No projects found.")
        return
    for p in sorted(projs, key=lambda p: p["key"]):
        click.echo(f"{p['key']:<10} {p['name']}")


@main.command()
def new():
    """Interactively create a ticket: pick a project, edit a template, confirm."""
    client = get_client()
    try:
        projs = sorted(client.list_projects(), key=lambda p: p["key"])
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
        issue_types = client.list_issue_types(project["key"])
    except JiraApiError:
        issue_types = []
    try:
        assignees = client.list_assignable_users(project["key"])
    except JiraApiError:
        assignees = []
    try:
        statuses = client.list_statuses(project["key"])
    except JiraApiError:
        statuses = []
    try:
        priorities = client.list_priorities()
    except JiraApiError:
        priorities = []
    try:
        labels = client.list_labels()
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


@main.command()
def update():
    """Interactively edit a ticket: pick a project and issue, edit a template, confirm."""
    client = get_client()
    try:
        projs = sorted(client.list_projects(), key=lambda p: p["key"])
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
        assignees = client.list_assignable_users(project["key"])
    except JiraApiError as e:
        raise click.ClickException(str(e))
    try:
        statuses = client.get_transitions(issue_key)
    except JiraApiError:
        statuses = []
    try:
        priorities = client.list_priorities()
    except JiraApiError:
        priorities = []
    try:
        labels = client.list_labels()
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


if __name__ == "__main__":
    main()
