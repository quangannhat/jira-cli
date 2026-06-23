import re
from collections import defaultdict

_HEADER_RE = re.compile(r"^(Summary|Type|Assignee|Priority|Labels|Status):\s*(.*)$", re.IGNORECASE)
_ACTIONS_RE = re.compile(r"^Actions:\s*(.*)$", re.IGNORECASE)
_SEARCH_PLAIN_FIELD_RE = re.compile(r"^(Text|Max results):\s*(.*)$", re.IGNORECASE)
_SEARCH_SECTION_RE = re.compile(r"^##\s+(.+)$")
_SEARCH_SECTION_KEYS = [
    ("type", "type"),
    ("status", "statuses"),
    ("assignee", "assignee"),
    ("priority", "priority"),
    ("labels", "labels"),
    ("order by", "order_by"),
]
SEARCH_ORDER_BY_OPTIONS = [
    ("Updated, newest first", "updated DESC"),
    ("Updated, oldest first", "updated ASC"),
    ("Created, newest first", "created DESC"),
    ("Created, oldest first", "created ASC"),
]


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


def build_attachment_placement_template(description: str, attachments: list[dict]) -> str:
    """Template for repositioning attachment references within a description.

    Each attachment gets a numbered {{n}} token; the user moves the token to wherever
    in the text they want that attachment mentioned, then `resolve_attachment_placements`
    turns it into a plain-text reference.
    """
    token_lines = "\n".join(f"#   {{{{{i}}}}} -> {a['filename']}" for i, a in enumerate(attachments, start=1))
    return f"""# Position attachments in the description below by inserting their token wherever
# you want them mentioned. Available attachment tokens:
{token_lines}
# Lines starting with '#' are comments and are stripped before parsing.
# Save and quit when done.

{description}
"""


def resolve_attachment_placements(text: str, attachments: list[dict]) -> str:
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#")).strip()
    for i, attachment in enumerate(attachments, start=1):
        body = body.replace(f"{{{{{i}}}}}", f"[Attached: {attachment['filename']}]")
    return body


def _checkbox_section(title: str, options: list[str]) -> str:
    if not options:
        return f"## {title}\n#   (no options available)\n"
    option_lines = "\n".join(f"#   {opt}" for opt in options)
    return f"## {title}\n{option_lines}\n"


def build_search_template(
    project_key: str | None,
    project_name: str | None,
    assignees: list[dict] | None = None,
    statuses: list[str] | None = None,
    priorities: list[str] | None = None,
    labels: list[str] | None = None,
    issue_types: list[str] | None = None,
    max_results: int = 25,
) -> str:
    assignee_labels = ["Unassigned"] + [
        f"{u['displayName']} <{u['emailAddress']}>" if u.get("emailAddress") else u["displayName"]
        for u in (assignees or [])
    ]
    order_by_labels = [label for label, _ in SEARCH_ORDER_BY_OPTIONS]

    header = (
        f"# Search filter for project: {project_key} - {project_name}"
        if project_key
        else "# Search filter (no project selected, applies across all projects)"
    )

    return f"""{header}
# Lines starting with '#' are comments and are stripped before parsing.
# To apply a filter, delete the leading '#   ' from the option(s) you want below so the
# line is no longer commented out. You can uncomment more than one option in a section
# (matches any of them). Leave a whole section commented out to skip filtering on it.

{_checkbox_section("Type", issue_types or [])}
{_checkbox_section("Status", statuses or [])}
{_checkbox_section("Assignee", assignee_labels)}
{_checkbox_section("Priority", priorities or [])}
{_checkbox_section("Labels", labels or [])}
{_checkbox_section("Order by (pick one)", order_by_labels)}
# Text contains: only tickets whose summary or description contain this text. Optional.
Text:
# Max results: leave blank for {max_results}.
Max results:
"""


def parse_search_template(text: str) -> dict:
    fields = {"type": [], "statuses": [], "assignee": [], "priority": [], "labels": [], "order_by": []}
    text_value = ""
    max_results_raw = ""
    current_section = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        section_match = _SEARCH_SECTION_RE.match(line)
        if section_match:
            header_text = section_match.group(1).lower()
            current_section = next(
                (key for prefix, key in _SEARCH_SECTION_KEYS if header_text.startswith(prefix)), None
            )
            continue

        plain_match = _SEARCH_PLAIN_FIELD_RE.match(line)
        if plain_match:
            current_section = None
            key, value = plain_match.group(1).lower(), plain_match.group(2).strip()
            if key == "max results":
                max_results_raw = value
            else:
                text_value = value
            continue

        if line.startswith("#"):
            continue

        if current_section is not None:
            fields[current_section].append(line)

    if max_results_raw:
        if not max_results_raw.isdigit() or int(max_results_raw) < 1:
            raise ValueError(f"'{max_results_raw}' is not a valid max results value")
        max_results = int(max_results_raw)
    else:
        max_results = None

    fields["text"] = text_value
    fields["max_results"] = max_results
    return fields


def resolve_choice(value: str, options: list[str]) -> str:
    """Resolve a field value that may be a 1-based index into `options`, or pass through free text."""
    if value.isdigit():
        idx = int(value)
        if 1 <= idx <= len(options):
            return options[idx - 1]
        raise ValueError(f"'{value}' is not a valid option number (1-{len(options)})")
    return value


def build_results_template(issues: list[dict], base_url: str) -> str:
    """List search results with a copyable link under each, plus an Actions field.

    Saving with Actions left as None does nothing further; other actions (e.g. bulk-update)
    trigger a follow-up template.
    """
    lines = [
        "# Actions: leave as None to do nothing, or type an action below and save.",
        "# Available actions: bulk-update",
        "Actions: None",
        "",
        "# Matching tickets. Each ticket is followed by a link you can copy.",
    ]
    for issue in issues:
        fields = issue["fields"]
        assignee = fields.get("assignee") or {}
        lines.append(
            f"# {issue['key']:<12} [{fields['status']['name']:<12}] "
            f"{fields['summary'][:60]} ({assignee.get('displayName', 'Unassigned')})"
        )
        lines.append(f"{base_url}/browse/{issue['key']}")
    return "\n".join(lines) + "\n"


def parse_results_template(text: str) -> str | None:
    """Pull out the Actions field. Returns None if left blank or "None"."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ACTIONS_RE.match(stripped)
        if match:
            value = match.group(1).strip()
            return value if value and value.lower() != "none" else None
    return None


def build_bulk_update_template(issues: list[dict], available_statuses: list[str]) -> str:
    """Group matching tickets under a header for every available status, including statuses
    with no matching tickets right now.

    To change a ticket's status, cut its line and paste it under a different '## Status'
    header. Tickets left under their original header are left alone.
    """
    groups = defaultdict(list)
    for issue in issues:
        groups[issue["fields"]["status"]["name"]].append(issue)

    all_statuses = list(available_statuses)
    for status in groups:
        if status not in all_statuses:
            all_statuses.append(status)

    lines = [
        "# Bulk update — every available status has a header below, even ones with no",
        "# matching tickets right now. To change a ticket's status, cut its line and paste it",
        "# under a different '## Status' header. Tickets left in place are left alone.",
    ]
    for status in all_statuses:
        lines.append("")
        lines.append(f"## {status}")
        for issue in groups.get(status, []):
            lines.append(f"{issue['key']:<12} {issue['fields']['summary'][:60]}")
    return "\n".join(lines) + "\n"


_BULK_HEADER_RE = re.compile(r"^##\s+(.+)$")


def parse_bulk_update_template(text: str) -> dict[str, str]:
    """Return {issue_key: status} for every ticket found, based on which '## Status' section
    it currently appears under. Comparing against each ticket's original status is the
    caller's responsibility.
    """
    positions: dict[str, str] = {}
    current_status = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        header_match = _BULK_HEADER_RE.match(line)
        if header_match:
            current_status = header_match.group(1).strip()
            continue

        if line.startswith("#"):
            continue

        if current_status is None:
            continue
        issue_key = line.split()[0]
        positions[issue_key] = current_status

    return positions
