#!/usr/bin/env bash
# setup.sh — build ogun's venv (.venv on a Mac; bin/venv names it) with the pinned uv, and nothing
# newer: the uv in uv.pin, checked against its SHA-256 before it runs; the Python
# in .python-version; the packages in uv.lock. Nothing here updates itself — a
# new version of any of them is an edit to those files (docs/appendix/ogun-python.md).
# Run when og is installed, and again by hand after a bump. It puts og on PATH itself: og and
# ogun, links to the venv's og, in OGUN_BIN (~/.local/bin; empty: no links, as for a
# sandbox that builds og only to run its tests).
set -uo pipefail

here=$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root="${OGUN_TOOLS:-$HOME/.local/share/ogun}"   # the pinned uv and its Pythons, apart from any other uv's
bin="${OGUN_BIN-$HOME/.local/bin}"               # where og and ogun go on PATH; set empty for none
die() { echo "ogun setup: $*" >&2; exit 1; }
pin() { awk -v k="$1" '!/^#/ && $1 == k { print $2; exit }' "$here/uv.pin"; }

ver=$(pin version)
[[ "$ver" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "uv.pin names no version"
case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)  plat=aarch64-apple-darwin ;;
    Darwin-x86_64) plat=x86_64-apple-darwin ;;
    Linux-aarch64) plat=aarch64-unknown-linux-gnu ;;
    Linux-x86_64)  plat=x86_64-unknown-linux-gnu ;;
    *) die "no pinned uv for $(uname -s) $(uname -m)" ;;
esac
want=$(pin "$plat")
[[ "$want" =~ ^[0-9a-f]{64}$ ]] || die "uv.pin has no SHA-256 for $plat"

sha256() { if command -v shasum >/dev/null; then shasum -a 256 "$1"; else sha256sum "$1"; fi | awk '{ print $1 }'; }

uv="$root/uv-$ver/uv"
if [[ ! -x "$uv" ]]; then
    tmp=$(mktemp -d) || die "no temp dir"
    trap 'rm -rf "$tmp"' EXIT
    echo "ogun setup: uv $ver ($plat)"
    curl -fsSL --proto '=https' --tlsv1.2 -o "$tmp/uv.tar.gz" \
        "https://github.com/astral-sh/uv/releases/download/$ver/uv-$plat.tar.gz" || die "could not download uv $ver"
    got=$(sha256 "$tmp/uv.tar.gz")
    [[ "$got" == "$want" ]] || die "uv $ver ($plat): SHA-256 is $got, uv.pin says $want — refused"
    # only the one file, by its exact name: nothing else in the archive is written
    tar -xzf "$tmp/uv.tar.gz" -C "$tmp" "uv-$plat/uv" || die "uv $ver: no uv-$plat/uv in the archive"
    mkdir -p "$root/uv-$ver" || die "could not make $root/uv-$ver"
    install -m 755 "$tmp/uv-$plat/uv" "$uv" || die "could not install uv to $uv"
fi
[[ "$("$uv" --version 2>/dev/null)" == "uv $ver"* ]] || die "$uv is not uv $ver"

# no UV_* setting from elsewhere may change what is installed, and the rules
# that matter are flags too, which win over any uv.toml: the lock as written,
# wheels only, the pinned Python, downloaded by this uv
for v in $(compgen -e | grep '^UV_'); do unset "$v"; done
py=$(tr -d '[:space:]' < "$here/.python-version")
[[ "$py" =~ ^3\.[0-9]+\.[0-9]+$ ]] || die ".python-version must name one exact Python (3.x.y), not '$py'"
export UV_PYTHON_INSTALL_DIR="$root/python"
venv=$("$here/bin/venv")
export UV_PROJECT_ENVIRONMENT="$venv"
# uv says it skips [project.scripts]: og isn't packaged on purpose, and the command is
# written below instead, so that one line is dropped; everything else uv says is kept
"$uv" sync --frozen --no-build --managed-python --python "$py" --project "$here" 2>&1 \
    | { grep -v 'Skipping installation of entry points (`project.scripts`)' || true; }
(( PIPESTATUS[0] == 0 )) || die "uv sync failed"
got=$("$venv/bin/python" -I -c 'import platform; print(platform.python_version())')
[[ "$got" == "$py" ]] || die "$venv runs Python $got, not $py — remove it and run this again"

# og itself, never built and nothing downloaded for it: a .pth file puts src/ on
# the venv's path as it is, and the command is pyproject.toml's [project.scripts]
# entry, written here, run by the venv's Python isolated (-I: no user
# site-packages, no PYTHON* variables, no current folder on the path)
[[ "$venv" != *[[:space:]]* ]] || die "$venv has a space in it, which a script's first line can't hold"
site=$("$venv/bin/python" -I -c 'import sysconfig; print(sysconfig.get_path("purelib"))') || die "no site-packages in $venv"
printf '%s\n' "$here/src" > "$site/ogun.pth" || die "could not write $site/ogun.pth"
entry=$("$venv/bin/python" -I -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["scripts"]["og"])' "$here/pyproject.toml")
[[ "$entry" =~ ^([a-z_.]+):([a-z_]+)$ ]] || die "pyproject.toml declares og as '$entry', not <module>:<function>"
printf '#!%s -I\nimport sys\nfrom %s import %s\nsys.argv[0] = "og"\nsys.exit(%s())\n' \
    "$venv/bin/python" "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "${BASH_REMATCH[2]}" > "$venv/bin/og.new" \
    && chmod 755 "$venv/bin/og.new" && mv -f "$venv/bin/og.new" "$venv/bin/og" || die "could not write $venv/bin/og"
"$here/bin/venv" --ready || die "$venv's Python can't load og's packages — remove it and run this again"
echo "ogun setup: $venv — Python $got, og at $venv/bin/og"

# og and ogun on PATH: a link of ours (or any link) is pointed at this og; a file that
# isn't a link is someone else's, left as it is
if [[ -n "$bin" ]]; then
    mkdir -p "$bin" || die "could not make $bin"
    for name in og ogun; do
        if [[ -e "$bin/$name" && ! -L "$bin/$name" ]]; then
            echo "ogun setup: $bin/$name is not a link, left as it is: og isn't on PATH as $name" >&2
        elif [[ "$(readlink "$bin/$name" 2>/dev/null)" != "$venv/bin/og" ]]; then
            ln -sfn "$venv/bin/og" "$bin/$name" || die "could not link $bin/$name"
        fi
    done
    case ":$PATH:" in *":$bin:"*) ;; *) echo "ogun setup: $bin isn't on your PATH: add it to run og" ;; esac
fi
echo "ogun setup: tab completion for og: in your shell profile, source $here/completion.bash"
