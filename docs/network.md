# Network

og's sandboxes reach the network only through sbx's proxy, which filters every sandbox's
outbound traffic: global rules, plus rules scoped to one sandbox, changed with
`og allow <name> <domain>…` and `og net`.

## Sandboxes: default-deny egress

Outbound traffic from a sandbox is blocked unless its domain is on the allowlist. The
allowlist has two layers: global rules that cover every sandbox (the baseline), and rules
scoped to one sandbox (what you approve).

- **Baseline.** Each create (and `ogun policy`) allows what setup needs: Debian mirrors,
  GitHub (pushes only to the sandbox's own repos, [below](#pushes-to-github)), npm, PyPI and Docker Hub read-only, and read-only the two apt
  repositories the sandbox image lists (Docker's and GitHub CLI's), and Docker's documentation
  (`docs.docker.com`), read-only too. The rest of AWS is left out
  ([below](#what-the-baseline-leaves-out)). It also takes out four of sbx's own default
  rules ([below](#sbxs-default-rules)). The lists are in og's `src/ogun/net/baseline.toml`, each
  with its reason; a `[baseline]` table in `config.toml` replaces them
  ([settings](appendix/flags-and-env.md#the-network-baseline)).
- **Containers inside a sandbox** go through a relay to the same proxy, so the same rules
  apply to them ([Docker inside a sandbox](sandboxes.md#docker-inside-a-sandbox)).
- **A blocked request** returns HTTP 403 naming the domain. What the agent does next is up to
  its instructions, which come with the provision command, not with og: a good one stops and
  reports the domains, why it needed them, and the `og allow` line to run
  ([Setting up og](setup.md#what-a-provision-command-should-tell-the-agent)).
- **You decide** on the Mac whether the domain should open. `og allow` names the sandbox
  that asked, so the domain opens to that sandbox only. Opening it to
  every sandbox takes an explicit `--all`, and a bare `ogun net <domain>` is refused:

```bash
ogun net cub example.com api.example.com          # one sandbox (og allow does the same)
ogun net --all example.com                        # every sandbox, only when that's the intent
ogun net cub github.com/acme/widgets              # let one sandbox push to one more GitHub repo
ogun net cub files.example.com --read-only        # reading only: downloads work, uploads and posts don't
ogun net cub                                      # what cub may reach or push to, and what's blocked
ogun net cub ads.example.com --deny               # block a domain for one sandbox (--all: every sandbox)
ogun net cub example.com --rm                     # remove the rule set for a domain, allow or block
ogun net cub github.com/acme/widgets --rm         # remove one repo's push
ogun net cub --log                                # what it tried to reach, blocked and allowed, newest first
ogun net cub example.com --check                  # would it be allowed, and for what? (exit 0 yes, 3 no)
ogun policy                                       # re-apply the baseline, every sandbox's push rules, the ssh-agent setting
ogun -v policy                                    # …showing each sbx command it runs and how it ended (-vv: what sbx printed too)
```

A block beats an allow: when a domain has both, it stays blocked until the block rule is
removed. `ogun allow` says so when it sees one, with the `ogun net … --rm` line, and removes nothing.

`ogun net` is the one command for a sandbox's network rules: bare, it lists them (a table:
each rule, allowed, read-only, blocked or a push, and whether for that sandbox or every
one; a push and a block are marked, and the rules every sandbox shares are dimmed so its own
stand out; the many rules sbx sets itself are counted at the foot, and `--sbx` lists them too); with domains or repos it allows them, as `ogun allow` does, blocks them (`--deny`) or
removes the rule set for each (`--rm`). A rule limited to a path or method shows it (the
baseline's clone rule reads `github.com/*/*/git-upload-pack  allowed (POST)`, never like a
whole-host allow). sbx lists two types: a host is a `network` rule, a host limited to a
method and path (a read-only allow, a push, the clone rule) an `http` rule; `ogun net` reads
both. `--rm` removes each matching rule by its id (naming the sandbox, for one of its own), with no y/N (typing it is the
decision), and nothing else: one repo's push is its two rules; `github.com` for one sandbox
is only its whole-host rule, never the pushes, the clone rule or an LFS allow. When the rule
also held other hosts (`ogun allow cub a.com b.com` makes one rule), those are set again as
they were.

`--read-only` allows only `GET` and `HEAD`, the rule npm and PyPI have. A sandbox can download
from the site, but it can't upload, post a form or call an API that writes. That's the better
answer when it only needs to read docs or fetch a file from a site that also accepts uploads.
It isn't a seal: the address of a `GET` can itself carry a little data, and the site's owner
sees every address asked for (the same leak as a stranger's S3 bucket, [below](#what-the-baseline-leaves-out)). So keep it for
sites you'd trust with that. If the same sandbox already has the whole site allowed, that rule
still lets everything through; `ogun allow` says so, with its removal line.

Template recipes declare the extra domains their build downloads from, allowed for the
build sandbox only, and the domains their sandboxes need at runtime, allowed for each such
sandbox at its create. See [Templates](templates.md#what-a-recipe-may-do). `og net <name>` shows the rules a sandbox
is under: the global ones and its own.

### What the baseline leaves out

A domain on the allowlist is only safe if no stranger can write to it. Otherwise a
prompt-injected agent can send your files there with the stranger's own credentials, and
the domain rule can't tell that apart from real work. The baseline keeps to two kinds of
host:

- **Download-only:** the Debian mirrors, and GitHub's raw, objects and codeload hosts.
- **Hosts where the proxy swaps in your credentials:** GitHub, and Claude's own API, which
  comes with the sandbox's kit. Whatever token the agent sends, the request goes out as
  you, so it can't write into a stranger's account.

Package registries don't qualify as whole hosts: the proxy holds no npm or PyPI secret, so
a token the agent brings goes through untouched, and a stranger's token could publish your
code. So npm (`registry.npmjs.org`) and PyPI (`pypi.org`, `files.pythonhosted.org`) are
allowed **read-only**, as sbx HTTP rules for `GET,HEAD`. Installs are GETs and work
everywhere. A publish is refused, and so is npm's audit, which is a POST: use
`npm install --no-audit` or approve it for that sandbox. PyPI's upload host,
`upload.pypi.org`, isn't allowed at all. Other registries (crates.io, Go modules, RubyGems…)
ask the first time a sandbox needs them.

AWS can't be made read-only the same way. Most AWS APIs send even their reads as POSTs, and
a GET to a stranger's bucket still leaks: the bucket's owner sees every path requested in
its access logs. `*.amazonaws.com` covers every S3 bucket, and a pre-signed upload link
needs no credentials at all. So a sandbox reaches AWS hosts only once you approve them for
it, the same way as any other blocked domain. A template that always needs them lists them
in its `# runtime-egress:` header. For AWS, approve the exact hosts asked for (`sts.<region>`,
`oidc.<region>`, `portal.sso.<region>`, a named bucket), never all of `*.amazonaws.com`.

When you approve a domain, ask "can a stranger write to this and read it back?", not only
"is this site legitimate?".

### Pushes to GitHub

The sandbox's GitHub token can write to every repo of its owner, public ones included. So a
tricked agent could push your private code into one of your own public repos, and the proxy
would send it as you. To stop that, every sandbox can read GitHub, but pushes only to its own
repos:

- **For every sandbox:** `github.com` read-only (`GET,HEAD`), plus the one `POST` a clone or
  fetch sends (`/*/*/git-upload-pack`). Cloning and pulling any repo works as before.
- **For each sandbox:** a push (`POST /<owner>/<repo>.git/git-receive-pack`, and the same
  without `.git`) to the GitHub remotes of the repo's checkout on the Mac, of each repo in
  its registry entry's `repos.write`, and to each address in its `repos.push`. A push
  anywhere else gets a 403 from the proxy.
- **One more repo:** `ogun allow <name> github.com/<owner>/<repo>` lets that sandbox push
  there until it's removed. For every future sandbox of the repo,
  `ogun project add https://github.com/<owner>/<repo>` adds the address to `repos.push`
  (the registry decides what sandboxes get). `ogun allow <name> github.com` on its own is refused: it
  would let that sandbox push anywhere again. So is any pattern that would also cover
  `github.com` (`*github.com`, `*.com`, `*.github.com`, `**`, `http://github.com`), for one
  sandbox or `--all`. `ogun policy` names each existing allow that covers it (a rule added
  by hand, or before this check), with its `ogun net … --rm` line, and removes none.
- **When:** at create, on every attach (so a remote added since gets its rule), and for
  every sandbox on `ogun policy`. The remotes are read on the Mac: the sandbox works in its
  own clone, and the write repos are mounted read-only, so it can't add a repo to its own list.

Not covered: `api.github.com` stays fully allowed, because `gh` needs it, and a pull request
or an issue goes through GitHub's GraphQL API, one address for everything, which a path rule
can't tell apart. [OpenAPPA](appa.md) covers those in interactive sessions. Git LFS
uploads and downloads aren't allowed either (their `POST` is on another path); approve them
for a sandbox if a repo needs LFS.

An allow that covers all of `github.com` (`github.com` itself, `*.com`, `**`), for every
sandbox or one, undoes the push limit wherever it applies, and sbx keeps an allow until it is
removed. `ogun policy` gives every sandbox its push rules first, then prints the
`ogun net … --rm` line for each such rule sbx lists, and leaves the removing to you.

### A repo's own egress

A repo can say which domains its sandboxes always need, in its entry in
og's registry (`registry.json` in its [config folder](config.md)). Edit the file;
`og allow` and `og net` stay the way to change one sandbox's rules right away.

```json
"web": {
  "owner": "personal",
  "egress": [
    { "hosts": ["api.orders.example"], "for": "orders in dev" },
    { "hosts": ["uploads.example.com", "*.cdn.example.com"], "write": true, "for": "file uploads" }
  ]
}
```

- **Reading only, unless `write` is true.** Without it a grant allows GET and HEAD, as
  npm's rule does. `write: true` allows the host whole, once this Mac approves it: the first
  create or attach that meets it asks once, and the answer, yes or no, is kept in ogun's
  state dir (`approved-egress`), outside every repo. Until it's yes (no terminal to ask at,
  or declined) the host is reachable reading only.
- **`for`** is the reason, shown in that question and kept in the sandbox's record.
- **The same gate as the entry's other grants:** it declares `owner`, that matches the path's,
  and the directory is the repo the entry describes. GitHub, and any pattern that covers it,
  is refused: reads are the baseline's, pushes `og project add`'s ([above](#pushes-to-github)).
- **Applied** at create and on every attach, and by `og policy` for every sandbox at once.
  A host the registry no longer grants is removed then, and one whose access changed
  (writes added or taken away) has its rule replaced. Only its allows go, never a block
  you set; only a host ogun applied from the registry (the sandbox's record says which);
  and never one its template or a secret grant also needs. So after a removal, run
  `og policy` to close it everywhere without waiting for attaches. A secret removed from a
  host a read-only grant still names doesn't leave its whole-host allow behind: the host
  goes back to reading only.

A template's `# runtime-egress:` is the other place domains come from: what the template's
tools need, for every repo using it. The registry's is what this repo needs.

### sbx's default rules

sbx's "Balanced" setup adds global rules of its own, created as `default`. Four of them
allow whole categories of host for every sandbox, and Ogun takes them out:

| sbx rule | What it allows | Why it's off |
|---|---|---|
| `default-ai-services` | OpenAI, Gemini, Cursor, Perplexity… | og needs none of them; Claude's hosts come with each sandbox's kit |
| `default-cloud-infrastructure` | all of AWS, Google APIs, Azure storage, Vercel, Supabase… | every storage bucket on three clouds, writable with a pre-signed link |
| `default-code-and-containers` | GitLab, Bitbucket, Docker Hub, Quay, other image registries | a stranger's token can push code or images there; the Docker and GitHub CLI apt repositories (`download.docker.com`, `cli.github.com`) come back read-only, because the sandbox image installs from them, and so does Docker Hub, so sandboxes pull images but can't push them |
| `default-package-managers` | every language's registry | a stranger's token can publish there; npm and PyPI come back read-only |

`default-os-packages` (Debian, Ubuntu, Alpine and Fedora mirrors) and
`default-cert-validation` (certificate status checks) stay: they're download-only.

An sbx upgrade may restore a rule Ogun keeps off. Every create, template build and
`ogun policy` removes it again, and so does **every attach** (`ogun <name>` on an existing
sandbox, or `ogun attach <name>`), saying so in one line. If sbx refuses the removal, the
attach stops and prints the by-hand line, so Claude never starts with the rule on.
