#!/usr/bin/env bash
# workflow-push-request.sh — hand a branch the sandbox can't push to the Mac: og ship's sandbox half (og runs the other).
#
# A sandbox's GitHub token has no workflow permission (docs/secrets.md), so
# GitHub refuses any push that creates or changes .github/workflows/*. That
# must stay a hard failure; this turns it into one command for you to run on the Mac:
# the branch's unpushed commits go to the exchange out/ as a format-patch, and
# a WORKFLOW PUSH REQUEST block prints the `og ship` line that takes, checks,
# shows and (on their y) pushes them from the Mac. `ogun ship` is the gate —
# it trusts nothing from here; the checks below only refuse early and clearly.
#
# Usage: workflow-push-request.sh [--remote <name>] [--to <ref>] [--why "<one line>"]
#        workflow-push-request.sh --landed [--remote <name>] [--to <ref>]
#   default    write the patch, print the block. An agent shows the block to you whole.
#   --remote   the remote the push failed on (default origin). `og ship` fetches
#              and pushes that same remote name: a sandbox mirrors the host's
#              remotes under their host names.
#   --to       the branch on the remote the refused push was writing (the
#              `-> <ref>` in git's rejection); default: this branch's upstream
#              on that remote, else this branch's own name.
#   --landed   once you've pushed it from the Mac: fetch the branch, check its
#              tree is exactly this HEAD's, and move the local branch onto it
#              (pushed from the Mac, its commits may differ in committer and signature), so
#              later pushes fast-forward. Refuses if the trees differ.
#
# Env (tests): WPR_OUT_DIR overrides where the patch goes; WPR_FETCH_URL
# overrides the URL it talks to GitHub through.
# Exit: 0 ok; 1 refused (the message says why); 2 usage.

set -uo pipefail

die() { printf 'workflow-push-request: %s\n' "$*" >&2; exit 1; }

remote=origin why="" mode=request to=""
while (( $# )); do
    case "$1" in
        --remote) remote="${2:-}"; shift 2 || exit 2 ;;
        --why)    why="${2:-}"; shift 2 || exit 2 ;;
        --to)     to="${2:-}"; shift 2 || exit 2 ;;
        --landed) mode=landed; shift ;;
        -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) printf 'workflow-push-request: unknown argument %s\n' "$1" >&2; exit 2 ;;
    esac
done

git rev-parse --git-dir >/dev/null 2>&1 || die "not inside a git repository"
branch=$(git symbolic-ref --quiet --short HEAD) || die "HEAD is detached; switch to the branch whose push failed"
# The block is pasted into the Mac's shell, and the sandbox chooses these names:
# git accepts a branch like ci$(cmd), which the paste would run. Every value a
# command line carries is held to a charset with nothing the shell expands.
[[ "$branch" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] \
    || die "branch name '$branch' has characters the Mac's shell would interpret; rename it (git branch -m) to letters, digits, . _ / -"
[[ "$remote" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "remote name '$remote' has characters the Mac's shell would interpret"
rurl=$(git remote get-url "$remote" 2>/dev/null) || die "no remote '$remote'"
# the remote branch: --to, else the upstream when it is on this remote, else ours
if [[ -z "$to" && "$(git config "branch.$branch.remote" 2>/dev/null)" == "$remote" ]]; then
    to=$(git config "branch.$branch.merge" 2>/dev/null); to=${to#refs/heads/}
fi
to=${to#refs/heads/}; to=${to:-$branch}
if ! [[ "$to" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || ! git check-ref-format --branch "$to" >/dev/null 2>&1; then
    die "--to '$to' is not a plain branch name (letters, digits, . _ / -)"
fi
# the commit handed off, per remote branch: --landed moves onto the pushed
# copy only while HEAD is still exactly it
rec="$(git rev-parse --git-path workflow-push-request)/$remote/${to//\//__}"

# owner/repo from the remote, for the block and for an https URL: a sandbox
# reaches GitHub over https (the proxy adds the token), not over ssh
slug=$(sed -E 's#^(git@github\.com:|ssh://git@github\.com/|https://([^@/]*@)?github\.com/)##; s#\.git$##; s#/$##' <<<"$rurl")
if [[ -n "${WPR_FETCH_URL:-}" ]]; then
    furl="$WPR_FETCH_URL"
elif [[ "$slug" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ && "$slug" != "$rurl" ]]; then
    furl="https://github.com/$slug.git"
else
    furl="$rurl"
fi

# fetch <ref> → its sha on the remote (fetched, so it exists here), or nothing
remote_sha() {
    local line
    line=$(git ls-remote "$furl" "$1" 2>/dev/null | awk -v r="$1" '$2 == r { print $1; exit }')
    [[ -n "$line" ]] || return 1
    git cat-file -e "$line^{commit}" 2>/dev/null || git fetch -q "$furl" "$1" 2>/dev/null || return 2
    printf '%s\n' "$line"
}

if [[ "$mode" == landed ]]; then
    [[ -f "$rec" ]] || die "no request recorded for $remote/$to from this clone — not moving"
    read -r rsha rbranch <"$rec"
    # the branch too: another branch at the same commit would pass a sha check,
    # and the reset would move it while the requesting branch kept the old history
    [[ "$branch" == "$rbranch" ]] \
        || die "the request for $remote/$to came from branch ${rbranch:-?}, not $branch — switch to it (git switch $rbranch) and run --landed there"
    [[ "$(git rev-parse HEAD)" == "$rsha" ]] \
        || die "$branch has moved since the request (it handed off ${rsha:0:12}) — not moving; a commit changed or added since would be dropped. Request again: workflow-push-request.sh"
    tip=$(remote_sha "refs/heads/$to"); rc=$?
    (( rc == 0 )) || die "branch $to is not on $slug yet (or could not be fetched) — has it been pushed from the Mac?"
    [[ "$(git rev-parse "$tip^{tree}")" == "$(git rev-parse "HEAD^{tree}")" ]] \
        || die "$slug's $to (${tip:0:12}) does not hold the same files as HEAD — not moving; compare with: git diff HEAD $tip"
    # same final files isn't enough: a commit made after the request that
    # nets to nothing (an empty one, a change and its undo) would pass, and the
    # reset would drop it. git am recreates each commit with the same tree and
    # message onto the same base, so the two sequences must match one for one.
    fork=$(git merge-base HEAD "$tip") || die "HEAD and $slug's $to share no history — not moving"
    seq() { git log --reverse --format='%T %s' "$fork..$1"; }
    [[ "$(seq HEAD)" == "$(seq "$tip")" ]] \
        || die "$branch has commits that $slug's $to (${tip:0:12}) doesn't (made after the request?) — not moving; request again for them: workflow-push-request.sh"
    if ! git diff --quiet HEAD || ! git diff --cached --quiet HEAD; then die "uncommitted changes; commit or stash them first"; fi
    git reset -q --keep "$tip" || die "could not move $branch onto ${tip:0:12}"
    rm -f "$rec"
    git update-ref "refs/remotes/$remote/$to" "$tip" 2>/dev/null || true
    printf 'workflow-push-request: %s now matches %s on %s (same files); later pushes fast-forward\n' "$branch" "${tip:0:12}" "$slug's $to"
    exit 0
fi

# base: the GitHub commit the patch applies onto. The branch's tip when it is
# already on GitHub (earlier pushes worked), else where it forked from the
# default branch — either way a commit the Mac can fetch.
if tip=$(remote_sha "refs/heads/$to"); then
    git merge-base --is-ancestor "$tip" HEAD \
        || die "$slug's $to (${tip:0:12}) has commits this branch lacks; pull or rebase first"
    base=$tip on_github="updates $to at ${tip:0:12}"
else
    (( $? == 1 )) || die "could not fetch $to from $slug"
    def=$(remote_sha HEAD) || die "could not read $slug's default branch"
    base=$(git merge-base HEAD "$def") || die "this branch shares no history with $slug's default branch"
    on_github="new branch, from ${base:0:12}"
fi

n=$(git rev-list --count "$base..HEAD")
(( n > 0 )) || die "nothing to push: $branch has no commits past ${base:0:12}"
[[ -z "$(git rev-list --merges "$base..HEAD")" ]] \
    || die "the commits past ${base:0:12} include a merge, which a patch can't carry; rebase onto ${base:0:12} first"
# a diff can't show what a binary or a submodule runs, and og ship refuses
# both in any commit (content added then removed still goes up in history):
# say so now. Raw modes and bytes, never diff attributes the range can set.
bad="" seen=" "
while IFS=$' \t' read -r _ nm _ ns _ path; do
    [[ "$nm" == 160000 ]] && { bad+="submodule $path; "; continue; }
    [[ "$ns" =~ ^0+$ || "$seen" == *" $ns "* ]] && continue
    seen+="$ns "
    if [[ "$nm" == 100644 || "$nm" == 100755 ]] \
       && [[ "$(git cat-file blob "$ns" | LC_ALL=C tr -d '\000' | wc -c | tr -d ' ')" != "$(git cat-file -s "$ns")" ]]; then
        bad+="binary $path; "
    fi
done < <(git log --format= --raw --no-abbrev --no-renames -r "$base..HEAD" | sed 's/^://')
[[ -z "$bad" ]] || die "og ship would refuse this range, since a diff can't show what these run: $(LC_ALL=C tr -c '[:print:]' '?' <<<"${bad%; }") — build them in CI or hand them over separately"
mapfile -t wf < <(git diff --name-only "$base" HEAD -- .github/workflows | LC_ALL=C tr -c '[:print:]\n' '?')

# where you collect files from on the Mac: this sandbox's out/ in the exchange (`og take`)
# the name goes into a command line, so a placeholder won't do (<sandbox> is a
# redirection): SANDBOX_NAME, else the hostname (sbx sets both), else refuse
sb="${SANDBOX_NAME:-$(hostname 2>/dev/null)}"
[[ "$sb" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
    || die "no usable sandbox name (SANDBOX_NAME and hostname are unset or unsafe); set SANDBOX_NAME to this sandbox's name and run again"
# the exchange is where og said at setup: its shared/ folder, in ~/.config/sbx
out="${WPR_OUT_DIR:-}"
if [[ -z "$out" ]]; then
    shared=$(head -n 1 "$HOME/.config/sbx/exchange-shared-root" 2>/dev/null)
    [[ "$shared" == /* && -d "$(dirname "$shared")/boxes/$sb/out" && -w "$(dirname "$shared")/boxes/$sb/out" ]] \
        && out="$(dirname "$shared")/boxes/$sb/out"
fi
[[ -n "$out" ]] || die "no out/ folder for $sb in the exchange: og names the exchange at setup (og $sb --sync on the Mac sets it again)"

# a flat name ogun take accepts, unique per request: ogun take renames onto a free name in ~/Downloads, so a
# reused name would leave the take line pointing at an older patch
name="${slug##*/}-$branch-$(git rev-parse --short=8 HEAD)-$(date -u +%Y%m%d%H%M%S)-$$"
name=$(tr -c 'A-Za-z0-9._-' '-' <<<"$name" | sed -E 's/-+$//; s/^[^A-Za-z0-9]+//').patch
git format-patch --stdout --binary "$base..HEAD" >"$out/$name" || die "could not write $out/$name"
if ! mkdir -p "$(dirname "$rec")" || ! printf '%s %s\n' "$(git rev-parse HEAD)" "$branch" >"$rec"; then
    die "could not record the request in $rec"
fi

top=$(cd "$(git rev-parse --git-common-dir)/.." && pwd)
# the lines that aren't commands still reach the terminal: no control
# characters (escape sequences, a newline faking an extra command line)
[[ "$top" =~ ^/[A-Za-z0-9._/\ -]*$ ]] || top="your clone of it"
[[ "$slug" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || slug="(remote $remote)"
why=$(LC_ALL=C tr -c '[:print:]' ' ' <<<"$why" | cut -c1-200 | sed 's/ *$//')
if (( ${#wf[@]} )); then wfl=$(printf '%s, ' "${wf[@]}"); wfl=${wfl%, }; else wfl="none in the diff — check the push error"; fi
tree=$(git rev-parse 'HEAD^{tree}')
line="og ship $sb $name --remote $remote --branch $to --base $base --commits $n --tree $tree"
cat <<EOF
WORKFLOW PUSH REQUEST
repo:     $slug
branch:   $to ($on_github)
commits:  $n
workflow: $wfl
patch:    $name
why:      ${why:-<one line: what the workflow change is for>}

On the Mac, in $top:
  $line
It takes the patch, applies it in a throwaway worktree with git hooks off (your
checkout and branches are untouched), refuses binaries and submodules, pages
every commit's patch for you to read, and pushes only on your y.
Then tell me it's pushed.
EOF
