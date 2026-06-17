import re

_HEADER_RE = re.compile(r"^(Summary|Assignee|Priority|Labels|Status):\s*(.*)$", re.IGNORECASE)


def _numbered_block(header: str, items: list[str]) -> str:
    block = f"# {header}\n"
    for i, item in enumerate(items, start=1):
        block += f"#   {i}) {item}\n"
    return block


def build_template(
    project_key: str,
    project_name: str,
    assignees: list[dict] | None = None,
    statuses: list[str] | None = None,
    priorities: list[str] | None = None,
    labels: list[str] | None = None,
) -> str:
    assignee_block = "# Assignee: leave blank for unassigned. Type a number from the list below, or free text.\n"
    if assignees:
        labels_for_assignees = [
            f"{u['displayName']} <{u['emailAddress']}>" if u.get("emailAddress") else u["displayName"]
            for u in assignees
        ]
        assignee_block += _numbered_block("Available assignees for this project:", labels_for_assignees)

    priority_block = "# Priority: leave blank for the default priority. Type a number from the list below, or free text.\n"
    if priorities:
        priority_block += _numbered_block("Available priorities:", priorities)

    status_block = "# Status: leave blank to use the workflow's default starting status. Type a number from the list below, or free text.\n"
    if statuses:
        status_block += _numbered_block("Available statuses for this project:", statuses)

    labels_block = "# Labels: comma-separated. Type numbers from the list below (e.g. 1,3), or free text.\n"
    if labels:
        labels_block += _numbered_block("Existing labels:", labels)

    return f"""# New ticket in project: {project_key} - {project_name}
# Lines starting with '#' are comments and are stripped before parsing.
# Fill in the fields below, then save and quit.

Summary:
{assignee_block}Assignee:
{priority_block}Priority:
{labels_block}Labels:
{status_block}Status:

# Write the description below this line. Multiple lines are fine.
Description:

"""


def parse_template(text: str) -> dict:
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]

    header_lines = lines
    body_lines: list[str] = []
    for i, line in enumerate(lines):
        if line.strip().lower() == "description:":
            header_lines = lines[:i]
            body_lines = lines[i + 1 :]
            break

    fields = {"summary": "", "assignee": "", "priority": "", "status": "", "labels": []}
    for line in header_lines:
        match = _HEADER_RE.match(line.strip())
        if not match:
            continue
        key, value = match.group(1).lower(), match.group(2).strip()
        if key == "labels":
            fields["labels"] = [label.strip() for label in value.split(",") if label.strip()]
        else:
            fields[key] = value

    fields["description"] = "\n".join(body_lines).strip()

    if not fields["summary"]:
        raise ValueError("Summary is required")

    return fields


def resolve_choice(value: str, options: list[str]) -> str:
    """Resolve a field value that may be a 1-based index into `options`, or pass through free text."""
    if value.isdigit():
        idx = int(value)
        if 1 <= idx <= len(options):
            return options[idx - 1]
        raise ValueError(f"'{value}' is not a valid option number (1-{len(options)})")
    return value
