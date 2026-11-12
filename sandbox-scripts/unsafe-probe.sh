#!/usr/bin/env bash
# The check for unsaved work, run INSIDE a sandbox before og removes it
# (src/ogun/sandbox/remove.py sends it: sbx exec <name> bash -lc "<this>" _ [--root <workspace>] [mode]).
# It prints one line per reason the sandbox must stay, and nothing when removing it
# loses nothing: commits no remote has, uncommitted/untracked changes (ignoring
# sbx's and og's own files) in any checkout or any worktree of one, or background
# Claude jobs (any `claude --bg` session) still in a non-terminal state.
# --idle-ok (`og rm --if-clean`): only a job mid-turn or waiting on a person counts,
# and an open terminal (attach, sh, ssh) does too. --stopped: the sandbox was
# stopped before this check booted it, so nothing ran in it — only the git half is
# asked (a job stopped mid-turn leaves its `working` state behind for good).
# --root <dir> (any number, before the mode): another place to look, the sandbox's
# own workspace, which og may have mounted from outside the usual roots.
# OG_PROBE_ROOTS (where checkouts are looked for) is for tests.
mode=""; extra=()
while [ $# -gt 0 ]; do
  case "$1" in
    --root) [ -n "${2:-}" ] && extra+=("$2"); shift; [ $# -gt 0 ] && shift ;;   # a lone --root: skipped, never a loop
    *) mode="$1"; shift ;;
  esac
done
# read-only mounts (related checkouts, host reference folders, any other ro
# workspace) only mirror host state: the sandbox cannot have changed them,
# so their dirt is the HOST checkout's and is not lost with the sandbox
# — it must not block removal. /proc/mounts marks them ro.
ro=""; while read -r _ mp _ opts _; do case ",$opts," in *,ro,*) ro="$ro $mp";; esac; done < /proc/mounts
is_ro() { for mp in $ro; do case "$1" in "$mp"|"$mp"/*) return 0;; esac; done; return 1; }
read -ra roots <<< "${OG_PROBE_ROOTS:-/Users /home/agent}"   # split on spaces, never globbed
roots+=(${extra[@]+"${extra[@]}"})
# a workspace under a usual root is found twice: once is the report
find "${roots[@]}" -maxdepth 6 -name .git -type d 2>/dev/null | sort -u | while IFS= read -r g; do
  r=${g%/.git}
  is_ro "$r" && continue
  # refs are shared by every worktree: one count covers them all. Every
  # local ref and HEAD, not only branches: a detached HEAD, a stash or a
  # local tag holds commits a remote may not have
  if l=$(git -C "$r" log --all --not --remotes --oneline 2>/dev/null); then
    n=$(printf "%s" "$l" | grep -c .); [ "$n" -gt 0 ] && echo "$r: $n unpushed commit(s)"
  else
    echo "$r: git could not read its history — unsaved work unknown"
  fi
  # each worktree has its own changes (.git is a file there, so only the
  # checkout it hangs off finds it). Claude Code's worktrees dir, checked
  # worktree by worktree, isn't the checkout's own work, and is excluded by
  # pathspec, not filtered after: git folds an untracked dir holding only
  # worktrees into ".claude/", which no line filter can tell from real work.
  git -C "$r" worktree list --porcelain 2>/dev/null | sed -n "s/^worktree //p" | while IFS= read -r w; do
    # a git that fails to answer (a corrupt index) is unknown work: it
    # keeps the sandbox, never reads as clean
    if l=$(git -C "$w" status --porcelain -- . ":(exclude,glob)**/.claude/worktrees/**" \
          ":(exclude,glob)**/.sbxenv.yaml" ":(exclude,glob)**/.inbox/**" 2>/dev/null); then
      d=$(printf "%s" "$l" | grep -c .); [ "$d" -gt 0 ] && echo "$w: $d uncommitted/untracked file(s)"
    else
      echo "$w: git status failed — unsaved work unknown"
    fi
  done
done
[ "$mode" = --stopped ] && exit 0
j=0; for f in "$HOME"/.claude/jobs/*/state.json; do [ -f "$f" ] || continue
  st=$(jq -r ".state // .status // \"\"" "$f" 2>/dev/null | tr "[:upper:]" "[:lower:]")
  # --idle-ok: a session whose turn ended (a finished job sits idle,
  # alive) loses nothing; only one mid-turn or waiting on a person counts
  if [ "$mode" = --idle-ok ]; then
    case "$st" in working|running|busy|needs_input|blocked) j=$((j+1));; esac
  else
    case "$st" in completed|complete|done|failed|error|killed|cancelled|canceled|stopped|"") ;; *) j=$((j+1));; esac
  fi
done; [ "$j" -gt 0 ] && echo "$j background Claude job(s) still running"
# a person in it: a process on a terminal (this check has none) — but
# not one of Claude's own: `claude --bg` runs every session, and the
# daemon its spare, on a pty under a `claude bg-pty-host`, and whatever
# the session runs inherits that tty. A tty one of those holds is no one.
if [ "$mode" = --idle-ok ] && [ -n "$(ps -eo pid=,ppid=,tty=,args= 2>/dev/null | awk "
    { pid[NR] = \$1; pp[NR] = \$2; tt[NR] = \$3; if (\$5 == \"bg-pty-host\") host[\$1] = 1 }
    END { for (i = 1; i <= NR; i++) if (host[pp[i]]) bg[tt[i]] = 1
          for (i = 1; i <= NR; i++) if (tt[i] != \"?\" && !bg[tt[i]]) { print tt[i]; exit } }")" ]; then
  echo "a terminal is open in it (attach, ogun sh or ssh)"
fi
true
