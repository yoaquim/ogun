"""What sandboxes may reach (docs/network.md): the baseline every sandbox gets,
sbx's own default rules removed, GitHub pushes per sandbox, the registry's
egress per sandbox, `og allow` and `og policy`, and the ssh-agent guard a create and `og policy` both run.

Rules are global and persistent in sbx and adding one twice keeps one copy, so
everything here is safe to re-run: a create, every attach and `og policy` do."""
