import re

_HEADER_RE = re.compile(r"^(Summary|Assignee|Priority|Labels):\s*(.*)$", re.IGNORECASE)


def build_template(project_key: str, project_name: str, assignees: list[dict] | None = None) -> str:
    assignee_block = "# Assignee: leave blank for unassigned.\n"
    if assignees:
        assignee_block += "# Available assignees for this project:\n"
        for user in assignees:
            email = user.get("emailAddress")
            label = f"{user['displayName']} <{email}>" if email else user["displayName"]
            assignee_block += f"#   {label}\n"

    return f"""# New ticket in project: {project_key} - {project_name}
# Lines starting with '#' are comments and are stripped before parsing.
# Fill in the fields below, then save and quit.

Summary:
{assignee_block}Assignee:
Priority:
Labels:

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

    fields = {"summary": "", "assignee": "", "priority": "", "labels": []}
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
