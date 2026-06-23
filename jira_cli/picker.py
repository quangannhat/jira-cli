import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import click


def pick_files(cfg: dict) -> list[str]:
    """Pick files to attach using the configured file picker, falling back to manual entry
    if none is configured or its binary isn't found on PATH."""
    command_template = cfg.get("file_picker_cmd")
    if command_template:
        binary = shlex.split(command_template)[0]
        if shutil.which(binary):
            start_dir = os.path.expanduser(cfg.get("file_picker_start_dir") or "~")
            paths = _run_picker(command_template, start_dir)
            if paths:
                return paths
            click.echo("File picker returned no files.")
            return []
        click.echo(f"Configured file picker '{binary}' not found on PATH, falling back to manual entry.")
    return _manual_prompt()


def _run_picker(command_template: str, start_dir: str) -> list[str]:
    fd, out_path = tempfile.mkstemp(suffix=".jira-cli-picker")
    os.close(fd)
    try:
        cmd = shlex.split(command_template.format(output=out_path))
        subprocess.call(cmd, cwd=start_dir)
        content = Path(out_path).read_text().strip()
    finally:
        os.remove(out_path)
    return [line for line in content.splitlines() if line.strip()]


def _manual_prompt() -> list[str]:
    raw = click.prompt("Enter file path(s) to attach, comma-separated", default="", show_default=False)
    return [p.strip() for p in raw.split(",") if p.strip()]
