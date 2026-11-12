#!/usr/bin/env bash
# ogun template recipe: work — built as the image ogun-work:latest.
# The common base plus a Rust toolchain (rustup, cargo, rustc), minimal profile.
# Conventions (egress/scrub headers, how a recipe runs): home.sh.
#
# egress: sh.rustup.rs,static.rust-lang.org
# runtime-egress: index.crates.io,static.crates.io,*.rust-lang.org
# scrub: ~/.cargo/credentials.toml
#
# The build fetches rustup's installer and the toolchain; at runtime cargo reads the
# crates index and downloads crates, and rustup updates from the Rust project's hosts.
# A registry token, should anything write one, is scrubbed before the save.

curl -fsSL --proto '=https' --tlsv1.2 https://sh.rustup.rs -o /tmp/rustup-init.sh
sh /tmp/rustup-init.sh -y --profile minimal --no-modify-path
rm -f /tmp/rustup-init.sh
sudo ln -sf ~/.cargo/bin/cargo ~/.cargo/bin/rustc ~/.cargo/bin/rustup /usr/local/bin/

# the build fails here, and nothing is saved, if the toolchain did not install
cargo --version
rustc --version
