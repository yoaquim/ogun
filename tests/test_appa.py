"""appa: the OpenAPPA install. The pinned lock; og's appa/install.sh, the
script that runs inside a sandbox, run here against fake releases (curl hands back
a fixture archive, sudo installs into a scratch folder); and the call that runs it,
the release host allowed for that sandbox alone."""

import hashlib
import io
import os
import platform
import re
import subprocess
import tarfile

import pytest

from conftest import FIXTURES
from ogun.core import paths
from ogun.sandbox import appa

INSTALL = paths.SCRIPTS / "appa/install.sh"
BINARY = b"#!/bin/sh\necho 'appa 0.37.0'\n"


def test_the_lock_pins_a_release_tag_and_both_linux_archives_sha256(home, monkeypatch):
    monkeypatch.setattr("ogun.sandbox.appa.lock_file", lambda: FIXTURES / "appa.lock")
    assert re.fullmatch(r"v\d+\.\d+\.\d+", appa.lock("version"))
    for arch in ("aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu"):
        assert re.fullmatch(r"[0-9a-f]{64}", appa.lock(arch))


# ── the script ──

def archive(path, entries) -> str:
    """A .tgz of (name, kind, data) entries, written with tarfile so a hostile one can
    be written at all; its SHA-256."""
    with tarfile.open(path, "w:gz") as t:
        for name, kind, data in entries:
            i = tarfile.TarInfo(name)
            if kind == "link":
                i.type, i.linkname = tarfile.SYMTYPE, data
                t.addfile(i)
            else:
                i.size, i.mode = len(data), 0o755
                t.addfile(i, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


ARCHIVES = {
    "good": [("appa", "file", BINARY), ("LICENSE", "file", b"MIT\n")],
    "escape": [("appa", "file", BINARY), ("../evil", "file", b"x\n")],
    "abs": [("appa", "file", BINARY), ("/etc/evil", "file", b"x\n")],
    "link": [("appa", "link", "/bin/sh")],
    "nobin": [("README", "file", b"no binary here\n")],
}


@pytest.fixture
def release(tmp_path):
    """install.sh as a sandbox runs it, against a fixture archive: curl logs the URL
    and hands it back, sudo installs into dest; appa absent unless given a version.
    Returns run(archive name, sha=…, have=version) → (exit code, output, URLs, sudo calls)."""
    b, dest = tmp_path / "bin", tmp_path / "dest"
    b.mkdir()
    dest.mkdir()
    (b / "curl").write_text(f"""#!/bin/sh
out=""; while [ $# -gt 0 ]; do case "$1" in -o) out=$2; shift ;; https://*) echo "$1" >> "{tmp_path}/curl.log" ;; esac; shift; done
cp "$APPA_ARCHIVE" "$out"
""")
    (b / "sudo").write_text(f"""#!/bin/sh
echo "$*" >> "{tmp_path}/sudo.log"
[ "$1" = install ] && cp "$4" "{dest}/appa"
""")
    for f in ("curl", "sudo"):
        (b / f).chmod(0o755)

    def run(name, sha=None, have=None):
        for f in ("curl.log", "sudo.log"):
            (tmp_path / f).write_text("")
        (dest / "appa").unlink(missing_ok=True)
        (b / "appa").write_text(f'#!/bin/sh\necho "appa {have}"\n' if have else "#!/bin/sh\nexit 127\n")
        (b / "appa").chmod(0o755)
        built = archive(tmp_path / f"{name}.tgz", ARCHIVES[name])
        want = sha or built   # sha: what the lock says, when it isn't this archive's
        # a PATH without /usr/local/bin: an appa installed where the tests run would read as installed
        p = subprocess.run(["bash", str(INSTALL), "v0.37.0", want, want, appa.REPO], capture_output=True, text=True,
                           env={**os.environ, "APPA_ARCHIVE": str(tmp_path / f"{name}.tgz"), "PATH": f"{b}:/usr/bin:/bin"})
        return (p.returncode, p.stdout + p.stderr, (tmp_path / "curl.log").read_text().splitlines(),
                (tmp_path / "sudo.log").read_text().splitlines(), dest / "appa")

    return run


def test_a_good_archive_this_platforms_file_from_the_pinned_release_installed(release):
    code, _, urls, sudo, dest = release("good")
    arch = {"arm64": "aarch64", "amd64": "x86_64"}.get(platform.machine(), platform.machine())
    assert code == 0 and os.access(dest, os.X_OK)
    assert any(re.fullmatch(r"install -m 755 .*/appa /usr/local/bin/appa", x) for x in sudo)
    assert urls == [f"{appa.REPO}/releases/download/v0.37.0/appa-{arch}-unknown-linux-gnu.tar.gz"]


@pytest.mark.parametrize(("name", "sha", "says"), [
    ("good", "0" * 64, "does not match the SHA-256 in the lock"),
    ("escape", None, "entry outside its folder: ../evil"),
    ("abs", None, "entry outside its folder: /etc/evil"),
    ("link", None, "holds no appa binary"),     # a link, not a file
    ("nobin", None, "holds no appa binary"),
], ids=["checksum", "climbs out", "absolute", "a link", "no binary"])
def test_an_archive_that_isnt_exactly_the_pinned_one_installs_nothing(release, name, sha, says):
    code, out, _, sudo, _ = release(name, sha)
    assert code != 0 and sudo == [] and says in out


def test_an_appa_already_at_the_pinned_version_is_kept_with_no_download(release):
    code, out, urls, sudo, _ = release("good", have="0.37.0")
    assert code == 0 and urls == [] and sudo == [] and "already installed" in out


def test_an_older_one_is_replaced(release):
    code, _, urls, _, dest = release("good", have="0.36.0")
    assert code == 0 and urls and os.access(dest, os.X_OK)


# ── the call that runs it ──

@pytest.fixture
def locked(home, monkeypatch):
    monkeypatch.setattr("ogun.sandbox.appa.lock_file", lambda: FIXTURES / "appa.lock")


def test_the_install_allows_the_release_host_for_that_sandbox_only_and_passes_the_locks_values(fakes, locked):
    assert appa.install("box")
    assert ["policy", "allow", "network", "--sandbox", "box", "release-assets.githubusercontent.com"] in fakes.sbx.calls
    [run] = [c for c in fakes.sbx.calls if c[:1] == ["exec"]]
    assert run[-5:] == ["_", appa.lock("version"), appa.lock("aarch64-unknown-linux-gnu"),
                        appa.lock("x86_64-unknown-linux-gnu"), appa.REPO]


def test_an_install_that_fails_inside_the_sandbox_fails_the_call(fakes, locked, capfd):
    fakes.sbx.answer(["exec"], code=1)
    assert not appa.install("box")
    assert re.search(r"og: OpenAPPA \S+ could not be installed in box", capfd.readouterr().err)


def test_a_lock_without_a_version_and_both_hashes_stops_it_before_any_sbx_call(fakes, home, monkeypatch, tmp_path):
    (tmp_path / "bad.lock").write_text("version latest\n")
    monkeypatch.setattr("ogun.sandbox.appa.lock_file", lambda: tmp_path / "bad.lock")
    assert not appa.install("box")
    assert fakes.sbx.calls == []


# ── the registry's appa.private: the other places a protected sandbox counts as private ──

def test_a_host_path_off_github_is_passed_github_a_scheme_and_dotdot_are_refused_each_said(recipes, capfd):
    (recipes / "Projects/personal/archive").mkdir()
    assert appa.private(str(recipes / "Projects/personal/archive")) == ["gitlab.example.com/me/fixtures"]
    err = capfd.readouterr().err
    assert "'github.com/me/notes' is on GitHub" in err
    assert "'https://x.example/y' must be host/path" in err and "'git.example.com/../etc' must be host/path" in err


def test_under_the_owner_gate_another_owners_entry_or_a_folder_that_isnt_the_repo_gets_none(recipes, capfd):
    for d in ("Projects/personal/stray", "elsewhere/archive"):
        (recipes / d).mkdir(parents=True)
    assert appa.private(str(recipes / "Projects/personal/stray")) == []
    assert "for owner 'umbrella'" in capfd.readouterr().err
    assert appa.private(str(recipes / "elsewhere/archive")) == []
    assert "not the repo it describes" in capfd.readouterr().err
    assert appa.private(str(recipes / "Projects/personal/plain")) == []
    assert "".join(capfd.readouterr()) == ""   # no key: nothing said


# ── the scripts that turn it on and check it: sent in, never from a host mount ──

def bundle_files(text: str) -> dict:
    import base64
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(text)), mode="r:gz") as t:
        return {m.name: (t.extractfile(m).read(), m.mode) for m in t.getmembers()}


def test_an_appa_script_goes_in_as_a_bundle_on_stdin_never_from_a_host_mount(fakes, home):
    appa.script("box", "ensure.sh", wait="checking")
    c = fakes.sbx.calls[-1]
    assert c[:4] == ["exec", "-i", "box", "bash"] and c[-1] == "ensure.sh" and "OG_PROVISION_CMD=" in c[5]
    got = bundle_files(fakes.sbx.stdin[-1])
    assert sorted(got) == ["activate.sh", "ensure.sh", "policy.py"]
    for name, (body, mode) in got.items():
        assert body == (paths.SCRIPTS / "appa" / name).read_bytes() and (not name.endswith(".sh") or mode & 0o100)


def test_the_bundle_runs_from_a_fresh_folder_that_goes_after(home, tmp_path):
    t = tmp_path / "t"
    t.mkdir()
    p = subprocess.run(["bash", "-c", appa.runner(""), "ensure.sh"], input=appa.bundle(), capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(t)})
    assert p.returncode == 3 and "never turned on" in p.stderr   # ensure.sh ran: no marker in this home
    assert list(t.iterdir()) == []


def test_activation_is_told_ogs_provision_command_by_og_never_by_the_sandbox(home, monkeypatch):
    monkeypatch.setenv("OG_PROVISION", "~/setup-repo/provision.sh --all")
    assert appa.runner(appa._provision()).startswith(f"OG_PROVISION_CMD='{home}/setup-repo/provision.sh --all' ")
    assert "OG_PROVISION_CMD='' " in appa.runner("") and "OG_PROVISION_CMD='a b' " in appa.runner("a b")


def probe_bundle(tmp_path) -> str:
    """A bundle holding one script that prints what it was told to provision with."""
    import base64
    (tmp_path / "probe.sh").write_text('printf "%s\\n" "${OG_PROVISION_CMD-unset}" "$@"\n')
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        t.add(tmp_path / "probe.sh", arcname="probe.sh")
    return base64.b64encode(buf.getvalue()).decode()


@pytest.mark.parametrize("cmd", ["/srv/me/agent-config/provision.sh --all", ""])
@pytest.mark.parametrize("planted", [{"OG_PROVISION_CMD": "/planted/by/the/sandbox"}, {}], ids=["sandbox sets one", "sandbox sets none"])
def test_the_script_gets_ogs_provision_command_over_the_sandboxs_own_and_its_arguments(tmp_path, cmd, planted):
    p = subprocess.run(["bash", "-c", appa.runner(cmd), "probe.sh", "a b", "c"], input=probe_bundle(tmp_path), capture_output=True,
                       text=True, env={"PATH": "/usr/bin:/bin", "TMPDIR": str(tmp_path), **planted})
    assert p.returncode == 0 and p.stdout.splitlines() == [cmd, "a b", "c"]
