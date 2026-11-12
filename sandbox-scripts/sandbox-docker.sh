#!/usr/bin/env bash
# sandbox-docker.sh — runs INSIDE a sandbox, from og's base.setup and every attach:
# lets the containers the sandbox's own Docker runs reach the internet. sbx's
# proxy only serves traffic sent to it by address ($HTTPS_PROXY), at an
# address containers can't reach, and it re-signs HTTPS with its own CA.
# Intercepted container traffic to a method-limited rule (npm, PyPI, GitHub)
# is reset.
#
#   relay                     socat on the Docker bridge's gateway, :3128 →
#                             the proxy; its pid in ~/.docker/sbx-relay.pid
#   ~/.docker/config.json     proxies.default → the relay, which Docker hands
#                             every container and build as HTTPS_PROXY. HTTPS
#                             only: plain HTTP between containers
#                             (http://minio:9000) stays direct
#   ~/.docker/sbx-ca/ca.crt   the proxy's CA ($PROXY_CA_CERT_B64), exported as
#                             DOCKER_EXTRA_CA_DIR for builds that trust an
#                             extra CA
#
# The export is the one line it puts in /etc/sandbox-persistent.sh. Nothing
# there starts the relay: that file runs before every command, and a start
# that hangs would hang them all. A restart stops the relay; the next attach
# starts it again.
#
# Idempotent. With no Docker or no proxy there is nothing to relay: the export
# is removed and the rest left as is.
set -uo pipefail

docker_dir="$HOME/.docker"
pidf="$docker_dir/sbx-relay.pid"
ca_dir="$docker_dir/sbx-ca"
envf="${SBX_PERSISTENT_ENV:-/etc/sandbox-persistent.sh}"
# the marker's start, which finds og's line again
mark="# ogun sandbox-docker ("
export_line="export DOCKER_EXTRA_CA_DIR=\"\$HOME/.docker/sbx-ca\"  ${mark}sandbox-docker.sh)"
port=3128

# the proxy as host:port, from the sandbox's own setting
upstream() {
    local u="${HTTPS_PROXY:-${https_proxy:-}}"
    u="${u#*://}"; u="${u%%/*}"
    printf '%s' "$u"
}

# the default bridge's IPv4 gateway: an address of this sandbox every
# container network can reach
gateway() {
    docker network inspect bridge -f '{{range .IPAM.Config}}{{.Gateway}} {{end}}' 2>/dev/null \
        | tr ' ' '\n' | grep -m1 -E '^[0-9]+(\.[0-9]+){3}$'
}

# a live socat: a dead one nobody has reaped yet keeps its name, as a zombie
# (state Z, the third field of /proc/<pid>/stat)
relay_running() {
    local p c s
    { read -r p < "$pidf"; } 2>/dev/null || return 1
    { read -r c < "/proc/$p/comm" && read -r _ _ s _ < "/proc/$p/stat"; } 2>/dev/null \
        && [[ "$c" == socat && "$s" != Z ]]
}

# our line out of the env file, everything else kept
unexport() {
    [[ -f "$envf" ]] && grep -qF "$mark" "$envf" || return 0
    local t; t=$(grep -vF "$mark" "$envf")
    if [[ -n "$t" ]]; then printf '%s\n' "$t" > "$envf"; else : > "$envf"; fi
}

if ! command -v docker >/dev/null || [[ -z "$(upstream)" ]]; then
    unexport
    echo "  no Docker or no proxy here — nothing to relay"
    exit 0
fi
for t in socat jq; do
    command -v "$t" >/dev/null || { echo "sandbox-docker: $t is missing" >&2; exit 1; }
done

if [[ -n "${PROXY_CA_CERT_B64:-}" ]]; then
    mkdir -p "$ca_dir"
    printf '%s' "$PROXY_CA_CERT_B64" | base64 -d > "$ca_dir/ca.crt" \
        || { echo "sandbox-docker: PROXY_CA_CERT_B64 is not base64" >&2; exit 1; }
fi
unexport
[[ -s "$ca_dir/ca.crt" ]] && printf '%s\n' "$export_line" >> "$envf"

if relay_running; then
    echo "  ok the relay is running"
    exit 0
fi
gw=$(gateway) || { echo "sandbox-docker: Docker isn't up — no bridge to relay from; attach again once it is" >&2; exit 1; }
mkdir -p "$docker_dir"
cfg="$docker_dir/config.json"
[[ -s "$cfg" ]] || echo '{}' > "$cfg"
t=$(jq --arg p "http://$gw:$port" \
    '.proxies.default = ((.proxies.default // {}) + {httpsProxy: $p, noProxy: "localhost,127.0.0.1,::1"})' "$cfg") \
    || { echo "sandbox-docker: $cfg is not JSON" >&2; exit 1; }
printf '%s\n' "$t" > "$cfg"
( socat "TCP4-LISTEN:$port,bind=$gw,fork,reuseaddr" "TCP:$(upstream)" </dev/null >/dev/null 2>&1 & echo $! > "$pidf" )
for _ in 1 2 3 4 5; do
    relay_running && { echo "  ok containers reach the internet through the relay on $gw:$port"; exit 0; }
    sleep 0.1
done
echo "sandbox-docker: the relay on $gw:$port did not start" >&2
exit 1
