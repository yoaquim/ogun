"""og's settings: ~/.config/ogun/config.toml ($XDG_CONFIG_HOME/ogun/config.toml when
that's set), one `name = value` a line, each overridden by the environment variable
OG_<NAME> (docs/appendix/flags-and-env.md). A name neither sets reads as "", and its
reader holds the default. A file og can't take as its settings is an error,
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
    "vault", "projects", "exchange", "take_dest", "token_name", "token_suffix", "github_owners",
    "protected_keys", "provision", "skills_dir", "host_ro_mounts", "apt_tools",
)
BASELINE_KEYS = ("domains", "http", "default_rules_off")


def env_name(name: str) -> str:
    """The environment variable that overrides a setting: OG_ and its name in capitals."""
    return "OG_" + name.upper()
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


def check_baseline(b, where: str) -> dict[str, list[str]] | None:
    """The [baseline] table: each of its three keys a list of text. None when there is none."""
    if b is None:
        return None
    if not isinstance(b, dict):
        raise Unreadable(f"{where}: baseline must be a [baseline] table")
    for k, v in b.items():
        if k not in BASELINE_KEYS:
            raise Unreadable(f"{where}: baseline.{k} isn't a key the baseline has ({', '.join(BASELINE_KEYS)})")
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise Unreadable(f"{where}: baseline.{k} must be a list of text")
    missing = [k for k in BASELINE_KEYS if k not in b]
    if missing:
        raise Unreadable(f"{where}: [baseline] has no {', '.join(missing)} (an empty list is {missing[0]} = [])")
    return {k: list(b[k]) for k in BASELINE_KEYS}


def _parsed() -> tuple[dict[str, str], dict[str, dict[str, str]], dict[str, list[str]] | None]:
    """The shared settings, each profile's own, and the [baseline] table."""
    # read whole on every lookup: settings are few and read rarely, and a cache
    # would outlive a test's (or a person's) edit to the file
    f = file()
    where = _shown(f)
    try:
        text = f.read_bytes().decode()
    except FileNotFoundError:
        return {}, {}, None
    except (OSError, UnicodeDecodeError) as e:
        raise Unreadable(f"can't read {where}: {getattr(e, 'strerror', None) or e}") from None
    try:
        d = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise Unreadable(f"{where} isn't valid TOML: {e}") from None
    base = check_baseline(d.pop("baseline", None), where)
    profs = d.pop("profiles", {})
    if not isinstance(profs, dict):
        raise Unreadable(f"{where}: profiles must be [profiles.<name>] sections")
    out = {}
    for name, p in profs.items():
        if not isinstance(p, dict):
            raise Unreadable(f"{where}: profiles.{name} must be a [profiles.{name}] section of settings")
        out[name] = _settings(p, where, f"profiles.{name}.")
    return _settings(d, where), out, base


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
    shared, profs, _ = _parsed()
    p = profile()
    return {**shared, **profs.get(p, {})} if p else shared


def get(name: str) -> str:
    """The setting: OG_<NAME> when that's set and not empty, else the file's, else "".
    The file is read either way, so a broken one always stops og."""
    if name not in NAMES:
        raise KeyError(f"{name} isn't one of og's settings")
    from_file = _read()
    return os.environ.get(env_name(name)) or from_file.get(name, "")


def baseline() -> dict[str, list[str]] | None:
    """config.toml's [baseline] table, its three lists; None when it has none."""
    return _parsed()[2]


def vault() -> str:
    """The 1Password vault og reads its token items and secret grants from: the vault
    setting, else Sandbox."""
    return get("vault") or "Sandbox"


def path(name: str, default: Path) -> Path:
    v = get(name)
    return Path(v).expanduser() if v else default
