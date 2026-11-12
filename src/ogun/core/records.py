"""A sandbox's create record: where it lives, and reading it back. The secret
grants are applied and revoked from it (grants.py), so a change here deserves a
secrets review."""

import json
from pathlib import Path

from ogun.core import paths


def records_dir() -> Path:
    """Where create records each sandbox: og's state dir."""
    return paths.state_dir() / "sandboxes"


def record_file(name: str) -> Path:
    """A sandbox's create record."""
    return records_dir() / f"{name}.json"


def read_record(name: str) -> dict | None:
    """A sandbox's create record, or None when it's missing or unreadable."""
    try:
        r = json.loads(record_file(name).read_text())
    except (OSError, ValueError):
        return None
    return r if isinstance(r, dict) else None
