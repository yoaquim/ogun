# og's test container: its whole suite (test.sh) on a clean Linux, with every tool a test
# needs, as an unprivileged user. Built and run by tests/docker/run.sh; the build context
# is the repo, less what .dockerignore leaves out. Real sandboxes don't run here: the suite
# fakes sbx, op, curl and gh (tests/conftest.py), so nothing reaches them.
# bash 3.2, the one a Mac ships at /bin/bash, built from GNU's source (pinned by SHA-256)
# for the completion tests (tests/sh/completion-shells.test.sh): Debian has none this old.
# Its own config.guess predates today's machines, so Debian's current one stands in
FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc AS bash32
RUN apt-get update \
    && apt-get install -y --no-install-recommends autotools-dev bison ca-certificates curl gcc libc6-dev make \
    && rm -rf /var/lib/apt/lists/*
ARG BASH32_SHA256=3fa9daf85ebf35068f090ce51283ddeeb3c75eb5bc70b1a4a7cb05868bfe06a4
RUN --mount=type=secret,id=extra_ca \
    if [ -s /run/secrets/extra_ca ]; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/extra_ca > /tmp/og-ca.pem; export CURL_CA_BUNDLE=/tmp/og-ca.pem; \
    fi; \
    curl -fsSL -o /tmp/bash.tar.gz https://ftp.gnu.org/gnu/bash/bash-3.2.57.tar.gz \
    && echo "$BASH32_SHA256  /tmp/bash.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/bash.tar.gz -C /tmp && cd /tmp/bash-3.2.57 \
    && cp /usr/share/misc/config.guess /usr/share/misc/config.sub support/ \
    && CFLAGS="-O2 -std=gnu89 -Wno-implicit-function-declaration -Wno-implicit-int -Wno-int-conversion" \
       ./configure --quiet --without-bash-malloc --disable-nls >/dev/null \
    && make -s -j"$(nproc)" >/dev/null 2>&1 \
    && install -m 755 bash /usr/local/bin/bash3.2 && /usr/local/bin/bash3.2 -c 'echo "bash $BASH_VERSION"'

FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc

# og's own needs (docs/setup.md): git and curl; jq, python3 and shellcheck for its shell tests;
# rsync, procps (kill, pkill) and ssh-keygen, which a Mac has built in and tests call; zsh and
# bash 3.2, the Mac's two shells, for completion
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git jq openssh-client procps python3 rsync shellcheck zsh \
    && rm -rf /var/lib/apt/lists/*
COPY --from=bash32 /usr/local/bin/bash3.2 /usr/local/bin/bash3.2

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

# a skipped pytest test fails (tests/conftest.py): here every tool a test needs is installed
ENV OG_NO_SKIPS=1
ENTRYPOINT ["tests/docker/entry.sh"]
