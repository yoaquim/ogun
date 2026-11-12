"""Writing a file whole: a temp file beside it, then a rename. A crash or a full
disk mid-write leaves the old file, never half of a new one, and no temp file."""

import json
import os
from pathlib import Path


def write_text(f: Path | str, text: str, private: bool = False) -> None:
    """Replace f with text. private: readable by its owner only (0600); otherwise
    the umask decides. Raises OSError when it can't."""
    f = Path(f)
    tmp = f.with_name(f"{f.name}.tmp.{os.getpid()}")
    try:
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o666), "w") as out:
            out.write(text)
        os.replace(tmp, f)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_json(f: Path | str, data, private: bool = False, ascii: bool = True, newline: bool = False) -> None:
    """Replace f with data as JSON, indented two. ascii=False keeps non-ASCII text
    as written; newline ends the file with one."""
    write_text(f, json.dumps(data, indent=2, ensure_ascii=ascii) + ("\n" if newline else ""), private=private)
