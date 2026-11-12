#!/usr/bin/env bash
# The OpenAPPA install, run inside a sandbox (docs/appa.md): og sends this
# file as text with `sbx exec <sandbox> bash -c` (src/ogun/sandbox/appa.py), so it
# needs nothing of og's mounted, a template's build sandbox among them. Arguments: the release tag, the
# aarch64 and x86_64 archives' SHA-256 from appa.lock in og's config folder, the repo URL.
# The archive for this platform from the pinned release, its SHA-256 checked
# against the lock, its entries checked as OpenAPPA's own installer does
# (nothing absolute, nothing climbing out, appa a regular file), then appa run
# once before it's installed. An appa already at the pinned version (a
# template's image) is kept.
set -euo pipefail
v=$1 sha_a=$2 sha_x=$3 repo=$4
case $(uname -m) in
  aarch64|arm64) p=aarch64-unknown-linux-gnu want=$sha_a ;;
  x86_64|amd64)  p=x86_64-unknown-linux-gnu want=$sha_x ;;
  *) echo "no OpenAPPA build for $(uname -m)" >&2; exit 1 ;;
esac
case "$(appa --version 2>/dev/null || true)" in *" ${v#v}") echo "appa ${v#v} already installed"; exit 0 ;; esac
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
curl -fsSL --proto =https --proto-redir =https -o "$w/a.tgz" "$repo/releases/download/$v/appa-$p.tar.gz"
[ "$(sha256sum "$w/a.tgz" | cut -d" " -f1)" = "$want" ] || { echo "appa-$p.tar.gz does not match the SHA-256 in the lock" >&2; exit 1; }
tar -tzf "$w/a.tgz" | while IFS= read -r e; do
  case $e in /*|..|../*|*/..|*/../*) echo "appa-$p.tar.gz holds an entry outside its folder: $e" >&2; exit 1 ;; esac
done
mkdir "$w/x" && tar -xzf "$w/a.tgz" -C "$w/x"
{ [ -f "$w/x/appa" ] && [ ! -L "$w/x/appa" ]; } || { echo "appa-$p.tar.gz holds no appa binary" >&2; exit 1; }
"$w/x/appa" --version
sudo install -m 755 "$w/x/appa" /usr/local/bin/appa
