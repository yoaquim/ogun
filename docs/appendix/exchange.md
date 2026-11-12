# Appendix: exchange internals

Reference for [File exchange](../exchange.md).

## Wiring

- og makes the tree, `inbox/`, `shared/` (git-initialized) and `boxes/`, when it makes a
  sandbox's directories at its first `ogun`, and makes again any part that's missing.
- At create, `ogun` writes the mounts into `.sbxenv.yaml`: read-only parents first, then the
  sandbox's own writable subdirectories nested inside them. Paths are quoted YAML scalars, so
  a relocated root with `#` or quotes in it doesn't break.
- A sandbox's box is `boxes/<name>/`, nowhere else.
- Names are the sandbox charset. `inbox`, `shared` and `boxes` are reserved, and a name
  that case-folds onto an existing box is refused. `ogun give <name>` refuses a name that is
  also a file in the current directory rather than guessing.
- At setup, `ogun` records the shared root inside the sandbox at
  `~/.config/sbx/exchange-shared-root`, so og ship's script (`workflow-push-request.sh`) finds
  the sandbox's `out/`, wherever the exchange is.

## Handing off: claim, then detach

The sandbox may still be writing when you take a file. So `ogun take` works in two steps:

1. **Claim.** Atomically rename the entry into unmounted staging. From that instant its name
   and type can't be swapped, and anything the sandbox writes afterwards is a different file,
   never touched or deleted.
2. **Detach.** The claimed inode may still be open for writing inside the sandbox, so only a
   fresh copy, an inode no sandbox holds, is checked, tagged and delivered.

Nothing ever runs chmod on, or tags, a live sandbox-writable path: a racing swap to a symlink
would aim the change at the link's target. Quarantine moves first and changes things after.

## What a read guard needs from og

A read guard is a Claude Code `PreToolUse` hook on `Read|Grep`, which a provision command
may add; og ships none. og gives one what it needs to hold up:

- **A root no sandbox can fake.** og writes the `shared/.exchange` marker on the Mac, and
  `shared/`'s top is read-only to every sandbox. A guard that anchors on the topmost marker
  on a path can't be re-rooted by a marker a sandbox plants in its own subdirectory.
- **A place for approvals no sandbox can write.** `shared/.approved/` is the host's: every
  sandbox mounts it read-only, and `og scan` keeps it, and `.git`, out of quarantine. A guard
  that records an approval there (the file's sha-256, written on the Mac) can trust it.

Whatever else a guard does is its own design; it should read only what it has scanned, never
the live file, which a running sandbox could rewrite between the check and the read.

## Deliberately not built

| Not built | Why |
|---|---|
| a LaunchAgent or watcher | no automatic host-side parser of sandbox output |
| mounting sandbox filesystems on the Mac | Finder browsing a hostile disk |
| images or binaries in `shared/` | text only; route binaries through you |
| auto-running anything taken | `ogun take` only moves and tags |
| `noexec` on the mounts | sbx offers no mount option. A live author can re-flip an exec bit after the scan, so nothing ever runs shared files, and the read path is what the guard covers. If sbx grows mount options, `noexec` on `inbox/` and `shared/` comes first |
| a storage quota | macOS has no per-directory quota, so a hostile sandbox could fill the disk through `out/`. It's loud and recoverable, not an integrity risk. If it ever bites: a size-capped sparse APFS image mounted at `~/sandboxes.noindex` |

## Defaults

| Setting | Default | Override |
|---|---|---|
| root | `~/sandboxes.noindex` | `exchange`. Keep the `.noindex` suffix, or add the root to Spotlight's Search Privacy list by hand |
| `ogun take` destination | `~/Downloads`, name-deduped | `take_dest` |
| size caps | `shared/` 1 MB per file, `out/` 1 GB per file | — |

## Implementation map

| File | Holds |
|---|---|
| `src/ogun/sandbox/envfile.py` | mount wiring in `env_yaml`, which `create` writes |
| `completion.bash` | tab completion for `give` and `take`: the box lookup (`boxes/<name>`) |

The agent's side (its rules for the exchange, the read guard, a way to publish notes to
`shared/`) and `pngpaste` for `--clip` are the Mac's own: og ships none of them.

## Verify on the Mac

These can't be tested from inside a sandbox. The logic is covered by the test suite. The
mounts and the xattr are macOS-only. After the first create following an exchange change,
check that:

- `inbox/` is read-only inside; the sandbox's own `in/` is mounted read-only, and another
  sandbox's `in/` isn't visible;
- another sandbox's `shared/` directory can't be written;
- a symlink, a fake `.pdf` (really a Mach-O), an exec-bit file and an oversized file in
  `out/` each get quarantined;
- a taken PDF carries the quarantine xattr;
- `shared/`'s git log attributes a handoff to the right sandbox.

If sbx rejects nested mounts (`shared/` read-only with `shared/<name>/` read-write inside),
the fallback is mounting `shared/<name>/` read-write plus every other sandbox's directory
read-only, as separate entries.
