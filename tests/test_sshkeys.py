"""sshkeys: what keeps the Mac's signing key out of every sandbox. The probe that
proves a sandbox reaches no ssh-agent (sbx's setting can read off before the daemon
applies it), and the one host folder (~/.ssh/sandbox) every sandbox mounts
read-only: refused while it holds a key SBX_PROTECTED_KEYS keeps out or a symlink. Then
og's sandbox-ssh.sh, the setup that runs inside the sandbox, run here against
a scratch HOME. Real ssh-keygen, throwaway keys."""

import os
import shutil
import socket
import struct
import subprocess
import tempfile
import threading

import pytest

from ogun.core import paths
from ogun.secrets import sshkeys

SCRIPT = paths.SCRIPTS / "sandbox-ssh.sh"
FP = {"ssh-ed25519": "SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU",
      "ecdsa-sha2-nistp256": "SHA256:p2QAMXNIC1TJYWeIOttrVc98/R1BUFWu3/LiyKgUfQM",
      "ssh-rsa": "SHA256:uNiVztksCsDhcc0u9e8BujQXVUpKZIDTMczCvj3tD2s"}


# ── the probe: a sandbox must reach no agent ──

def probed(fakes, out="agent:none\n", code=0, err=""):
    fakes.sbx.answer(["exec", "box"], stdout=out, stderr=err, code=code)


def test_a_sandbox_that_reaches_no_agent_passes(fakes):
    probed(fakes)
    assert sshkeys.agent_absent("box")


@pytest.mark.parametrize("out", ["agent:present\n", ""], ids=["sees the socket", "answers nothing"])
def test_one_that_sees_the_agent_or_answers_nothing_is_refused_naming_the_restart(fakes, capfd, out):
    probed(fakes, out)
    assert not sshkeys.agent_absent("box")
    err = capfd.readouterr().err
    assert "sbx daemon restart" in err and "can reach the Mac's ssh-agent (and every key it holds)" in err


def test_a_failed_exec_is_refused_with_sbxs_error_never_the_restart(fakes, capfd):
    probed(fakes, "", 1, 'error: cannot start sandbox: workspace directory "/x/gone" no longer exists on the host\n')
    assert not sshkeys.agent_absent("box")
    err = capfd.readouterr().err
    assert 'workspace directory "/x/gone" no longer exists' in err and "could not run" in err
    assert "daemon restart" not in err


# sbx's gateway answers the agent protocol on a TCP port as well as through the socket, so a
# sandbox with no socket can still reach it. A fake answers REQUEST_IDENTITIES with an empty
# IDENTITIES_ANSWER (type 12).

def _agent(sock: socket.socket) -> None:
    while True:
        try:
            c, _ = sock.accept()
        except OSError:
            return
        with c:
            c.recv(64)
            c.sendall(struct.pack(">IBI", 5, 12, 0))


@pytest.fixture
def agents():
    # a socket path has a hard limit (104 bytes on macOS), which pytest's per-test
    # folder under the Mac's temp dir passes: the socket gets a short folder of its own
    d = tempfile.mkdtemp(prefix="og-", dir="/tmp")
    sock = os.path.join(d, "agent.sock")
    tcp = socket.socket()
    tcp.bind(("127.0.0.1", 0))
    unix = socket.socket(socket.AF_UNIX)
    unix.bind(sock)
    for s in (tcp, unix):
        s.listen(4)
        threading.Thread(target=_agent, args=(s,), daemon=True).start()
    yield f"127.0.0.1:{tcp.getsockname()[1]}", sock
    tcp.close()
    unix.close()
    shutil.rmtree(d, ignore_errors=True)


def probe(**env) -> str:
    """The probe og sends, run here: no real socket, gateway or agent unless given."""
    base = {k: v for k, v in os.environ.items() if k not in ("SSH_AUTH_SOCK", "SSH_AUTH_SOCK_GATEWAY")}
    base.update({"SBX_AGENT_SOCK": "", "SBX_AGENT_GATEWAY": "127.0.0.1:1"}, **env)
    return subprocess.run(["bash", "-c", sshkeys.PROBE], env=base, capture_output=True, text=True).stdout.strip()


def test_the_probe_reports_none_when_nothing_answers():
    assert probe() == "agent:none"


@pytest.mark.parametrize("where", ["SBX_AGENT_GATEWAY", "SSH_AUTH_SOCK_GATEWAY", "SSH_AUTH_SOCK", "SBX_AGENT_SOCK"],
                         ids=["gateway port only", "the gateway's named address", "SSH_AUTH_SOCK", "sbx's fixed socket"])
def test_the_probe_finds_an_agent_wherever_it_answers(agents, where):
    tcp, sock = agents
    assert probe(**{where: tcp if "GATEWAY" in where else sock}) == "agent:present"


# ── the key folder: no protected key, no symlink ──

def keygen(path, comment, pw=""):
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", pw, "-C", comment, "-f", str(path)], check=True)


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    k = tmp_path_factory.mktemp("keys")
    for name, pw in (("signer", ""), ("peer", ""), ("allowed", ""), ("deploy", ""), ("locked", "secret-pw"),
                     ("signing", ""), ("signing-locked", "pw")):
        keygen(k / name, name, pw)
    return k


@pytest.fixture
def ssh(tmp_path, keys, monkeypatch):
    """SBX_SSH_DIR: the Mac's ~/.ssh, a key it signs with and a signers file, which
    SBX_PROTECTED_KEYS names, git's own allowed_signers, and an empty sandbox folder."""
    s = tmp_path / "ssh"
    (s / "sandbox").mkdir(parents=True)
    for f in ("signer", "signer.pub"):
        (s / f).write_bytes((keys / f).read_bytes())
    (s / "peer_signers").write_text(f'me@mac namespaces="git" {(keys / "peer.pub").read_text()}')
    (s / "allowed_signers").write_text(f'# comment\nme@mac {(keys / "allowed.pub").read_text()}')
    monkeypatch.setenv("SBX_SSH_DIR", str(s))
    monkeypatch.setenv("SBX_PROTECTED_KEYS", f"{s}/signer:{s}/peer_signers:{s}/allowed_signers")
    return s


def put(ssh, keys, *names, as_=None):
    for n in names:
        (ssh / "sandbox" / (as_ or n)).write_bytes((keys / n).read_bytes())


def refused(capfd, text) -> bool:
    ok = sshkeys.keys_check()
    return not ok and text in capfd.readouterr().err


def test_no_folder_nothing_to_refuse(ssh):
    (ssh / "sandbox").rmdir()
    assert sshkeys.keys_check()


def test_an_unrelated_key_is_accepted_beside_a_locked_key_and_a_non_key_file_never_prompting(ssh, keys):
    put(ssh, keys, "deploy", "deploy.pub", "locked", "locked.pub")
    (ssh / "sandbox/README").write_text("notes\n")
    assert sshkeys.keys_check()


def test_a_protected_key_is_refused_naming_the_file_and_what_protects_it(ssh, keys, capfd):
    put(ssh, keys, "signer", as_="id")
    assert refused(capfd, f"og: {ssh}/sandbox/id is the key in {ssh}/signer, which SBX_PROTECTED_KEYS keeps out")


def test_its_public_key_too(ssh, keys, capfd):
    put(ssh, keys, "signer.pub", as_="id.pub")
    assert refused(capfd, f"is the key in {ssh}/signer")


def test_even_behind_a_pub_that_names_another_key(ssh, keys, capfd):
    put(ssh, keys, "signer", as_="id")
    put(ssh, keys, "deploy.pub", as_="id.pub")
    assert refused(capfd, f"{ssh}/sandbox/id is the key in {ssh}/signer")


@pytest.mark.parametrize(("key", "named"), [("peer", "peer_signers"), ("allowed.pub", "allowed_signers")])
def test_a_key_a_protected_signers_file_trusts_is_refused(ssh, keys, capfd, key, named):
    put(ssh, keys, key, as_="k" if "." not in key else "k.pub")
    assert refused(capfd, f"is a key {ssh}/{named} trusts")


def test_a_signers_file_whose_first_principal_starts_like_a_key_type_still_protects_every_key(ssh, keys, capfd):
    (ssh / "peer_signers").write_text(f'ssh-user@example.com {(keys / "deploy.pub").read_text()}'
                                         f'me@mac namespaces="git" {(keys / "peer.pub").read_text()}')
    put(ssh, keys, "peer", as_="k")
    assert refused(capfd, f"is a key {ssh}/peer_signers trusts")
    (ssh / "sandbox/k").unlink()
    put(ssh, keys, "deploy", as_="first")   # the key on that principal's own line, too
    assert refused(capfd, f"is a key {ssh}/peer_signers trusts")


@pytest.mark.parametrize(("text", "key"), [
    ("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n", True),
    ("ssh-ed25519 AAAA me", True), ("ssh-rsa AAAA me", True), ("ecdsa-sha2-nistp384 AAAA", True),
    ("sk-ssh-ed25519@openssh.com AAAA", True), ("ssh-ed25519-cert-v01@openssh.com AAAA", True),
    ("# a comment first\n\nssh-ed25519 AAAA", True),
    ("ssh-user@example.com ssh-ed25519 AAAA", False), ("me@mac namespaces=\"git\" ssh-ed25519 AAAA", False),
    ("ecdsa-team@example.com ssh-ed25519 AAAA", False), ("# only a comment\n", False), ("", False),
])
def test_a_key_file_is_told_from_a_signers_file_by_its_first_whole_word(tmp_path, text, key):
    f = tmp_path / "f"
    f.write_text(text)
    assert sshkeys.is_key_file(f) is key


def test_unset_git_s_own_allowed_signers_is_protected_and_nothing_else(ssh, keys, capfd, monkeypatch):
    monkeypatch.delenv("SBX_PROTECTED_KEYS")
    put(ssh, keys, "signer", as_="id")
    assert sshkeys.keys_check()
    put(ssh, keys, "allowed.pub", as_="k.pub")
    assert refused(capfd, f"is a key {ssh}/allowed_signers trusts")


def test_a_protected_file_that_isnt_there_protects_nothing_and_stops_nothing(ssh, keys, monkeypatch):
    monkeypatch.setenv("SBX_PROTECTED_KEYS", f"{ssh}/gone:{ssh}/signer")
    put(ssh, keys, "deploy")
    assert sshkeys.keys_check()


def test_a_protected_path_that_isnt_a_full_path_stops_og_naming_it(ssh, monkeypatch):
    from ogun.core import settings
    monkeypatch.setenv("SBX_PROTECTED_KEYS", "signer")
    with pytest.raises(settings.Unreadable, match="SBX_PROTECTED_KEYS"):
        sshkeys.protected_keys()


def test_a_symlink_in_the_folder_is_refused_at_any_depth(ssh, keys, capfd):
    put(ssh, keys, "deploy")
    (ssh / "sandbox/sub").mkdir()
    (ssh / "sandbox/sub/link").symlink_to(keys / "deploy")
    assert refused(capfd, "symlink")


def test_a_symlinked_folder_is_never_mounted(ssh, tmp_path):
    (ssh / "sandbox").rmdir()
    (tmp_path / "elsewhere").mkdir()
    (ssh / "sandbox").symlink_to(tmp_path / "elsewhere")
    assert sshkeys.keys_dir(quiet=True) == ""


# ── inside the sandbox: sandbox-ssh.sh ──

def fingerprints(lines: str) -> list[str]:
    out = subprocess.run(["ssh-keygen", "-lf", "-"], input=lines, capture_output=True, text=True).stdout
    return sorted(x.split()[1] for x in out.splitlines())


@pytest.mark.parametrize(("kind", "fp"), FP.items())
def test_the_pinned_github_host_keys_hash_to_githubs_published_fingerprints(kind, fp):
    [line] = [x for x in SCRIPT.read_text().splitlines() if x.startswith(f"github.com {kind} ")]
    assert fingerprints(line.split(" ", 1)[1]) == [fp]


def setup(home, mount, **env):
    return subprocess.run(["bash", str(SCRIPT), str(mount)], capture_output=True, text=True,
                          env={**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": "", **env})


def mode(p) -> int:
    return p.stat().st_mode & 0o777


@pytest.fixture
def mount(tmp_path, keys):
    """The mounted folder, its keys at the host's modes, and a sandbox HOME with a
    known_hosts holding another host and a stale github.com line."""
    m = tmp_path / "mount"
    m.mkdir()
    for n in ("deploy", "deploy.pub", "locked"):
        (m / n).write_bytes((keys / n).read_bytes())
    (m / "stray.pub").write_bytes((keys / "allowed.pub").read_bytes())
    (m / "README").write_text("notes\n")
    for n in ("deploy", "locked"):
        (m / n).chmod(0o644)
    h = tmp_path / "home"
    (h / ".ssh").mkdir(parents=True)
    (h / ".ssh/known_hosts").write_text("example.com ssh-ed25519 AAAAexample\ngithub.com ssh-rsa AAAAstale\n")
    return m, h


def test_private_keys_are_copied_0600_with_their_pub_nothing_else(mount):
    m, h = mount
    assert setup(h, m).returncode == 0
    k = h / ".ssh/sandbox-keys"
    assert mode(k / "deploy") == 0o600 and mode(k / "locked") == 0o600 and mode(h / ".ssh") == 0o700
    assert (k / "deploy.pub").is_file() and not (k / "README").exists() and not (k / "stray.pub").exists()
    assert (k / "deploy").read_bytes() == (m / "deploy").read_bytes()


def test_ssh_config_is_an_agent_less_github_block_one_identity_file_per_key(mount):
    m, h = mount
    setup(h, m)
    lines = (h / ".ssh/config").read_text().splitlines()
    for want in ("Host github.com", "    User git", "    IdentitiesOnly yes", "    IdentityAgent none",
                 f'    IdentityFile "{h}/.ssh/sandbox-keys/deploy"', f'    IdentityFile "{h}/.ssh/sandbox-keys/locked"'):
        assert want in lines
    assert sum("IdentityFile" in x for x in lines) == 2


def test_known_hosts_the_three_pinned_keys_replace_any_github_line_other_hosts_kept(mount):
    m, h = mount
    setup(h, m)
    kh = (h / ".ssh/known_hosts").read_text()
    gh = [x for x in kh.splitlines() if x.startswith("github.com ")]
    assert "example.com " in kh and "AAAAstale" not in kh and len(gh) == 3
    assert fingerprints("\n".join(gh) + "\n") == sorted(FP.values())


def test_a_second_run_changes_nothing(mount):
    m, h = mount
    setup(h, m)
    before = {p: p.read_bytes() for p in (h / ".ssh").rglob("*") if p.is_file()}
    assert setup(h, m).returncode == 0
    assert {p: p.read_bytes() for p in (h / ".ssh").rglob("*") if p.is_file()} == before


def test_with_no_private_key_left_its_copies_and_config_are_removed(mount):
    m, h = mount
    setup(h, m)
    (m / "deploy").unlink()
    (m / "locked").unlink()
    assert setup(h, m).returncode == 0
    assert not (h / ".ssh/sandbox-keys").exists() and not (h / ".ssh/config").exists()


def test_a_hand_made_config_is_kept_aside_and_a_second_one_too(mount):
    m, h = mount
    (h / ".ssh/config").write_text("Host first\n")
    setup(h, m)
    assert (h / ".ssh/config.pre-ogun").read_text() == "Host first\n"
    assert "Host github.com" in (h / ".ssh/config").read_text()
    (h / ".ssh/config").write_text("Host second\n")
    setup(h, m)
    assert (h / ".ssh/config.pre-ogun.1").read_text() == "Host second\n"
    assert "Host github.com" in (h / ".ssh/config").read_text()


def test_no_mount_ssh_left_unset(tmp_path):
    h = tmp_path / "h"
    h.mkdir()
    assert setup(h, tmp_path / "no-such-mount").returncode == 0
    assert not (h / ".ssh/config").exists()


# ── a key named signing: commit signing, not login ──

def gcfg(home, key) -> str:
    return subprocess.run(["git", "config", "--file", str(home / ".config/git/config"), "--get", key],
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def signing(tmp_path, keys, no_system_git):
    """A mount with a login key and a key named signing, whose .pub beside it names
    another key; and a fresh HOME."""
    m, h = tmp_path / "mount-sign", tmp_path / "sign-home"
    m.mkdir()
    h.mkdir()
    (m / "deploy").write_bytes((keys / "deploy").read_bytes())
    (m / "signing").write_bytes((keys / "signing").read_bytes())
    (m / "signing.pub").write_bytes((keys / "deploy.pub").read_bytes())
    return m, h


@pytest.fixture
def no_system_git(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def test_a_key_named_signing_turns_on_commit_signing_its_pub_derived_left_out_of_login(signing, keys):
    m, h = signing
    assert setup(h, m).returncode == 0
    assert gcfg(h, "gpg.format") == "ssh" and gcfg(h, "commit.gpgsign") == "true"
    assert gcfg(h, "user.signingkey") == f"{h}/.ssh/sandbox-keys/signing.pub"
    derived = (h / ".ssh/sandbox-keys/signing.pub").read_text().split()[:2]
    assert derived == (keys / "signing.pub").read_text().split()[:2]
    config = (h / ".ssh/config").read_text()
    assert config.count("IdentityFile") == 1 and "sandbox-keys/signing" not in config


def test_and_a_commit_made_there_is_signed(signing, tmp_path):
    m, h = signing
    setup(h, m)
    r = tmp_path / "repo"
    env = {**os.environ, "HOME": str(h), "XDG_CONFIG_HOME": ""}
    subprocess.run(["git", "init", "-q", str(r)], check=True, env=env)
    subprocess.run(["git", "-C", str(r), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                    "-m", "signed"], check=True, env=env)
    out = subprocess.run(["git", "-C", str(r), "cat-file", "commit", "HEAD"], capture_output=True, text=True, env=env).stdout
    assert "-----BEGIN SSH SIGNATURE-----" in out


def test_signing_alone_turns_signing_on_with_no_login_block(signing):
    m, h = signing
    (m / "deploy").unlink()
    (m / "signing.pub").unlink()
    assert setup(h, m).returncode == 0
    assert gcfg(h, "commit.gpgsign") == "true" and not (h / ".ssh/config").exists()


def test_a_passphrase_protected_signing_key_is_refused_loudly_and_signing_stays_off(signing, keys):
    m, h = signing
    (m / "signing").write_bytes((keys / "signing-locked").read_bytes())
    p = setup(h, m)
    assert p.returncode == 0
    assert "has a passphrase" in p.stdout + p.stderr and "NOT signed" in p.stdout + p.stderr
    assert gcfg(h, "commit.gpgsign") == ""


def test_the_signing_key_removed_its_three_settings_go(signing):
    m, h = signing
    setup(h, m)
    (m / "signing").unlink()
    (m / "signing.pub").unlink()
    assert setup(h, m).returncode == 0
    assert gcfg(h, "user.signingkey") == gcfg(h, "gpg.format") == gcfg(h, "commit.gpgsign") == ""


def test_even_with_one_already_removed_by_hand_and_the_rest_of_setup_still_runs(signing):
    m, h = signing
    setup(h, m)
    subprocess.run(["git", "config", "--file", str(h / ".config/git/config"), "--unset", "commit.gpgsign"], check=True)
    (m / "signing").unlink()
    assert setup(h, m).returncode == 0
    assert gcfg(h, "user.signingkey") == gcfg(h, "gpg.format") == ""
    assert not (h / ".ssh/sandbox-keys/signing").exists()
    assert f'    IdentityFile "{h}/.ssh/sandbox-keys/deploy"' in (h / ".ssh/config").read_text().splitlines()


def test_settings_naming_another_key_are_left_alone(tmp_path):
    m, h = tmp_path / "none", tmp_path / "mine"
    m.mkdir()
    (h / ".config/git").mkdir(parents=True)
    cfg = str(h / ".config/git/config")
    subprocess.run(["git", "config", "--file", cfg, "user.signingkey", "/elsewhere/me.pub"], check=True)
    subprocess.run(["git", "config", "--file", cfg, "commit.gpgsign", "true"], check=True)
    assert setup(h, m).returncode == 0
    assert gcfg(h, "user.signingkey") == "/elsewhere/me.pub" and gcfg(h, "commit.gpgsign") == "true"
