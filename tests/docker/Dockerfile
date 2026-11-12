# og's test container: its whole suite (test.sh) on a clean Linux, with every tool a test
# needs, as an unprivileged user. Built and run by tests/docker/run.sh; the build context
# is the repo, less what .dockerignore leaves out. Real sandboxes don't run here: the suite
# fakes sbx, op, curl and gh (tests/conftest.py), so nothing reaches them.
FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc

# og's own needs (docs/setup.md): git and curl; jq, python3 and shellcheck for its shell tests;
# rsync, procps (kill, pkill) and ssh-keygen, which a Mac has built in and tests call
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git jq openssh-client procps python3 rsync shellcheck \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash og
USER og
WORKDIR /home/og/ogun

# setup builds og's venv from its pins (uv, Python and packages downloaded and checked).
# A network that inspects TLS hands its CA in as the extra_ca secret (run.sh's OG_TEST_CA):
# trusted for this step alone, never kept in the image
COPY --chown=og:og . .
RUN --mount=type=secret,id=extra_ca,uid=1000 \
    if [ -s /run/secrets/extra_ca ]; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/extra_ca > /tmp/og-ca.pem; \
      export SSL_CERT_FILE=/tmp/og-ca.pem CURL_CA_BUNDLE=/tmp/og-ca.pem; \
    fi; \
    ./setup.sh; rc=$?; rm -f /tmp/og-ca.pem; exit $rc

ENTRYPOINT ["tests/docker/entry.sh"]
