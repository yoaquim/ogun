"""og's config folder: config.toml, read by settings.py, and beside it the user's
own files, each named here. Each may be a link to a file kept
elsewhere. One that's missing means none; one that can't be parsed stops og
(settings.Unreadable), never skipped."""

import json
from pathlib import Path

from ogun.core import log, settings

# each file, and what it's for: the message a command that needs one gives when it's missing
NAMED = {
    "registry.json": "the repos og knows: their owners, mounts, grants and MCP servers",
    "marketplaces.json": "the plugin marketplaces this Mac's sandboxes mount",
    "templates": "the recipes og builds sandbox images from",
    "baseline.env": "the network baseline every sandbox gets, in place of og's own",
    "appa.lock": "the OpenAPPA release sandboxes install, by version and SHA-256",
    "profile": "which [profiles.<name>] of config.toml this Mac uses (OG_PROFILE wins)",
}


_said: set[str] = set()


def once(key: str, msg: str) -> None:
    """A note about a setting left unset, said once a run, however often it's asked."""
    if key not in _said:
        _said.add(key)
        log.note(msg, err=True)


def profiles_of(x: dict) -> list:
    """The og profiles a registry or marketplace entry names (`profiles`)."""
    v = x.get("profiles")
    return v if isinstance(v, list) else []


def label() -> str:
    """This Mac's profile name: the label the registry's `profiles` lists, MCP
    servers, marketplaces and the default template match. "" with no profile
    chosen, said once: then none of those applies anywhere."""
    p = settings.profile()
    if not p:
        once("profile", "no og profile chosen (OG_PROFILE, or ~/.config/ogun/profile): "
                        "no per-profile grant, MCP server, marketplace or template applies")
    return p


def folder() -> Path:
    return settings.file().parent


def file(name: str) -> Path:
    if name not in NAMED:
        raise ValueError(f"{name} isn't a file og's config folder holds")
    return folder() / name


def missing(cmd: str, name: str, where: Path | None = None) -> None:
    """A command needs the file and it isn't there: which, where og looked (where,
    when a setting points elsewhere), and what it's for."""
    log.err(f"{cmd}: no {name} at {log.path(where or file(name))} ({NAMED[name]})")


def unreadable(name: str, why: str) -> settings.Unreadable:
    return settings.Unreadable(f"{log.path(file(name))} {why}; fix it, or remove it to go without")


def read_text(name: str) -> str | None:
    """The file's text; None when it's missing (a link to nothing too). One that's
    there but can't be read as text (a folder, no permission, not UTF-8) stops og."""
    try:
        return file(name).read_text()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        raise unreadable(name, f"can't be read ({getattr(e, 'strerror', None) or e})") from None


def read_json(name: str) -> dict | None:
    """The file as a JSON object; None when it's missing (a link to nothing too)."""
    text = read_text(name)
    if text is None:
        return None
    try:
        d = json.loads(text)
    except ValueError as e:
        raise unreadable(name, f"isn't valid JSON ({e})") from None
    if not isinstance(d, dict):
        raise unreadable(name, "isn't a JSON object")
    return d
