#!/usr/bin/env bash
# Build og's test container from this checkout and run its whole suite in it; the exit is
# the suite's. Arguments go to test.sh (a filter: run.sh python). Needs only Docker.
# On a network that inspects TLS, OG_TEST_CA names its CA certificate: the build trusts it
# while setup downloads og's pins, and the image never keeps it.
#
#   tests/docker/run.sh           # everything
#   tests/docker/run.sh python    # only files whose name contains "python"
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
image="${OG_TEST_IMAGE:-og-test}"

ca=()
if [[ -n "${OG_TEST_CA:-}" ]]; then
  [[ -s "$OG_TEST_CA" ]] || { echo "run.sh: OG_TEST_CA ($OG_TEST_CA) isn't a readable certificate file" >&2; exit 1; }
  ca=(--secret "id=extra_ca,src=$OG_TEST_CA")
fi
# ${ca[@]+…}: an empty array under set -u is an error in macOS's bash 3.2
docker build ${ca[@]+"${ca[@]}"} -f "$root/tests/docker/Dockerfile" -t "$image" "$root"
exec docker run --rm "$image" "$@"
