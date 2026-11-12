"""The file exchange (docs/exchange.md): og give, take, scan and tidy, and
the checks every file a sandbox wrote goes through before it reaches the Mac.

Everything in out/ and shared/, its names and its bytes, was written by a sandbox
that may be hijacked. So nothing is used before it's checked, nothing is changed
where the sandbox can still reach it, and whatever fails a check is moved to the
exchange's .quarantine/<name>/ (never mounted), not deleted."""
