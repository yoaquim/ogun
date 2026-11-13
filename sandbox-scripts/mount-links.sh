#!/usr/bin/env bash
# og's mount-links.sh, run inside a sandbox at every setup: the links its mounts were
# reached through on the Mac, made again here. sbx mounts a folder at its real path,
# so a mount named through a link (~/sandbox-setup -> ~/dotfiles/claude) would be
# missing under the name you gave it. Arguments are pairs: <link> <real path>.
# Only a link, or nothing, is ever replaced: a real file or folder at <link> is left
# as it is, and said.
set -uo pipefail
rc=0
while (( $# >= 2 )); do
  link="$1" to="$2"
  shift 2
  if [[ "$link" != /* || "$to" != /* ]]; then
    echo "mount-links: $link -> $to: not full paths; skipped"; rc=1; continue
  fi
  if [[ -e "$link" && ! -L "$link" ]]; then
    echo "mount-links: $link is already there and isn't a link; left as it is"; continue
  fi
  parent="$(dirname "$link")"
  { mkdir -p "$parent" && ln -sfn "$to" "$link"; } 2>/dev/null && continue
  { sudo -n mkdir -p "$parent" && sudo -n ln -sfn "$to" "$link"; } 2>/dev/null && continue
  echo "mount-links: couldn't make $link -> $to"; rc=1
done
exit "$rc"
