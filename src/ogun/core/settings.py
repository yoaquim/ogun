"""og's settings: ~/.config/ogun/config.toml ($XDG_CONFIG_HOME/ogun/config.toml when
that's set), one `NAME = value` a line, each overridden by an environment variable
of the same name (docs/appendix/flags-and-env.md). A name neither sets reads as "",
and its reader holds the default. A file og can't take as its settings is an error,
never skipped: a misread vault name or a typo'd key would otherwise fall back to the
default without a word.

Profiles: a [profiles.<name>] section holds settings for one profile, over the
shared ones. Which profile is told, never guessed: OG_PROFILE, else the one-line
`profile` file beside config.toml; neither, no profile."""

import os
import re
import tomllib
from pathlib import Path

NAMES = (
    "SBX_VAULT", "SBX_PROJECTS", "SBX_OGUN_DIR", "SBX_EXCHANGE",
    "SBX_TAKE_DEST", "SBX_SSH_DIR", "SBX_SKILLS_STORE", "SBX_HOST_RO_MOUNTS", "SBX_APPA_LOCK",
    "SBX_SECRETS_APPROVED", "SBX_EGRESS_APPROVED", "SBX_RM_PROBE_TIMEOUT", "SBX_RM_BOOT_TIMEOUT",
    "SBX_CLAUDE_UPDATE_TIMEOUT", "SBX_CLAUDE_UPDATE_LOG", "SBX_TOKEN_NAME", "SBX_TOKEN_SUFFIX",
    "SBX_PROVISION", "SBX_SKILLS_DIR", "SBX_GITHUB_OWNERS", "SBX_PROTECTED_KEYS", "SBX_APT_TOOLS",
)
PROFILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


class Unreadable(Exception):
    """The settings file can't be read as og's settings; the message says why."""


def file() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "ogun" / "config.toml"


def _shown(f: Path) -> str:
    home = str(Path.home())
    return "~" + str(f)[len(home):] if str(f).startswith(home + "/") else str(f)


def _settings(d: dict, where: str, prefix: str = "") -> dict[str, str]:
    out = {}
    for k, v in d.items():
        if k not in NAMES:
            raise Unreadable(f"{where}: {prefix}{k} isn't a setting og has (docs/appendix/flags-and-env.md lists them)")
        if isinstance(v, bool) or not isinstance(v, str | int):
            raise Unreadable(f"{where}: {prefix}{k} must be text or a number")
        out[k] = str(v)
    return out


def _parsed() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """The shared settings and each profile's own."""
    # read whole on every lookup: settings are few and read rarely, and a cache
    # would outlive a test's (or a person's) edit to the file
    f = file()
    where = _shown(f)
    try:
        text = f.read_bytes().decode()
    except FileNotFoundError:
        return {}, {}
    except (OSError, UnicodeDecodeError) as e:
        raise Unreadable(f"can't read {where}: {getattr(e, 'strerror', None) or e}") from None
    try:
        d = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise Unreadable(f"{where} isn't valid TOML: {e}") from None
    profs = d.pop("profiles", {})
    if not isinstance(profs, dict):
        raise Unreadable(f"{where}: profiles must be [profiles.<name>] sections")
    out = {}
    for name, p in profs.items():
        if not isinstance(p, dict):
            raise Unreadable(f"{where}: profiles.{name} must be a [profiles.{name}] section of settings")
        out[name] = _settings(p, where, f"profiles.{name}.")
    return _settings(d, where), out


def shared() -> dict[str, str]:
    """config.toml's settings outside every profile."""
    return _parsed()[0]


def profiles() -> dict[str, dict[str, str]]:
    """Every profile config.toml has, each with its own settings."""
    return _parsed()[1]


def profile() -> str:
    """The profile this Mac was told to use, "" for none. One named but missing
    from config.toml stops og: a typo must never read as no profile."""
    v = os.environ.get("OG_PROFILE")
    if not v:
        f = file().parent / "profile"
        try:
            v = f.read_text().strip()
        except FileNotFoundError:
            v = ""
        except (OSError, UnicodeDecodeError) as e:
            raise Unreadable(f"can't read {_shown(f)} (the profile to use): {getattr(e, 'strerror', None) or e}") from None
    if not v:
        return ""
    if not PROFILE_RE.fullmatch(v):
        raise Unreadable(f"'{v}' isn't a profile name (OG_PROFILE, or {_shown(file().parent / 'profile')})")
    if v not in profiles():
        if not file().exists():
            raise Unreadable(f"the profile is {v}, but there's no {_shown(file())}, where [profiles.{v}] goes")
        raise Unreadable(f"the profile is {v}, but {_shown(file())} has no [profiles.{v}]")
    return v


def _read() -> dict[str, str]:
    shared, profs = _parsed()
    p = profile()
    return {**shared, **profs.get(p, {})} if p else shared


def get(name: str) -> str:
    """The setting: its environment variable when that's set and not empty, else
    the file's, else "". The file is read either way, so a broken one always stops og."""
    from_file = _read()
    return os.environ.get(name) or from_file.get(name, "")


def vault() -> str:
    """The 1Password vault og reads its token items and secret grants from: SBX_VAULT,
    else Sandbox."""
    return get("SBX_VAULT") or "Sandbox"


def path(name: str, default: Path) -> Path:
    v = get(name)
    return Path(v).expanduser() if v else default


def seconds(name: str, default: int) -> int:
    v = get(name)
    return int(v) if v.isdigit() else default
