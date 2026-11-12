#!/usr/bin/env bash
# ogun template recipe: orders — built as the image ogun-orders:latest.
# An invented recipe for og's tests: an orders service whose tests run against a
# staging API and a local PostgreSQL; the common base plus the PostgreSQL client.
# Conventions (egress/scrub headers, how a recipe runs): home.sh.
#
# runtime-egress: api.orders.example
# scrub: ~/.psql_history ~/.pgpass
# appa: on
#
# The staging key comes from og's registry, never the image (ORDERS_API_KEY, granted
# to this repo's sandboxes on api.orders.example). Customer records pass through the
# repo's tests, hence OpenAPPA.

command -v psql >/dev/null || sudo apt-get install -y postgresql-client

# the build fails here, and nothing is saved, if the client did not install
psql --version >/dev/null
