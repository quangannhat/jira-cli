import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("JIRA_CLI_CONFIG_DIR", Path.home() / ".config" / "jira-cli"))
CONFIG_FILE = CONFIG_DIR / "config.json"


class ConfigError(Exception):
    pass


def load_config() -> dict:
    config = {}
    if CONFIG_FILE.exists():
        config = json.loads(CONFIG_FILE.read_text())

    config["base_url"] = os.environ.get("JIRA_BASE_URL", config.get("base_url"))
    config["email"] = os.environ.get("JIRA_EMAIL", config.get("email"))
    config["api_token"] = os.environ.get("JIRA_API_TOKEN", config.get("api_token"))

    missing = [k for k in ("base_url", "email", "api_token") if not config.get(k)]
    if missing:
        raise ConfigError(
            f"Missing Jira config: {', '.join(missing)}. "
            "Run `jira-cli configure` or set JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN."
        )
    config["base_url"] = config["base_url"].rstrip("/")
    return config


def save_config(base_url: str, email: str, api_token: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps({"base_url": base_url.rstrip("/"), "email": email, "api_token": api_token}, indent=2)
    )
    CONFIG_FILE.chmod(0o600)
