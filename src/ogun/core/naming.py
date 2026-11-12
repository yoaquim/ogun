"""A sandbox's name: the characters og takes, and the exchange folders no sandbox may be
named. A name reaches host paths (its folder in the exchange, its create record), so
every name is checked here before a path is built from it."""

import re

from ogun.core import log

# the characters alone, any length: a sandbox made with plain sbx can be named past
# the 61 og allows (name_ok) and may still have an exchange box. Kept in step with
# the shell completion's _og_name_chars (shared-values.test.sh)
_CHARS = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# exchange directories no sandbox may be named, in any case: the Mac's filesystem
# folds case, so `Inbox` is `inbox`
_RESERVED = {"inbox", "shared", "boxes"}


def name_chars(n: str) -> bool:
    return bool(_CHARS.fullmatch(n))


NAME_RULE = "letters, digits, . _ - only, not starting with . _ -"   # _CHARS, in words


def bad_name(cmd: str, n: str) -> None:
    log.err(f"og {cmd}: '{log.shown(n)}' can't be a sandbox name — {NAME_RULE}")


def reserved_name(cmd: str, n: str) -> None:
    log.err(f"og {cmd}: '{n}' is one of the exchange's own folders, not a sandbox")


def reserved(n: str) -> bool:
    return n.lower() in _RESERVED


def name_ok(n: str) -> bool:
    return name_chars(n) and len(n) <= 61
