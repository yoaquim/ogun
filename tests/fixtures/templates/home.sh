#!/usr/bin/env bash
# ogun template recipe: home — built as the image ogun-home:latest.
#
# The common base (apt tools, AWS CLI, Claude Code, the scrub) is all this
# recipe's sandboxes need, so it adds nothing: a recipe can be the base alone.
#
# The recipe convention, for every file in this folder (`ogun template <name>`
# builds templates/<name>.sh, in og's config folder, into ogun-<name>:latest):
#   - runs INSIDE the build sandbox (golden-<name>) as the agent user, after
#     the common base, as `bash -l` with `set -euo pipefail` already on; any
#     failing command fails the build and nothing is saved
#   - header lines the builder reads, anywhere in the leading comment block:
#       # egress: <domain>[,<domain>…]   extra domains the build downloads from,
#                                        allowed for the build sandbox only
#       # runtime-egress: <domain>[,…]   domains a sandbox made from the
#                                        template needs, allowed per sandbox
#                                        at its create
#       # scrub: <path> [<path>…]        extra paths deleted before the save
#                                        (credentials or state a tool leaves)
#   - no logins, no secrets, no per-repo setup: a template is shared by every
#     sandbox created from it

true
