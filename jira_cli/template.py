import re

_HEADER_RE = re.compile(r"^(Summary|Type|Assignee|Priority|Labels|Status):\s*(.*)$", re.IGNORECASE)


def _numbered_block(header: str, items: list[str]) -> str:
    block = f"# {header}\n"
    numbered = [f"{i}) {item}" for i, item in enumerate(items, start=1)]
    per_line = 2 if len(numbered) > 10 else 1
    if per_line == 1:
        for entry in numbered:
            block += f"#   {entry}\n"
        return block

    width = max(len(entry) for entry in numbered)
    for row_start in range(0, len(numbered), per_line):
        row = numbered[row_start : row_start + per_line]
        padded = [entry.ljust(width) for entry in row[:-1]] + [row[-1]]
        block += f"#   {'   '.join(padded)}\n"
    return block


def build_template(
    project_key: str,
    project_name: str,
    assignees: list[dict] | None = None,
    statuses: list[str] | None = None,
    priorities: list[str] | None = None,
    labels: list[str] | None = None,
    issue_types: list[str] | None = None,
    prefill: dict | None = None,
    issue_key: str | None = None,
    current_status: str | None = None,
) -> str:
    prefill = prefill or {}

    def field_line(name: str) -> str:
        value = prefill.get(name.lower(), "")
        return f"{name}: {value}" if value else f"{name}:"

    type_section = ""
    if issue_key is None:
        type_block = (
            "# Type: leave blank for the default work type (Task). Type a number from the list below, or free text.\n"
        )
        if issue_types:
            type_block += _numbered_block("Available work types for this project:", issue_types)
        type_section = f"{type_block}{field_line('Type')}\n"

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
    if issue_key is not None:
        status_block = "# Status: leave blank to keep the current status. Transition to one of the statuses below, or free text.\n"
        if current_status:
            status_block += f"# Current status: {current_status}\n"
    if statuses:
        status_block += _numbered_block("Available statuses:", statuses)

    labels_block = "# Labels: comma-separated. Type numbers from the list below (e.g. 1,3), or free text.\n"
    if labels:
        labels_block += _numbered_block("Existing labels:", labels)

    header = (
        f"# Editing {issue_key} in project: {project_key} - {project_name}"
        if issue_key is not None
        else f"# New ticket in project: {project_key} - {project_name}"
    )

    return f"""{header}
# Lines starting with '#' are comments and are stripped before parsing.
# Fill in the fields below, then save and quit.

{field_line('Summary')}
{type_section}{assignee_block}{field_line('Assignee')}
{priority_block}{field_line('Priority')}
{labels_block}{field_line('Labels')}
{status_block}Status:

# Write the description below this line. Multiple lines are fine.
Description:
{prefill.get('description', '')}
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

    fields = {"summary": "", "type": "", "assignee": "", "priority": "", "status": "", "labels": []}
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


def adf_to_text(adf: dict | None) -> str:
    """Flatten Atlassian Document Format content into plain text, the inverse of JiraClient._adf."""
    if not adf:
        return ""

    def text_of(node: dict) -> str:
        if node.get("type") == "text":
            return node.get("text", "")
        return "".join(text_of(child) for child in node.get("content", []))

    paragraphs = [text_of(node) for node in adf.get("content", [])]
    return "\n".join(paragraphs).strip()


def resolve_choice(value: str, options: list[str]) -> str:
    """Resolve a field value that may be a 1-based index into `options`, or pass through free text."""
    if value.isdigit():
        idx = int(value)
        if 1 <= idx <= len(options):
            return options[idx - 1]
        raise ValueError(f"'{value}' is not a valid option number (1-{len(options)})")
    return value
