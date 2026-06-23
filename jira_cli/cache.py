import json
import time
from pathlib import Path

from jira_cli.config import CONFIG_DIR

CACHE_DIR = CONFIG_DIR / "cache"

DEFAULT_TTL = 3600

# issue_types/assignees/statuses vary per project; priorities/labels are instance-wide.
PROJECT_SCOPED_CATEGORIES = ["issue_types", "assignees", "statuses"]
GLOBAL_CATEGORIES = ["priorities", "labels", "projects"]
ALL_CATEGORIES = PROJECT_SCOPED_CATEGORIES + GLOBAL_CATEGORIES


def _cache_file(project_key: str | None) -> Path:
    name = f"{project_key}.json" if project_key else "_global.json"
    return CACHE_DIR / name


def _read_cache_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_cache_file(path: Path, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def get_ttl(config: dict, category: str) -> int:
    return config.get("cache_ttl", {}).get(category, DEFAULT_TTL)


def cached_fetch(config: dict, category: str, fetch_fn, project_key: str | None = None):
    """Return cached data for `category` if still within its TTL, else call fetch_fn() and refresh the cache."""
    path = _cache_file(project_key if category in PROJECT_SCOPED_CATEGORIES else None)
    cache = _read_cache_file(path)
    entry = cache.get(category)
    if entry and time.time() - entry["fetched_at"] < get_ttl(config, category):
        return entry["data"]

    data = fetch_fn()
    cache[category] = {"fetched_at": time.time(), "data": data}
    _write_cache_file(path, cache)
    return data


def clear(project_key: str | None = None) -> list[Path]:
    """Remove cache file(s). With a project_key, only that project's file; otherwise every cache file."""
    if not CACHE_DIR.exists():
        return []
    if project_key:
        path = _cache_file(project_key)
        if not path.exists():
            return []
        path.unlink()
        return [path]

    removed = list(CACHE_DIR.glob("*.json"))
    for p in removed:
        p.unlink()
    return removed
