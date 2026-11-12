# Appendix: og's style

Every `og` command looks and reads the same way. This page is the rule. The code is
`src/ogun/core/log.py` (each kind of line) and `core/boxes.py` (tables and boxes), the
only places a color, a mark or a layout is defined, and `og style` draws each pattern. To
change the look, change those first, check it with
`og style`, then update this page.

## Voice

- **Plain English, short.** Say what happened, then what to do about it. A line that asks
  for an action names the whole command to run: `sbx policy rm network --resource 'x'`, not
  "remove the rule".
- **An error says why, then the fix:** `og allow: no sandbox 'cub2' — name one, or --all for
  every sandbox; to see yours, run:`. It starts with `og <command>:`, so it's clear which
  command refused.
- **The fix command goes on its own line,** beneath the warning or error, where its text
  starts: the sentence says what's wrong and ends with a colon, the next line is what to run
  (`og take cub --all, then og tidy --rm`). It's the part to copy, so it stands alone. Pass it
  as `fix=` to `log.warn()` or `log.err()`, never inside the sentence; a test holds every
  message to this.
- **A command to run is og's when og can do it.** A fix names the `og` command (`og rm cub
  --force`, `og net cub docs.example.com --rm`); only what og can't do yet names `sbx` (below).
  On a terminal the command is bold, in og's color, so the part to copy stands out; piped,
  the same words. Wrap it in `log.cmd()`.
- **og, the name you type.** Every message names a command as `og …`, never `ogun …` (both
  run the same thing).
- **Several reasons:** the error line says what, its fix line what to do, and each reason is
  a note under them (`og rm` naming each piece of unsaved work).
- **Everyday English.** Use the word anyone would: "removed", not "taken back"; "allowed"
  and "blocked", not "granted" and "denied"; "can't", not "is unable to". Technical where the
  reader needs it to act (a command, a rule's id, a path, `http`), and nowhere else. A message
  you'd have to explain out loud is the wrong message.
- **No jargon the person didn't type.** Name things as the person knows them: a sandbox's
  name, a domain, a repo's address.

## Kinds of line

| Kind | Looks like | Use it for | `log.` |
|---|---|---|---|
| step | `→ GitHub pushes: each sandbox to its own repos` | the heading of one stage, in a command that has several | `step()` |
| note | `  · removed sbx's default rule …` | a fact under a step, worth seeing every time | `note()` |
| done | `✓ gave note.txt to workshop  ~/…/in/note.txt` (green, the detail dim) | what you asked for is finished | `ok()` |
| warning | `  ⚠ all of github.com is allowed …` (yellow) | needs a look, with what to do | `warn()` |
| error | `og policy takes no arguments — …` (red, stderr) | failed or refused | `err()` |
| plain | `nothing to tidy` | anything else: a line that found nothing to do, a next step | `info()` |
| detail | `  $ sbx policy ls …` (dim, stderr) | only with `-v` / `-vv` | `detail()` |
| callout | a block between two rules, title in capitals (orange) | must not scroll past: a security warning | `callout()` |
| section | `Wed 28 Oct 2026` (bold, og's color, a blank line above) | a heading over the lines below it: a day in `og log`, a repo in `og project ls` | `section()` |
| aside | `           og rm cub --force` (dim) | beneath the line above, where its text starts: the command under a change in `og log` | `aside()` |

Each line carries the dim clock of when it happened: now, live; the time it was recorded,
replayed (`og log`); none, for a listing that happened at no time (`og project ls`).
`step()`, `note()` and `info()` take `clock=` to say which; a done line, a warning and an
error are always now.

### Done, and steps

Green and a mark are for what needs your eye, so they stay rare:

- **✓ and green** mean *what you asked for is finished*: one line for each change a command
  makes, when it makes it (`✓ gave note.txt to workshop`, `✓ removed cub`, `✓ cub may reach
  docs.example.com`). Only the ✓ and the short summary are green; a detail after it (a path,
  what was kept, a hint) is dim. `log.ok(summary, detail)` adds the ✓; nothing else draws one.
- **Never ✓ or green:** a fact along the way (a note, `·`); a listing; a replay of what
  happened before (`og log` shows plain lines); a line that found nothing to do ("nothing to
  tidy"). Those are plain.
- **→** is a step: the heading of one stage of a command that has several (`og policy`'s
  `→ baseline egress: …`), saying what og is doing now. Never a result, never a lone line in a
  command that does one thing.

State marks: `✓` done, `✗` failed, `●` waiting, `○` idle, `▸`
running (`log.DONE`, `log.FAILED`, …), plus `⚠` for needs a look (`log.WARNING`), on a
warning line and in a summary. A list of sandboxes marks on and off as `●` and `○`
(`log.STATES`): a filled dot beside a hollow one reads at a glance.

## Destroying things

A command that removes or overwrites something (`og rm`) ends with one done line: what's
gone, and what stayed (`✓ removed cub  shared/cub kept`, or `✓ removed cub  shared/cub and its
folder (files in out/) kept`). Before that, each piece it took away is a note. When it can't tell whether something would be lost (a check that didn't
run), it treats that as a reason to stop, never as nothing to lose, and says how to go
ahead anyway (`--force`).

## Waiting

A step that waits on something slow (sbx starting a sandbox, a check inside it) shows a
spinner on a terminal, with what it waits on (`checking cub for unsaved work…`), on stderr,
gone when the step ends. Every `sbx` call og makes gets one (`src/ogun/core/sbx.py`), unless
sbx's own words or question are on screen. Piped, there is no spinner: the lines before and
after say the same thing. Use `log.waiting()`.

## Where output goes

- **stdout** is the result: steps, notes, done lines, and data (`--json`, a list of repos).
- **stderr** is errors, the `-v` / `-vv` details, and a warning that comes up while the
  command's real output goes to stdout (one a caller might capture).
- **Exit codes:** 0 when it did what was asked, 1 when it failed or refused, including a
  wrong call. 3 when it kept something on purpose (`og rm --if-clean`), or a check's answer
  is no (`og net <name> <domain> --check`: one isn't allowed), so a caller can tell that from
  a failure. A call handed straight to sbx (`og ls <sbx args>`) exits with sbx's
  code. A refusal never does part of the job first: a call that asks for help, or names
  something wrong, changes nothing.

- **sbx's own words stay out.** og says what happened in its own lines; what sbx printed
  shows only when sbx failed, as notes under og's error (`og rm --force`), or
  when sbx asks a question og can't (its y/N on a plain `og rm`). `-vv` shows the rest.
- **A line a program reads** (`kept: <why>` from `og rm --if-clean`) is a contract like JSON: one plain line on stdout, never colored, its words fixed.

## Terminal and plain

- **On a terminal:** a dim clock before each line, colors, and the boxes of the table format
  (below).
- **Piped, in a file, `NO_COLOR` or `TERM=dumb`:** the same words, plain, with no clock,
  colors or boxes, so a `grep` always matches ([Two formats](#two-formats) says how each
  reads).

## More detail

Nothing extra by default. `-v`, before the command or anywhere in its
arguments (`og sh`: only before it, since the words after its name are the command's), shows each `sbx` command og runs, how it ended and how long it took; `-vv` adds
what `sbx` printed. A script og sends to run inside a sandbox shows as its line count, not its
text; a call that failed shows its exit in red. Each file og changes on this Mac shows too, as
`  file  removed ~/…`. These go to stderr, and travel to every process the command starts as
`OGUN_VERBOSE`. Every `sbx` call goes through `src/ogun/core/sbx.py`, so every command gets
this for free.

## The record

Every change og makes on this Mac is one line in `~/.config/sbx/ogun/og.log` (`SBX_OGUN_DIR`):
when, the command as you typed it, and what changed (`cub removed`, `cub may reach
docs.example.com (reading only)`, `policy applied: …`). `og log` replays the last 20 in classic
format, a section a day, as plain lines with the command under each (piped, one whole line
each: [Two formats](#two-formats)), `-n` more, `--json` for scripts. Record what changed, not
what was read or refused. Past 1 MB the file moves to `og.log.1` and starts over, so it never
grows without end. A record that can't be written never fails the change: `-v` says so. Use
`log.record()`.

## Help and usage

- **On a terminal:** a box titled `og <command>`. Inside: one sentence on what the command
  is for, each form of the command beside what it does, a dim note for anything surprising,
  and two or three real examples, in green. A wrong call shows one red line first, saying
  what's missing, then a blank line. At most 96 columns wide. In a narrow pane, each form sits above what it
  does. Use `log.usage()`.
- **Plain:** a wrong call prints one line, `usage: og <command> <arguments>`. `--help`
  prints the same content as the box, as plain lines, starting with that line.
- `--help` or `-h` anywhere in a command is help, and the command does nothing else.
  `og sh` reads it only as its first argument: after that, it's the command's own.

## Two formats

Every command prints in one of two formats, the one that fits what it shows, and never
mixes them:

- **Classic:** og's lines, the kinds above, one after another, as a command does its
  work or lists what has parts under it. Long text folds, never cut.
- **Table:** one box of rows, for things that share a few short columns: the column names
  in og's color with a rule under them, the first column bold, a state with its mark and
  color (`● running` bold green, `○ stopped` dim, the whole row dim at rest), a column
  that reads the same on every row dim (AGENT), a label in lavender (`OpenAPPA`), and
  below, how many are in each state (`● 3 running · ○ 8 stopped`), then any line the
  table must be read with, dim. Each color means one thing, so a
  name is never colored by itself. Use `log.columns()`.

One addition, the only place a table sits in a classic run: a classic command of several
steps (`og policy`) may end, after a blank line, with a **summary** box, each step's name and
its state with its mark and color (`✓ applied`, `⚠ 1 to remove (above)`, `✗ not off yet
(above)`), so the outcome reads at a glance once the steps have scrolled by. A state that
needs a look points at the line above that explains it. Use `log.table()`, with the theme's
names (`[ok]`, `[warn]`, `[error]`), never a color by name.

| Command | Format |
|---|---|
| `og net <name>` | table: its rules, a push and a block marked, the ones every sandbox shares dim |
| `og net` | classic, to allow, block or remove |
| `og net <name> --log` | table: a host a row, blocked first, then allowed |
| `og net <name> <domain> --check` | table: a host a row, yes or no and its access; the fix beneath |
| `og allow` | classic |
| `og policy` | classic, ending with a summary |
| `og rm` | classic |
| `og log` | classic: a section a day, each change a plain line with the time it happened (a replay: no ✓, no green), its command beneath |
| `og project` | classic: a section a repo with grants, each grant a note; the rest under one last section |
| `og style` | classic, then one of each table and box |
| `og take <name>` | table: what waits in its out/ |
| `og take` | classic, to take files |
| `og scan` | classic: each change a line (a quarantine a warning, a commit a done line), or "nothing to change in shared/" |
| `og give` | classic |
| `og ship` | classic: the review paged, then one done line |
| `og mcp` | table: each server, its login status, who gets it; how to fix a row beneath |
| `og mcp auth` | classic |
| `og mcp load` | classic |
| `og pass <name>` | classic: a line a secret, never any part of a value |
| `og pass` | classic: one done line, the secret's value never shown |
| `og token` | classic: the steps, then one done line; the token never shown |
| `og skills` | classic: one step, how many skills |
| `og help` | classic: the command list, or one command's usage line and what it does |
| `og ssh` | classic: og's lines only for a wrong call; the rest is ssh's own |
| `og sh` | classic: og's lines only when it can't start; the rest is the shell's or the command's own output |
| `og stop` | classic: one done line |
| `og ports <name>` | table: what's published |
| `og ports` | classic: one done line |
| `og doctor` | classic: a section for sbx, one for og, each check a note or a warning with its fix |
| `og template ls` | table, with how to build what isn't, at its foot |
| `og template rm` | classic: one done line |
| `og template` | classic: a build's steps |
| `og attach` | classic: a warning only for a refresh that failed, then the session's own screen |
| `og tidy` | classic: a section a folder whose sandbox is gone, what's in it as notes; each secret left for one a warning, its removal command beneath |
| `og ls` | table |

`tests/test_docs.py` checks this list against each command's `FORMAT` in `cli.py`. A new
command picks one: a table only when every row is a few short values, classic otherwise.
Before anything new, reuse the kinds of line: a record of what og did reads best the way
og said it.

**Boxes.** Every table, and a command's help, sits in one kind of box: rounded corners in
og's color, `og <command>` in the top border, padded, as wide as what's in it and at most
96 columns. Draw it with `log.columns()`, `log.table()` or `log.usage()`, never a box or
table of your own.

**Piped,** each format is plain lines with no clock, color or box, so a grep finds a whole
one: classic, the bare words; a table, the same words aligned by spaces with no marks, so
`awk '{print $3}'` reads the state; a summary, nothing (the lines above said it all). A read
command whose items carry a time or parts prints one whole line per item (`og log`:
`2026-10-28 14:07:51  cub removed  (og rm cub --force)`).

## Values

One way to show each kind of value, from `log.py`:

| | | |
|---|---|---|
| a path | under your home as `~/…` (`~/Downloads/cub`), otherwise in full | `log.path()` |
| a size | `7 B`, `12 KB`, `1.2 MB`, `3.4 GB`: 1024 a step, one decimal under 10 | `log.size()` |
| a moment | local time, `2026-10-28 14:05` | `log.when()` |
| a clock before a line | `[14:05:09]`, dim, on a terminal only | automatic |
| how long | `41 ms` in `-v` | automatic |

## What og can't do yet

Each fix og still names as an `sbx` command, until og has its own:

| A fix og names | What og would need |
|---|---|
| `sbx policy rm network --id <rule> --force` | the same, for sbx's own default rules |
| `sbx settings set ssh.agentForwardingEnabled false`, `sbx daemon restart` | `og policy` sets the first itself; neither by hand |
| `sbx secret rm <name> --sandbox <sandbox>`, `sbx secret rm --sandbox <sandbox> --placeholder …` | removing a secret left behind by a sandbox that's gone (`og tidy` lists them); `og pass --rm` needs the sandbox |

## Colors

A soft palette, one set across og's output. The terminal shows the nearest color it can.

| | |
|---|---|
| og's own (arrows, borders, command forms, a command inside a message, bold) | sapphire `#7dc4e4` |
| a done line's ✓ and summary, and examples to copy | green `#a6da95` |
| needs a look | yellow `#eed49f` |
| failed or refused | rose `#ed8796` |
| a callout | peach `#f5a97f` |
| a label on a row (`OpenAPPA`) | lavender `#c6a0f6` |
| the clock, details, notes in a box | dim |

## JSON

A read command takes `--json` for scripts: the data only, on stdout, never colored, with no
clock, steps or summary.
