"""base: a sandbox's setup (create, and attach --sync), and the Claude Code update
it runs. Setup stops before anything runs when the sandbox can reach the Mac's
ssh-agent; sets ssh up only from a key folder that passes its check, every time;
and brings Claude Code to the latest release first, best effort and bounded. Then
og's sandbox-docker.sh, the Docker relay setup that runs inside the sandbox,
run here against a scratch HOME (it reads /proc: Linux only)."""

import base64
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ogun.core import paths
from ogun.sandbox import base
from ogun.secrets import sshkeys

# ── setup ──


@pytest.fixture
def box(fakes, home, monkeypatch):
    """Sandbox box, reaching no agent, with no key folder; provisioned by a provision
    command."""
    monkeypatch.setenv("SBX_PROVISION", "~/agent-config/provision.sh --all")
    monkeypatch.setenv("SBX_SSH_DIR", str(home / "ssh"))
    monkeypatch.setenv("SBX_EXCHANGE", str(home / "exchange"))
    fakes.sbx.answer(["exec", "box"], stdout="agent:none\n", has=sshkeys.PROBE)
    return fakes.sbx


def ran(s, text: str) -> list[int]:
    """The positions of the calls that hold text."""
    return [i for i, c in enumerate(s.calls) if text in " ".join(c)]


def test_setup_stops_before_anything_runs_when_the_sandbox_sees_the_agent(fakes, home, monkeypatch):
    monkeypatch.setenv("SBX_SSH_DIR", str(home / "ssh"))
    fakes.sbx.answer(["exec", "box"], stdout="agent:present\n", has=sshkeys.PROBE)
    assert base.setup("box") is False
    assert len(fakes.sbx.calls) == 1


def test_setup_sets_ssh_up_only_when_the_key_folder_exists(box, home):
    assert base.setup("box")
    assert not ran(box, "sandbox-ssh.sh")
    (home / "ssh/sandbox").mkdir(parents=True)
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(home / "ssh/sandbox/deploy")], check=True)
    assert base.setup("box")
    assert ran(box, "sandbox-ssh.sh")


def test_setup_refuses_copying_nothing_when_a_protected_key_has_appeared_there(box, home, monkeypatch):
    (home / "ssh/sandbox").mkdir(parents=True)
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(home / "ssh/signer")], check=True)
    monkeypatch.setenv("SBX_PROTECTED_KEYS", str(home / "ssh/signer"))
    shutil.copy(home / "ssh/signer", home / "ssh/sandbox/id")
    assert base.setup("box") is False
    assert not ran(box, "sandbox-ssh.sh")


def test_og_v_shows_each_sbx_call_setup_makes(box, capfd, monkeypatch):
    monkeypatch.setenv("OGUN_VERBOSE", "1")
    assert base.setup("box")
    out = "".join(capfd.readouterr())
    assert "$ sbx exec box bash -lc 'sudo apt-get" in out and "$ sbx exec box bash -lc 'mkdir -p ~/.config/sbx" in out


def test_setup_runs_the_docker_relay_in_the_sandbox(box):
    base.setup("box")
    c = next(c for c in box.calls if "sandbox-docker.sh" in c)
    assert c[4] == (paths.SCRIPTS / "sandbox-docker.sh").read_text() and "agent-config" not in " ".join(c)


def test_setup_stops_when_the_images_apt_never_finishes_nothing_after_it_runs(box):
    box.answer(["exec", "box"], code=1, has="sudo fuser")
    assert base.setup("box") is False and not ran(box, "apt-get") and not ran(box, "agent-config/provision.sh")


def test_setup_stops_when_the_claude_config_fails_nothing_after_it_runs(box, capfd):
    box.answer(["exec", "box"], code=1, has="agent-config/provision.sh")
    assert base.setup("box") is False and "the provision command failed" in "".join(capfd.readouterr())
    assert not ran(box, "sandbox-docker.sh")


# ── setup's parts: the apt tools, the ssh keys ──

def test_apt_tools_wait_for_the_images_own_apt_and_a_lock_never_freed_stops_setup(box):
    box.answer(["exec", "box"], code=1, has="sudo fuser")
    assert base.apt_tools("box") is False and not ran(box, "apt-get")


def test_apt_tools_failing_is_said_and_setup_goes_on(box, capfd):
    box.answer(["exec", "box"], stdout="E: 403 Blocked\n", code=1, has="apt-get")
    assert base.apt_tools("box") is True and ran(box, "apt-get")
    out = "".join(capfd.readouterr())
    assert "apt failed, so it goes on without" in out and "og policy" in out and "403 Blocked" in out


def test_a_docker_relay_that_fails_says_why_and_setup_goes_on(box, capfd):
    box.answer(["exec", "box"], stderr="sandbox-docker: socat is missing\n", code=1, has="sandbox-docker.sh")
    assert base.setup("box")
    out = "".join(capfd.readouterr())
    assert "docker relay setup failed" in out and "sandbox-docker: socat is missing" in out


def test_ssh_keys_with_no_folder_set_nothing_up(box):
    assert base.ssh_keys("box") is True and box.calls == []


def test_ssh_keys_from_the_folder_are_set_up_a_failure_said_and_setup_goes_on(box, home, capfd):
    (home / "ssh/sandbox").mkdir(parents=True)
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(home / "ssh/sandbox/deploy")], check=True)
    assert base.ssh_keys("box") is True and ran(box, "sandbox-ssh.sh")
    c = next(c for c in box.calls if "sandbox-ssh.sh" in c)
    assert c[4] == (paths.SCRIPTS / "sandbox-ssh.sh").read_text() and "agent-config" not in " ".join(c)
    box.answer(["exec", "box"], code=1, has="sandbox-ssh.sh")
    assert base.ssh_keys("box") is True and "ssh key setup failed" in "".join(capfd.readouterr())


def test_ssh_keys_stop_setup_when_a_protected_key_is_in_the_folder(box, home, monkeypatch):
    (home / "ssh/sandbox").mkdir(parents=True)
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(home / "ssh/signer")], check=True)
    monkeypatch.setenv("SBX_PROTECTED_KEYS", str(home / "ssh/signer"))
    shutil.copy(home / "ssh/signer", home / "ssh/sandbox/id")
    assert base.ssh_keys("box") is False and not ran(box, "sandbox-ssh.sh")


def test_an_exchange_place_that_cant_be_recorded_says_what_misses_it(box, capfd):
    box.answer(["exec", "box"], code=1, has="exchange-shared-root")
    assert base.setup("box")
    assert "couldn't record the exchange's place, so og ship's script in box won't find its out/" in "".join(capfd.readouterr())


# ── what every sandbox gets: og's own tools, and only what the settings add ──


def test_setup_installs_only_ogs_own_apt_tools_by_default(box):
    assert base.setup("box")
    assert ran(box, "install -y -qq jq socat 2>&1")


def test_the_apt_tools_setting_adds_its_own_after_ogs(box, monkeypatch):
    monkeypatch.setenv("SBX_APT_TOOLS", "make  htop jq")
    assert base.setup("box")
    assert ran(box, "install -y -qq jq socat make htop")


# ── the Claude Code update: first, best effort, bounded ──

UPDATED = "Successfully updated\nv 2.1.277 2.1.280\n"


def test_setup_updates_claude_before_its_config_printing_before_and_after(box, capfd):
    box.answer(["exec", "box"], stdout=UPDATED, has="claude update")
    assert base.setup("box")
    assert ran(box, "claude update")[0] < ran(box, "agent-config/provision.sh")[0]
    out = capfd.readouterr().out
    assert "2.1.277 → 2.1.280" in out and "until restarted" in out


def test_a_failing_update_warns_with_its_output_and_setup_goes_on(box, capfd):
    box.answer(["exec", "box"], stdout="403 Blocked by network policy\nv 2.1.277 2.1.277\n", code=1, has="claude update")
    assert base.setup("box")
    assert ran(box, "claude update")[0] < ran(box, "agent-config/provision.sh")[0]
    out = "".join(capfd.readouterr())
    assert "claude update failed" in out and "403 Blocked" in out
    assert not ran(box, "tail -5")


@pytest.fixture
def hung(box, monkeypatch):
    """The update never returns within its one second; its run id is fixed, so a log
    line can name it."""
    monkeypatch.setenv("SBX_CLAUDE_UPDATE_TIMEOUT", "1")
    monkeypatch.setattr(base.time, "time", lambda: 100)
    monkeypatch.setattr(base.random, "randrange", lambda n: 7)
    box.answer(["exec", "box"], delay=5, has="claude update")
    return f"100-{os.getpid()}-7"


def log_says(box, text):
    box.answer(["exec", "box", "tail", "-5"], stdout=text)


def test_a_hung_update_is_bounded_and_shows_the_updaters_log_so_far(box, hung, capfd):
    log_says(box, "Downloading 2.1.281…\n")
    assert base.setup("box")
    assert ran(box, "claude update")[0] < ran(box, "agent-config/provision.sh")[0]
    assert ran(box, "claude update")[0] < ran(box, "tail -5")[0]
    out = "".join(capfd.readouterr())
    assert "claude update timed out after 1s" in out and "Downloading 2.1.281" in out
    assert "sbx exec that never returned" not in out


def test_when_the_log_shows_this_run_exited_the_warning_blames_sbx_exec(box, hung, capfd):
    log_says(box, f"Successfully updated\nogun: updater exited 0 at 13:22:02, now 2.1.281 (run {hung})\n")
    base.setup("box")
    out = "".join(capfd.readouterr())
    assert "timed out after 1s" in out and "it was sbx exec that never returned" in out


def test_but_not_for_an_earlier_runs_exit_line(box, hung, capfd):
    log_says(box, "ogun: updater exited 0 at 09:00:00, now 2.1.280 (run 1-2-3)\n")
    base.setup("box")
    out = "".join(capfd.readouterr())
    assert "timed out after 1s" in out and "sbx exec that never returned" not in out


@pytest.fixture
def inside(tmp_path, monkeypatch):
    """sbx exec running its command here, as the sandbox would, with HOME a sandbox's
    whose claude goes 2.1.1 → 2.1.2, and the updater's log at a scratch path."""
    b, h = tmp_path / "local-exec", tmp_path / "sandbox-home"
    b.mkdir()
    (b / "sbx").write_text('#!/bin/sh\n[ "$1" = exec ] && { shift 2; exec "$@"; }\nexit 0\n')
    (b / "sbx").chmod(0o755)
    (h / ".local/bin").mkdir(parents=True)
    monkeypatch.setenv("PATH", f"{b}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("HOME", str(h))
    log = tmp_path / "update.log"
    monkeypatch.setenv("SBX_CLAUDE_UPDATE_LOG", str(log))

    def claude(rc: int):
        (h / ".local/bin/claude").write_text(f"""#!/bin/sh
case "$1" in
  --version) cat "{h}/version" 2>/dev/null || echo "2.1.1 (Claude Code)" ;;
  update) echo "Updating to 2.1.2..."; echo "2.1.2 (Claude Code)" > "{h}/version"; exit {rc} ;;
esac
""")
        (h / ".local/bin/claude").chmod(0o755)
    return claude, log


def test_the_real_script_empties_the_log_then_brackets_the_updater_with_run_tagged_lines(inside, capfd, monkeypatch):
    claude, log = inside
    claude(0)
    log.write_text("ogun: updater exited 0 at 09:00:00, now 2.1.0 (run 1-2-3)\n")   # an earlier run's
    monkeypatch.setattr(base.time, "time", lambda: 100)
    monkeypatch.setattr(base.random, "randrange", lambda n: 7)
    run = f"100-{os.getpid()}-7"
    base.claude_update("box")
    assert "2.1.1 → 2.1.2" in capfd.readouterr().out
    lines = log.read_text().splitlines()
    assert "(run 1-2-3)" not in log.read_text()
    assert lines[0].startswith("ogun: claude update from 2.1.1 at ") and lines[0].endswith(f"(run {run})")
    assert "Updating to 2.1.2..." in lines
    assert lines[-1].startswith("ogun: updater exited 0 at ") and lines[-1].endswith(f", now 2.1.2 (run {run})")


def test_an_updater_killed_inside_exit_137_reads_as_failed_not_timed_out_without_ogs_lines(inside, capfd):
    claude, _ = inside
    claude(137)
    base.claude_update("box")
    out = "".join(capfd.readouterr())
    assert "claude update failed" in out and "timed out" not in out
    assert "Updating to 2.1.2" in out and "ogun: " not in out


# ── Docker inside a sandbox: sandbox-docker.sh ──

DOCKER = paths.SCRIPTS / "sandbox-docker.sh"
CA_PEM = "-----BEGIN CERTIFICATE-----\nMIIBfake\n-----END CERTIFICATE-----"
linux = pytest.mark.skipif(not os.path.isdir("/proc/self"), reason="the script reads /proc: it runs in a sandbox")


@pytest.fixture
def docker(tmp_path):
    """docker, stubbed: the bridge's gateways; socat, a stand-in that logs its
    arguments and names itself socat, as /proc/<pid>/comm shows. Relays are
    stopped after."""
    b = tmp_path / "bin"
    b.mkdir()
    (b / "socat").write_text(f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{tmp_path}/socat.log"
exec {sys.executable} -c 'import ctypes, time; ctypes.CDLL(None).prctl(15, b"socat", 0, 0, 0); time.sleep(30)'
""")
    (b / "docker").write_text("""#!/usr/bin/env bash
[[ "$*" == "network inspect bridge"* ]] && printf '%s' "${DOCKER_STUB_GATEWAYS-172.18.0.1 fd00::1 }"
exit 0
""")
    for f in ("socat", "docker"):
        (b / f).chmod(0o755)
    homes = []

    def run(**env):
        h = env.pop("home", None)
        if h is None:
            h = tmp_path / f"home{len(homes)}"
            h.mkdir()
            homes.append(h)
        e = {**os.environ, "HOME": str(h), "PATH": f"{b}{os.pathsep}{os.environ['PATH']}",
             "SBX_PERSISTENT_ENV": str(h / "env.sh"), "HTTPS_PROXY": "http://gateway.docker.internal:3128",
             "PROXY_CA_CERT_B64": base64.b64encode(CA_PEM.encode()).decode(), **env}
        p = subprocess.run(["bash", str(DOCKER)], env=e, capture_output=True, text=True)
        settled(h)
        return h, p

    yield run, tmp_path / "socat.log"
    for h in homes:
        f = h / ".docker/sbx-relay.pid"
        if f.is_file():
            subprocess.run(["kill", f.read_text().strip()], capture_output=True)


def settled(h) -> None:
    """Until the stand-in relay has renamed itself socat: between the exec and the
    rename it shows as python, and a run that looks then rightly starts another."""
    f = h / ".docker/sbx-relay.pid"
    for _ in range(100):
        try:
            if b"prctl" in Path(f"/proc/{f.read_text().strip()}/cmdline").read_bytes() and comm(h) == "socat":
                return
        except OSError:
            return
        time.sleep(0.05)


def pid(h) -> str:
    return (h / ".docker/sbx-relay.pid").read_text().strip()


def comm(h) -> str:
    return open(f"/proc/{pid(h)}/comm").read().strip()


@linux
def test_setup_writes_the_ca_dockers_https_proxy_on_the_bridge_gateway_and_the_relay(docker):
    run, socat = docker
    h, p = run()
    assert p.returncode == 0
    assert (h / ".docker/sbx-ca/ca.crt").read_text() == CA_PEM
    cfg = json.loads((h / ".docker/config.json").read_text())["proxies"]["default"]
    assert cfg["httpsProxy"] == "http://172.18.0.1:3128" and cfg["noProxy"] == "localhost,127.0.0.1,::1"
    assert "httpProxy" not in cfg
    assert "TCP4-LISTEN:3128,bind=172.18.0.1,fork,reuseaddr TCP:gateway.docker.internal:3128" in socat.read_text().splitlines()
    assert comm(h) == "socat"


@linux
def test_the_env_file_gets_one_export_line_kept_once_and_nothing_that_starts_a_process(docker, tmp_path):
    run, _ = docker
    h = tmp_path / "keep"
    h.mkdir()
    (h / "env.sh").write_text("export KEEP=1\n")
    run(home=h)
    run(home=h)
    lines = (h / "env.sh").read_text().splitlines()
    assert sum("DOCKER_EXTRA_CA_DIR" in x for x in lines) == 1 and "export KEEP=1" in lines
    assert all(x.startswith("export ") for x in lines if x)
    subprocess.run(["kill", pid(h)], capture_output=True)


@linux
def test_a_second_run_leaves_a_running_relay_alone(docker):
    run, socat = docker
    h, _ = run()
    first = pid(h)
    socat.write_text("")
    run(home=h)
    assert pid(h) == first and socat.read_text() == ""


@linux
def test_a_stopped_relay_is_started_again(docker):
    run, _ = docker
    h, _ = run()
    first = pid(h)
    subprocess.run(["kill", first])
    time.sleep(0.2)
    run(home=h)
    assert pid(h) != first and comm(h) == "socat"


@linux
def test_a_pid_file_naming_some_other_live_process_isnt_a_running_relay(docker, tmp_path):
    run, _ = docker
    h = tmp_path / "stale"
    (h / ".docker").mkdir(parents=True)
    (h / ".docker/sbx-relay.pid").write_text(f"{os.getpid()}\n")
    run(home=h)
    assert pid(h) != str(os.getpid()) and comm(h) == "socat"
    subprocess.run(["kill", pid(h)], capture_output=True)


@linux
def test_a_dead_relay_its_parent_hasnt_reaped_is_started_again(docker, tmp_path):
    run, _ = docker
    h = tmp_path / "zombie"
    (h / ".docker").mkdir(parents=True)
    socat = tmp_path / "bin/socat"
    parent = subprocess.Popen(["bash", "-c", '"$1" & echo $! > "$2"; exec sleep 30', "_", str(socat),
                               str(h / ".docker/sbx-relay.pid")])
    try:
        time.sleep(0.5)
        z = pid(h)
        subprocess.run(["kill", z])
        time.sleep(0.3)
        state = next(x for x in Path(f"/proc/{z}/status").read_text().splitlines() if x.startswith("State:"))
        assert "Z" in state   # the fixture holds a zombie
        run(home=h)
        assert pid(h) != z and comm(h) == "socat"
    finally:
        parent.kill()
        subprocess.run(["kill", pid(h)], capture_output=True)


@linux
def test_dockers_other_settings_are_kept(docker, tmp_path):
    run, _ = docker
    h = tmp_path / "merged"
    (h / ".docker").mkdir(parents=True)
    (h / ".docker/config.json").write_text('{"auths":{"x":{}},"proxies":{"default":{"ftpProxy":"f"}}}')
    run(home=h)
    cfg = json.loads((h / ".docker/config.json").read_text())
    assert cfg["auths"] == {"x": {}} and cfg["proxies"]["default"]["ftpProxy"] == "f"
    assert cfg["proxies"]["default"]["httpsProxy"]
    subprocess.run(["kill", pid(h)], capture_output=True)


@linux
def test_docker_not_up_fails_saying_so_no_relay(docker):
    run, _ = docker
    h, p = run(DOCKER_STUB_GATEWAYS="")
    assert p.returncode != 0 and "Docker isn't up" in p.stdout + p.stderr
    assert not (h / ".docker/sbx-relay.pid").exists()


@linux
def test_no_proxy_nothing_to_relay_the_export_removed_the_rest_kept(docker):
    run, _ = docker
    h, _ = run()
    with open(h / "env.sh", "a") as f:
        f.write("export KEEP=1\n")
    _, p = run(home=h, HTTPS_PROXY="", https_proxy="")
    assert p.returncode == 0
    lines = (h / "env.sh").read_text().splitlines()
    assert not any("DOCKER_EXTRA_CA_DIR" in x for x in lines) and "export KEEP=1" in lines


@linux
def test_the_export_an_older_og_wrote_is_replaced_by_one_naming_ogs_own_script(docker, tmp_path):
    run, _ = docker
    h = tmp_path / "old"
    h.mkdir()
    (h / "env.sh").write_text('export DOCKER_EXTRA_CA_DIR="$HOME/.docker/sbx-ca"  # ogun sandbox-docker (elsewhere/sandbox-docker.sh)\n')
    run(home=h)
    lines = (h / "env.sh").read_text().splitlines()
    assert lines == ['export DOCKER_EXTRA_CA_DIR="$HOME/.docker/sbx-ca"  # ogun sandbox-docker (sandbox-docker.sh)']
    subprocess.run(["kill", pid(h)], capture_output=True)


@linux
def test_an_env_file_that_held_only_the_export_is_left_empty(docker):
    run, _ = docker
    h, _ = run()
    run(home=h, HTTPS_PROXY="", https_proxy="")
    assert (h / "env.sh").read_text() == ""


@linux
def test_no_docker_nothing_written(tmp_path):
    b = tmp_path / "nodocker"
    b.mkdir()
    for t in ("bash", "jq", "grep", "tr", "base64", "sleep", "mkdir", "cat"):
        (b / t).symlink_to(shutil.which(t))
    h = tmp_path / "h"
    h.mkdir()
    (h / "env.sh").write_text("x\n")
    p = subprocess.run([str(b / "bash"), str(DOCKER)], capture_output=True, text=True,
                       env={"HOME": str(h), "PATH": str(b), "SBX_PERSISTENT_ENV": str(h / "env.sh"),
                            "HTTPS_PROXY": "http://p:3128"})
    assert p.returncode == 0
    assert not (h / ".docker").exists() and (h / "env.sh").read_text() == "x\n"

