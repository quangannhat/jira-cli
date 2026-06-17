import click

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


if __name__ == "__main__":
    main()
