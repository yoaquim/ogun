"""exchange: how files move between this Mac and its sandboxes. A sandbox's box
(in/ and out/) and the older layouts a sandbox may still mount; og give (the
inbox, a sandbox's in/, --clip), all of it or none; og tidy (orphaned boxes,
leftover secrets, reported or removed); og take and og scan, which treat what a
sandbox wrote as hostile until checked: a clean file is delivered and nothing
else, never over another; what breaks a rule is quarantined, never deleted."""

import os
import re
import subprocess

import pytest

from ogun.core import log
from ogun.exchange import folders, give, scan, take
from ogun.sandbox import remove

SECRETS = """SCOPE TYPE NAME SECRET
fern service github (stored)
gone-sbx service github (stored)
(global) service anthropic (oauth)

CUSTOM SECRETS
SCOPE TARGETS ENV PLACEHOLDER SECRET
gone-sbx github.example.com, api.example.com KEY sbx-cs-DeadBeef01 ref:op://Private/An Item With Spaces/credential (on-demand)
fern api.mailer.example MAILER sbx-cs-LiveOne22 ref:op://Private/X/credential (on-demand)
"""

# file(1)'s answer, from the first bytes, as it gives it for these fixtures
FILE = """for f in "$@"; do :; done
[ -s "$f" ] || { echo inode/x-empty; exit 0; }
case "$(head -c 4 "$f" | od -An -c | tr -d ' ')" in
  177ELF*) echo application/x-executable ;;
  %PDF*)   echo application/pdf ;;
  *)       echo text/plain ;;
esac"""


@pytest.fixture
def ex(home, fakes, stand_in, monkeypatch):
    """The exchange at a scratch place, the take folder beside it; sbx listing fern
    (and extra, when given) and the secrets above. sbx rm asks its own y/N, which
    only --force (or a person's y) gets past."""
    e = home / "exchange"
    e.mkdir()
    monkeypatch.setenv("OG_EXCHANGE", str(e))
    monkeypatch.setenv("OG_TAKE_DEST", str(home / "downloads"))
    (home / "downloads").mkdir()
    (home / "Projects/personal/fern").mkdir(parents=True)
    stand_in("file", FILE)

    def sbx(extra="", ls_fail=False, rm_fail=False, secret_fail=False, rm_answer=False):
        s = fakes.sbx
        s.clear()
        s.answer(["ls"], stdout=f"NAME STATUS WORKSPACE\nfern running {home}/Projects/personal/fern\n"
                                + (f"{extra} running /x\n" if extra else ""), code=1 if ls_fail else 0)
        if rm_fail:
            s.answer(["rm"], code=1)
        s.answer(["rm"], has="--force")
        if not rm_answer:
            s.answer(["rm"], stderr="error: stdin is not a terminal; use --force to skip confirmation\n", code=1)
        s.answer(["secret", "ls"], stdout=SECRETS, code=1 if secret_fail else 0)
        return s

    sbx()
    yield e, sbx
    # a quarantined folder loses its x bits, on purpose: opened up again, so it can be cleaned away
    subprocess.run(["chmod", "-R", "u+rwx", str(e)], capture_output=True)


def made(name) -> None:
    assert folders.dirs(name) == ""


# ── the box carries in/ as well as out/ ──

def test_a_reserved_box_has_out_and_its_private_in_under_boxes_and_no_session_split(ex):
    e, _ = ex
    made("fern")
    assert (e / "boxes/fern/out").is_dir() and (e / "boxes/fern/in").is_dir()
    assert not (e / "sandboxes").exists()


def test_a_box_is_boxes_name_alone_never_a_top_level_folder(ex):
    e, _ = ex
    (e / "toplevel/out").mkdir(parents=True)
    (e / "boxes/inbox-ok/out").mkdir(parents=True)
    assert folders.box("toplevel") is None and folders.box("inbox-ok") == e / "boxes/inbox-ok"
    assert folders.box("nobox-here") is None   # a plain sbx sandbox has none


def test_tidy_leaves_a_top_level_folder_alone_it_isnt_ogs(og, ex):
    e, _ = ex
    (e / "toplevel/out").mkdir(parents=True)
    assert "toplevel" not in "".join(og("tidy")[1:]) and (e / "toplevel/out").is_dir()


@pytest.mark.parametrize("name", ["boxes", "Boxes"])
def test_the_exchanges_own_folder_names_are_reserved_in_any_case_and_say_why(ex, name):
    assert "exchange's own folders" in folders.dirs(name)


def test_a_name_differing_from_an_existing_box_only_in_case_is_refused_and_makes_nothing(ex):
    e, _ = ex
    (e / "boxes/Casey/out").mkdir(parents=True)
    assert folders.dirs("casey") != "" and not (e / "shared/casey").exists()


def test_a_reservation_lock_released_as_its_read_is_tried_again_never_a_crash(ex, monkeypatch):
    import pathlib
    lock = folders.exchange() / ".reserve-lock"
    lock.mkdir(parents=True)   # held, with no pid yet
    real, calls = pathlib.Path.stat, []

    def stat(self, *a, **k):
        if self.name == ".reserve-lock" and not calls:
            calls.append(1)
            lock.rmdir()   # the holder lets go just now
            raise FileNotFoundError(str(self))
        return real(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "stat", stat)
    assert folders.dirs("racer") == ""
    assert (folders.exchange() / "boxes/racer/in").is_dir()


# ── og give: the inbox, or a sandbox's own in/ ──

@pytest.fixture
def doc(home):
    f = home / "doc.txt"
    f.write_text("hello\n")
    return f


def test_a_bare_give_lands_in_the_inbox_a_targeted_one_in_the_sandboxs_in(og, ex, doc):
    e, _ = ex
    assert og("give", str(doc))[0] == 0 and (e / "inbox/doc.txt").is_file()
    made("fern")
    assert og("give", "fern", str(doc))[0] == 0 and (e / "boxes/fern/in/doc.txt").is_file()


def test_a_reserved_name_is_never_a_target(og, ex):
    assert og("give", "inbox")[0] == 1


def test_an_unknown_name_is_never_quietly_a_target(og, ex, doc):
    e, _ = ex
    og("give", "gone-sbx", str(doc))
    assert not (e / "boxes/gone-sbx").exists()


def test_with_one_file_it_cant_give_it_gives_none_an_option_it_doesnt_have_is_usage(og, ex, home):
    e, _ = ex
    one = home / "one.txt"
    one.write_text("")
    code, out, err = og("give", str(one), str(home / "missing.txt"))
    assert code == 1 and re.search(r"no file.*missing.txt", out + err) and not (e / "inbox/one.txt").exists()
    code, out, err = og("give", str(one), "-x")
    assert code == 1 and (out + err).startswith("usage: og give ") and not (e / "inbox/one.txt").exists()


@pytest.mark.parametrize("args", [["--clip", "ONE"], ["ONE", "--clip"], ["fern", "ONE", "--clip"]])
def test_clip_with_a_file_is_usage_never_one_of_them_dropped(og, ex, home, args):
    e, _ = ex
    made("fern")
    one = home / "one.txt"
    one.write_text("")
    code, out, err = og("give", *[str(one) if a == "ONE" else a for a in args])
    assert code == 1 and (out + err).startswith("usage: og give ")
    assert not (e / "inbox/one.txt").exists() and not (e / "boxes/fern/in/one.txt").exists()


def test_a_name_that_is_both_a_sandbox_and_a_file_here_is_refused(og, ex, doc, home, monkeypatch):
    monkeypatch.chdir(home)
    (home / "fern").write_text("decoy\n")
    assert og("give", "fern", str(doc))[0] == 1


LONG = "l" * 70   # past og's 61 characters: a sandbox made with plain sbx


def test_a_long_named_sandbox_is_still_a_sandbox_refused_never_copied_to_the_inbox(og, ex, home, monkeypatch):
    e, sbx = ex
    sbx(extra=LONG)
    monkeypatch.chdir(home)
    secret = home / "secret.txt"
    secret.write_text("secret\n")
    (home / LONG).write_text("decoy\n")
    assert og("give", LONG, str(secret))[0] == 1 and not (e / "inbox/secret.txt").exists()
    (home / LONG).unlink()
    assert og("give", LONG, str(secret))[0] == 1 and not (e / "inbox/secret.txt").exists()   # og can't make its box


def test_a_box_such_a_sandbox_already_has_stays_usable_give_take_and_rm(og, ex, home):
    e, sbx = ex
    sbx(extra=LONG)
    b = e / "boxes" / LONG
    (b / "out").mkdir(parents=True)
    (b / "in").mkdir()
    (b / "out/report.txt").write_text("result\n")
    secret = home / "secret.txt"
    secret.write_text("secret\n")
    og("give", LONG, str(secret))
    assert (b / "in/secret.txt").is_file()
    assert "report.txt" in og("take", LONG)[1]
    (b / "out/report.txt").unlink()
    (b / "in/secret.txt").unlink()
    folders.box_rm(LONG)
    assert not b.exists()


def test_give_refuses_a_symlink_never_handing_over_what_it_points_at(og, ex, home):
    e, _ = ex
    made("fern")
    (home / "hosts-link.txt").symlink_to("/etc/hosts")
    assert og("give", "fern", str(home / "hosts-link.txt"))[0] == 1
    assert not (e / "boxes/fern/in/hosts-link.txt").exists()


# ── og give --clip ──

def test_clip_lands_a_png_in_the_sandboxs_in_or_the_inbox_an_empty_clipboard_is_an_error(og, ex, home, stand_in, monkeypatch):
    e, _ = ex
    made("fern")
    stand_in("pngpaste", '[ -n "${PNGPASTE_SRC:-}" ] && [ -f "$PNGPASTE_SRC" ] || exit 1\ncp "$PNGPASTE_SRC" "$1"')
    (home / "clip-src").write_bytes(b"PNGDATA")
    monkeypatch.setenv("PNGPASTE_SRC", str(home / "clip-src"))
    og("give", "fern", "--clip")
    assert list((e / "boxes/fern/in").glob("clip-*.png"))
    og("give", "--clip")
    assert list((e / "inbox").glob("clip-*.png"))
    monkeypatch.setenv("PNGPASTE_SRC", "")
    assert og("give", "fern", "--clip")[0] == 1


# ── og give's parts: its refusals, where it gives, the clipboard, the files ──

@pytest.mark.parametrize("args", [["-x"], ["a.txt", "-x"], ["--clip", "a.txt"], ["fern", "a.txt", "--clip"]])
def test_a_give_refused_is_usage(ex, args, capsys):
    assert give.refused(args) is True and "usage: og give" in "".join(capsys.readouterr())


@pytest.mark.parametrize("args", [["a.txt", "b.txt"], ["--clip"], ["fern", "--clip"], ["fern", "a.txt"]])
def test_a_give_that_isnt_refused_says_nothing(ex, args, capsys):
    assert give.refused(args) is False and capsys.readouterr() == ("", "")


def test_a_give_goes_to_the_inbox_or_a_named_sandboxs_in_the_name_taken_off(ex, doc):
    e, _ = ex
    assert give.target(e, [str(doc)]) == (e / "inbox", "every sandbox", [str(doc)])
    assert give.target(e, ["--clip"]) == (e / "inbox", "every sandbox", ["--clip"])
    made("fern")
    assert give.target(e, ["fern", str(doc)]) == (e / "boxes/fern/in", "fern", [str(doc)])


def test_an_exchange_folders_name_is_a_file_even_when_sbx_lists_a_sandbox_by_it(ex, home, monkeypatch):
    e, sbx = ex
    sbx(extra="inbox")
    monkeypatch.chdir(home)
    (home / "inbox").write_text("a file\n")
    assert give.target(e, ["inbox"]) == (e / "inbox", "every sandbox", ["inbox"])


def test_a_sandbox_without_its_box_yet_gets_one_made(ex, doc):
    e, _ = ex
    assert give.target(e, ["fern", str(doc)]) == (e / "boxes/fern/in", "fern", [str(doc)]) and (e / "boxes/fern/in").is_dir()


def test_a_name_sbx_cant_list_gives_nowhere_never_the_inbox(ex, doc, capsys):
    e, sbx = ex
    sbx(ls_fail=True)
    assert give.target(e, ["other", str(doc)]) is None
    assert "sbx couldn't list its sandboxes" in "".join(capsys.readouterr())


@pytest.fixture
def staged(ex):
    e, _ = ex
    (e / "inbox").mkdir()
    (e / ".staging").mkdir()
    return e


def test_the_clipboard_without_pngpaste_says_how_to_get_it(staged, monkeypatch, capsys):
    monkeypatch.setattr(give.shutil, "which", lambda _: None)
    assert give.clip(staged, staged / "inbox", "every sandbox") == 1
    assert "brew install pngpaste" in "".join(capsys.readouterr()) and list((staged / "inbox").iterdir()) == []


def test_the_clipboards_image_lands_as_a_dated_png_none_is_an_error(staged, home, stand_in, monkeypatch):
    stand_in("pngpaste", '[ -n "${PNGPASTE_SRC:-}" ] || exit 1\ncp "$PNGPASTE_SRC" "$1"')
    (home / "clip-src").write_bytes(b"PNGDATA")
    monkeypatch.setenv("PNGPASTE_SRC", str(home / "clip-src"))
    assert give.clip(staged, staged / "inbox", "every sandbox") == 0
    assert [p.read_bytes() for p in (staged / "inbox").glob("clip-*.png")] == [b"PNGDATA"]
    monkeypatch.setenv("PNGPASTE_SRC", "")
    assert give.clip(staged, staged / "inbox", "every sandbox") == 1 and list((staged / ".staging").iterdir()) == []


def test_files_are_each_given_one_missing_gives_none(staged, home, doc):
    two = home / "two.txt"
    two.write_text("2\n")
    assert give.files(staged, [str(doc), str(home / "missing.txt")], staged / "inbox", "every sandbox") == 1
    assert list((staged / "inbox").iterdir()) == []
    assert give.files(staged, [str(doc), str(two)], staged / "inbox", "every sandbox") == 0
    assert sorted(p.name for p in (staged / "inbox").iterdir()) == ["doc.txt", "two.txt"]


# ── the box's life: it dies with its sandbox, unless out/ holds untaken files ──

def test_a_box_with_files_in_out_survives_removal_an_empty_one_goes_shared_outlives_both(ex):
    e, _ = ex
    made("fern")
    (e / "boxes/fern/out/report.txt").write_text("deliverable\n")
    assert folders.box_rm("fern") == "kept" and (e / "boxes/fern").is_dir()
    (e / "boxes/fern/out/report.txt").unlink()
    assert folders.box_rm("fern") == "removed" and not (e / "boxes/fern").exists()
    assert (e / "shared/fern").is_dir()
    assert folders.box_rm("never-existed") == "none"


def test_og_rms_clean_path_removes_the_box_too(ex):
    e, _ = ex
    made("fern")
    assert remove.rm_clean("fern", force=True) and not (e / "boxes/fern").exists()


@pytest.fixture
def locked_box(ex):
    """A box holding a non-empty folder a sandbox made unreadable: removal can't finish."""
    if os.getuid() == 0:
        pytest.skip("root reads anything")
    e, _ = ex
    made("fern")
    d = e / "boxes/fern/in/locked"
    d.mkdir()
    (d / "f").write_text("")
    d.chmod(0)
    yield e
    d.chmod(0o755)


def test_a_box_removal_that_cant_finish_is_reported_never_claimed_and_rm_clean_carries_it(locked_box):
    assert folders.box_rm("fern") == "failed" and (locked_box / "boxes/fern").is_dir()
    assert not remove.rm_clean("fern", force=True)


def test_with_sbx_down_rm_clean_refuses_unknown_is_not_gone(ex):
    e, sbx = ex
    made("fern")
    sbx(rm_fail=True, ls_fail=True)
    assert not remove.rm_clean("fern", force=True) and (e / "boxes/fern").is_dir()


def test_a_sandbox_a_good_listing_proves_gone_is_cleaned_though_sbx_rm_failed(ex):
    e, sbx = ex
    made("stale")
    sbx(rm_fail=True)
    assert remove.rm_clean("stale", force=True) and not (e / "boxes/stale").exists()


def test_without_force_sbxs_y_n_is_left_to_ask_unanswered_nothing_goes_answered_it_does(ex):
    e, sbx = ex
    made("fern")
    assert not remove.rm_clean("fern") and (e / "boxes/fern").is_dir()
    sbx(rm_answer=True)
    assert remove.rm_clean("fern") and not (e / "boxes/fern").exists()


def test_og_rm_force_passes_force_on_a_plain_og_rm_never_forces(og, ex):
    e, sbx = ex
    made("fern")
    assert og("rm", "fern", "--force")[0] == 0 and not (e / "boxes/fern").exists()
    made("fern")
    s = sbx()
    n = len(s.calls)
    assert og("rm", "fern")[0] != 0 and (e / "boxes/fern").is_dir()
    assert all("--force" not in c for c in s.calls[n:] if c[:1] == ["rm"])


@pytest.mark.parametrize("name", ["../../shared", "shared"])
def test_og_rm_refuses_a_traversal_or_reserved_name_before_any_path_is_built(og, ex, name):
    assert og("rm", name)[0] == 1


def test_box_rm_refuses_a_traversal_name_and_the_inbox_is_untouched(ex):
    e, _ = ex
    (e / "inbox").mkdir()
    assert folders.box_rm("../inbox") == "failed" and (e / "inbox").is_dir()


# ── og tidy: orphaned boxes and leftover secrets ──

def test_tidy_reports_orphaned_boxes_and_spares_live_ones(og, ex):
    made("fern")
    made("old-thing")
    out = og("tidy")[1]
    assert "old-thing" in out and "fern" not in out


def test_a_dotted_orphan_name_isnt_hidden_by_a_live_one_it_would_regex_match(og, ex):
    made("fa.o")
    assert "fa.o" in og("tidy")[1]


def test_tidy_lists_a_gone_sandboxs_secrets_with_their_removal_on_their_own_line_never_a_live_ones(og, ex):
    out = og("tidy")[1]
    lines = out.splitlines()
    assert "  ⚠ gone-sbx's github secret is still stored; gone-sbx is gone — to remove it:" in lines
    assert "    sbx secret rm github --sandbox gone-sbx" in lines
    assert "sbx secret rm --sandbox gone-sbx --placeholder sbx-cs-DeadBeef01" in out   # a custom one, its row spaced
    assert not re.search(r"secret.*fern", out) and "fern's custom secret" not in out


def test_tidy_rm_removes_orphaned_boxes_keeps_their_shared_and_live_boxes_and_never_secrets(og, ex):
    e, _ = ex
    made("fern")
    made("old-thing")
    og("tidy", "--rm")
    assert not (e / "boxes/old-thing").exists()
    assert (e / "shared/old-thing").is_dir() and (e / "boxes/fern").is_dir()
    assert "gone-sbx" in og("tidy")[1]   # secrets are only ever reported


def test_tidy_rm_keeps_an_orphan_with_untaken_files_and_removes_it_once_taken(og, ex):
    e, _ = ex
    (e / "boxes/ghost-full/out").mkdir(parents=True)
    (e / "boxes/ghost-full/out/report.txt").write_text("deliverable\n")
    og("tidy", "--rm")
    assert (e / "boxes/ghost-full/out/report.txt").is_file()
    (e / "boxes/ghost-full/out/report.txt").unlink()
    og("tidy", "--rm")
    assert not (e / "boxes/ghost-full").exists()


def test_tidy_aborts_when_sbx_ls_fails_deleting_no_live_box(og, ex):
    e, sbx = ex
    made("fern")
    sbx(ls_fail=True)
    assert og("tidy", "--rm")[0] == 1 and (e / "boxes/fern").is_dir()


def test_an_sbx_that_cant_list_secrets_is_said_never_read_as_none_left(og, ex):
    _, sbx = ex
    sbx(secret_fail=True)
    code, out, err = og("tidy")
    assert code == 1 and "couldn't list secrets (sbx secret ls failed) — leftover secrets not checked" in out + err
    assert "nothing to tidy" not in out + err


def test_tidy_rm_removes_a_folder_thats_a_link_as_the_link(og, ex, home):
    e, _ = ex
    t = home / "linked-target"
    (t / "out").mkdir(parents=True)
    (t / "keep.txt").write_text("keep\n")
    (e / "boxes").mkdir(exist_ok=True)
    (e / "boxes/linked-gone").symlink_to(t)
    out = "".join(og("tidy", "--rm")[1:])
    assert "✓ removed linked-gone's folder  shared/linked-gone kept" in out
    assert not (e / "boxes/linked-gone").is_symlink() and (t / "keep.txt").is_file()


def test_tidy_lists_a_leftover_box_a_sandbox_left_unreadable_and_carries_on(og, ex):
    if os.getuid() == 0:
        pytest.skip("root reads anything")
    e, _ = ex
    d = e / "boxes/locked-gone/out/inner"
    d.mkdir(parents=True)
    d.chmod(0)
    try:
        code, out, err = og("tidy")
    finally:
        d.chmod(0o755)
    assert code == 0 and "locked-gone" in out + err


# ── og take: a clean file delivered, and only it ──

@pytest.fixture
def fern_out(ex, real_git):
    """fern's out/, and its shared/ under the exchange's history."""
    e, _ = ex
    o = e / "boxes/fern/out"
    o.mkdir(parents=True)
    (e / "shared/fern").mkdir(parents=True)
    subprocess.run(["git", "-C", str(e / "shared"), "init", "-q"], check=True)
    (e / "shared/.exchange").write_text("marker\n")
    return o


def downloads(home):
    return sorted(p.name for p in (home / "downloads").iterdir())


def quarantined(ex, out, name) -> bool:
    e, _ = ex
    q = e / ".quarantine/fern" / name
    d = e.parent / "downloads" / name
    return not d.exists() and not (out / name).exists() and not (out / name).is_symlink() and (q.exists() or q.is_symlink())


def test_take_delivers_a_clean_file_removed_from_out_never_executable(og, ex, fern_out, home):
    (fern_out / "report.txt").write_text("hello\n")
    (fern_out / "report.txt").chmod(0o755)
    og("take", "fern", "report.txt")
    d = home / "downloads/report.txt"
    assert d.read_text() == "hello\n" and not (fern_out / "report.txt").exists() and not os.access(d, os.X_OK)


def test_never_over_a_file_already_there_the_new_one_gets_a_new_name(og, ex, fern_out, home):
    (home / "downloads/report.txt").write_text("old\n")
    (fern_out / "report.txt").write_text("new\n")
    og("take", "fern", "report.txt")
    assert (home / "downloads/report.txt").read_text() == "old\n" and (home / "downloads/report-1.txt").read_text() == "new\n"


def test_all_takes_everything_in_out(og, ex, fern_out, home):
    (fern_out / "a.txt").write_text("a\n")
    (fern_out / "b.md").write_text("b\n")
    og("take", "fern", "--all")
    assert downloads(home) == ["a.txt", "b.md"] and list(fern_out.iterdir()) == []


@pytest.mark.parametrize("case", ["symlink", "folder", "hard link", "executable", "lying extension", "unsafe name"])
def test_what_take_quarantines_never_delivered(og, ex, fern_out, home, case):
    name = {"symlink": "hosts.txt", "folder": "sub", "hard link": "leak.txt", "executable": "tool",
            "lying extension": "invoice.pdf", "unsafe name": ".hidden.txt"}[case]
    p = fern_out / name
    if case == "symlink":
        p.symlink_to("/etc/hosts")
    elif case == "folder":
        p.mkdir()
        (p / "x.txt").write_text("x\n")
    elif case == "hard link":
        (home / "elsewhere.txt").write_text("secret\n")
        os.link(home / "elsewhere.txt", p)
    elif case == "executable":
        p.write_bytes(b"\177ELFxxxx")
    else:
        p.write_text("not a pdf\n" if case == "lying extension" else "x\n")
    og("take", "fern", *(["--all"] if case == "unsafe name" else [name]))
    assert quarantined(ex, fern_out, name)


def test_a_pdf_that_is_one_is_delivered(og, ex, fern_out, home):
    (fern_out / "real.pdf").write_bytes(b"%PDF-1.4")
    og("take", "fern", "real.pdf")
    assert (home / "downloads/real.pdf").is_file()


@pytest.mark.parametrize("args", [["fern", "../a.txt"], ["fern", "nothere.txt"], ["../fern", "--all"], ["shared", "--all"],
                                  ["nobox", "--all"]],
                         ids=["a path in a name", "not there", "a traversal", "a reserved name", "no box"])
def test_refused_taking_nothing(og, ex, fern_out, home, args):
    (fern_out / "a.txt").write_text("x\n")
    assert og("take", *args)[0] != 0
    assert (fern_out / "a.txt").is_file() and downloads(home) == []


@pytest.mark.parametrize("args", [["fern", "-x"], ["fern", "a.txt", "-x"], ["fern", "a.txt", "--all"], ["fern", "--all", "a.txt"], ["--all"]])
def test_an_option_take_lacks_or_all_with_names_is_usage_nothing_taken_not_even_the_scan(og, ex, fern_out, home, args):
    e, _ = ex
    (fern_out / "a.txt").write_text("x\n")
    (e / "shared/fern/planted").mkdir()
    code, out, err = og("take", *args)
    assert code == 1 and (out + err).startswith("usage: og take ")
    assert (fern_out / "a.txt").is_file() and downloads(home) == [] and (e / "shared/fern/planted").is_dir()


def test_a_name_with_no_folder_says_so_and_how_to_see_yours(og, ex, fern_out):
    code, out, err = og("take", "nobox")
    assert code == 1 and re.search(r"og take: no sandbox 'nobox' has a folder in the exchange; to see yours, run:.*og ls",
                                   out + err, re.S)


def test_take_name_lists_what_waits_and_takes_nothing(og, ex, fern_out, home):
    (fern_out / "a.txt").write_text("x\n")
    (fern_out / "b.md").write_text("y\n")
    code, out, err = og("take", "fern")
    assert code == 0 and "a.txt" in out + err and "b.md" in out + err and downloads(home) == []


def test_an_empty_out_with_all_is_not_an_error(og, ex, fern_out):
    assert og("take", "fern", "--all")[0] == 0


def test_files_an_earlier_take_left_in_staging_are_reported_with_how_to_clear_them_and_kept(og, ex, fern_out):
    e, _ = ex
    st = e / ".staging/take.abc"
    st.mkdir(parents=True)
    (st / ".pid").write_text("999999\n")
    (st / "claimed.txt").write_text("x\n")
    out = "".join(og("take", "fern")[1:])
    assert re.search(r"an earlier og take left files in .*take.abc.*rm -rf .*take.abc", out, re.S)
    assert (st / "claimed.txt").is_file()


def test_another_take_finishing_as_its_folder_is_looked_at_stops_nothing(ex, fern_out, home, monkeypatch):
    import pathlib
    e, _ = ex
    (fern_out / "a.txt").write_text("x\n")
    (e / ".staging/take.done").mkdir(parents=True)
    real = pathlib.Path.iterdir

    def iterdir(self):   # the other take finished and removed its folder just now
        if self.name == "take.done":
            raise FileNotFoundError(str(self))
        return real(self)

    monkeypatch.setattr(pathlib.Path, "iterdir", iterdir)
    take.take(["fern", "a.txt"])
    assert (home / "downloads/a.txt").is_file()


def test_a_name_with_escape_codes_or_a_newline_is_printed_escaped(og, ex, fern_out):
    (fern_out / "evil\033[2Jname\nforged line.txt").write_text("x\n")
    out = "".join(og("take", "fern", "--all")[1:])
    assert "\033" not in out and "\nforged line" not in out and "\\x1b" in out


def test_take_sweeps_shared_first(og, ex, fern_out):
    e, _ = ex
    (e / "shared/fern/planted").mkdir()
    og("take", "fern", "--all")
    assert (e / ".quarantine/fern/planted").is_dir() and not (e / "shared/fern/planted").exists()


def test_v_shows_each_file_take_writes_or_quarantines(og, ex, fern_out, home):
    e, _ = ex
    (fern_out / "report.txt").write_text("hi\n")
    (fern_out / "hosts.txt").symlink_to("/etc/hosts")
    assert f"  file  wrote {log.path(home / 'downloads/report.txt')}" in og("-v", "take", "fern", "report.txt")[2]
    assert f"  file  quarantined {log.path(e / '.quarantine/fern/hosts.txt')}" in og("-v", "take", "fern", "hosts.txt")[2]


# ── og take's parts: its refusals, the listing, the files chosen, and each file
#    claimed, copied and delivered ──

@pytest.mark.parametrize("name, rest", [("fern", ["-x"]), ("--all", []), ("fern", ["a.txt", "--all"]), ("../fern", ["--all"]),
                                        ("shared", ["--all"]), ("fern", ["a/b.txt"]), ("fern", ["."])])
def test_a_take_refused_is_said_and_takes_nothing(ex, name, rest, capsys):
    assert take.refused(name, rest) is True
    assert "og take" in "".join(capsys.readouterr())


def test_a_take_that_isnt_refused_says_nothing(ex, capsys):
    assert take.refused("fern", ["a.txt", "b.md"]) is False and take.refused("fern", ["--all"]) is False
    assert capsys.readouterr() == ("", "")


def test_the_listing_shows_each_file_and_marks_a_folder(ex, fern_out, capsys):
    (fern_out / "a.txt").write_text("x\n")
    (fern_out / "sub").mkdir()
    take.listing("fern", sorted(fern_out.iterdir()))
    out = "".join(capsys.readouterr())
    assert "a.txt" in out and "sub/" in out and "og take fern --all" in out


def test_all_chooses_what_waits_and_nothing_waiting_is_said(ex, fern_out, capsys):
    (fern_out / "a.txt").write_text("x\n")
    assert take.chosen("fern", fern_out, ["--all"], [fern_out / "a.txt"]) == [fern_out / "a.txt"]
    assert take.chosen("fern", fern_out, ["--all"], []) == []
    assert "nothing in fern's out/ to take" in "".join(capsys.readouterr())


def test_named_files_are_chosen_one_not_there_chooses_none(ex, fern_out, capsys):
    (fern_out / "a.txt").write_text("x\n")
    assert take.chosen("fern", fern_out, ["a.txt"], []) == [fern_out / "a.txt"]
    assert take.chosen("fern", fern_out, ["a.txt", "nothere.txt"], []) is None
    assert re.search(r"no 'nothere.txt' in fern's out/.*og take fern", "".join(capsys.readouterr()), re.S)


@pytest.fixture
def staging(ex):
    e, _ = ex
    s = e / ".staging/take.test"
    s.mkdir(parents=True)
    return s


def test_a_claim_moves_a_file_into_staging(ex, fern_out, staging):
    (fern_out / "a.txt").write_text("x\n")
    got = take.claim("fern", fern_out / "a.txt", staging)
    assert got == staging / "a.txt" and got.read_text() == "x\n" and not (fern_out / "a.txt").exists()


def test_a_claim_quarantines_a_symlink_and_says_one_gone_from_out(ex, fern_out, staging, capsys):
    (fern_out / "hosts.txt").symlink_to("/etc/hosts")
    assert take.claim("fern", fern_out / "hosts.txt", staging) is None
    assert quarantined(ex, fern_out, "hosts.txt")
    assert take.claim("fern", fern_out / "gone.txt", staging) is None
    assert "couldn't move gone.txt out of fern's out/" in "".join(capsys.readouterr())


def test_a_detached_copy_has_the_files_name_and_bytes_beside_the_claim(ex, staging):
    (staging / "a.txt").write_text("x\n")
    chk, copy = take.detach("a.txt", staging / "a.txt", staging)
    assert chk.parent == staging and copy == chk / "a.txt" and copy.read_text() == "x\n" and (staging / "a.txt").is_file()


def test_a_copy_that_cant_be_made_keeps_the_claim_and_says_where(ex, staging, capsys, monkeypatch):
    (staging / "a.txt").write_text("x\n")

    def no(*a, **k):
        raise OSError("full")

    monkeypatch.setattr(take.shutil, "copyfile", no)
    assert take.detach("a.txt", staging / "a.txt", staging) is None
    assert (staging / "a.txt").is_file() and [p.name for p in staging.iterdir()] == ["a.txt"]
    assert "couldn't check a.txt" in "".join(capsys.readouterr())


def test_a_clean_copy_is_delivered_and_its_claim_removed(ex, fern_out, home, staging):
    claim, chk = staging / "a.txt", staging / ".chk.x"
    chk.mkdir()
    claim.write_text("x\n")
    (chk / "a.txt").write_text("x\n")
    assert take.deliver("fern", "a.txt", claim, chk / "a.txt", home / "downloads", False) is True
    assert (home / "downloads/a.txt").read_text() == "x\n" and not claim.exists()


def test_a_copy_that_breaks_a_rule_is_never_delivered_its_claim_quarantined(ex, fern_out, home, staging):
    claim, chk = staging / "invoice.pdf", staging / ".chk.x"
    chk.mkdir()
    claim.write_text("not a pdf\n")
    (chk / "invoice.pdf").write_text("not a pdf\n")
    assert take.deliver("fern", "invoice.pdf", claim, chk / "invoice.pdf", home / "downloads", False) is False
    assert downloads(home) == [] and quarantined(ex, fern_out, "invoice.pdf")


# ── the Gatekeeper tag survives a copy across disks, or nothing is delivered ──

@pytest.fixture
def xattr(stand_in, home):
    """xattr keeping each file's tag under its path: a copy carries none, as a
    copy across disks drops it on a Mac. fail(): writing a tag in Downloads fails."""
    d = home / "xattrs"
    d.mkdir()
    flag = home / "xattr.fail"
    stand_in("xattr", f'''k() {{ printf '%s' "$1" | cksum | cut -d' ' -f1; }}
case "$1" in
  -w) case "$4" in "{home}/downloads"/*) [ -e "{flag}" ] && exit 1 ;; esac; echo "$3" > "{d}/$(k "$4")" ;;
  -p) [ -f "{d}/$(k "$3")" ] ;;
esac''')

    def tagged(p) -> bool:
        k = subprocess.run(["sh", "-c", 'printf "%s" "$1" | cksum | cut -d" " -f1', "_", str(p)], capture_output=True, text=True).stdout.strip()
        return (d / k).is_file()

    return tagged, flag


@pytest.fixture
def across_disks(monkeypatch):
    import errno

    def no_link(*a, **k):
        raise OSError(errno.EXDEV, "cross-device")

    monkeypatch.setattr(os, "link", no_link)


def test_a_file_delivered_across_disks_carries_the_gatekeeper_tag(ex, fern_out, home, xattr, across_disks):
    tagged, _ = xattr
    (fern_out / "report.txt").write_text("hi\n")
    take.take(["fern", "report.txt"])
    assert (home / "downloads/report.txt").is_file() and tagged(home / "downloads/report.txt")


def test_one_whose_tag_cant_be_written_again_is_removed_from_downloads_and_quarantined(ex, fern_out, home, xattr,
                                                                                        across_disks):
    _, flag = xattr
    flag.write_text("")
    (fern_out / "report.txt").write_text("hi\n")
    assert take.take(["fern", "report.txt"]) != 0
    assert not (home / "downloads/report.txt").exists() and quarantined(ex, fern_out, "report.txt")


# ── og scan: shared/'s rules, and its history ──

def log_of(e, *args) -> str:
    return subprocess.run(["git", "-C", str(e / "shared"), "log", "-1", *args], capture_output=True, text=True).stdout.strip()


def commits(e) -> int:
    return int(subprocess.run(["git", "-C", str(e / "shared"), "rev-list", "--count", "HEAD"], capture_output=True, text=True).stdout or 0)


def test_scan_quarantines_a_non_text_file_a_subfolder_and_an_executable_bit(ex, fern_out):
    e, _ = ex
    sh, q = e / "shared/fern", e / ".quarantine/fern"
    (sh / "notes.md").write_text("ok\n")
    (sh / "tool.sh").write_text("x\n")
    (sh / "sub").mkdir()
    (sh / "run.txt").write_text("y\n")
    (sh / "run.txt").chmod(0o755)
    scan.scan(quiet=True)
    assert (sh / "notes.md").is_file()
    for n in ("tool.sh", "sub", "run.txt"):
        assert not (sh / n).exists() and (q / n).exists()


def test_and_a_file_hard_linked_elsewhere(ex, fern_out, home):
    e, _ = ex
    (home / "host-secret.md").write_text("secret\n")
    os.link(home / "host-secret.md", e / "shared/fern/leak.md")
    scan.scan(quiet=True)
    assert not (e / "shared/fern/leak.md").exists() and (e / ".quarantine/fern/leak.md").exists()


def test_and_a_symlink_its_target_never_read(ex, fern_out):
    e, _ = ex
    (e / "shared/fern/hosts.md").symlink_to("/etc/hosts")
    scan.scan(quiet=True)
    assert not (e / "shared/fern/hosts.md").is_symlink() and (e / ".quarantine/fern/hosts.md").is_symlink()


def test_never_the_hosts_own_hidden_folders_git_and_approved_stay(ex, fern_out):
    e, _ = ex
    (e / "shared/fern/notes.md").write_text("ok\n")
    (e / "shared/.approved").mkdir()
    (e / "shared/.approved/x").write_text("yes\n")
    scan.scan(quiet=True)
    assert (e / "shared/.git").is_dir() and (e / "shared/.approved/x").is_file()
    assert not (e / ".quarantine/.git").exists() and not (e / ".quarantine/.approved").exists()


def test_each_sandboxs_shared_is_committed_under_its_own_name_and_nothing_new_makes_no_commit(ex, fern_out):
    e, _ = ex
    (e / "shared/fern/notes.md").write_text("ok\n")
    scan.scan(quiet=True)
    assert log_of(e, "--format=%an", "--", "fern") == "sbx-fern"
    n = commits(e)
    scan.scan(quiet=True)
    assert commits(e) == n


def test_the_hosts_own_edits_are_committed_under_the_hosts_name(ex, fern_out):
    e, _ = ex
    scan.scan(quiet=True)
    (e / "shared/.approved").mkdir()
    (e / "shared/.approved/x").write_text("yes\n")
    scan.scan(quiet=True)
    assert log_of(e, "--format=%s") == "host edits" and log_of(e, "--format=%an") == "host"


def test_a_scan_another_live_one_is_committing_is_skipped_one_left_by_a_dead_scan_is_taken_over(ex, fern_out):
    e, _ = ex
    (e / "shared/fern/notes.md").write_text("ok\n")
    lock = e / ".scan-lock"
    lock.mkdir()
    (lock / "pid").write_text(f"{os.getpid()}\n")
    scan.scan(quiet=True)
    assert subprocess.run(["git", "-C", str(e / "shared"), "rev-parse", "-q", "--verify", "HEAD"], capture_output=True).returncode != 0
    (lock / "pid").write_text("999999\n")
    scan.scan(quiet=True)
    assert log_of(e, "--format=%an", "--", "fern") == "sbx-fern" and not lock.exists()


def test_og_scan_says_each_change_or_that_there_was_nothing_and_with_no_exchange_an_error(og, ex, fern_out, home,
                                                                                         monkeypatch):
    e, _ = ex
    (e / "shared/fern/notes.md").write_text("ok\n")
    (e / "shared/fern/tool.sh").write_text("x\n")
    code, out, err = og("scan")
    assert code == 0 and "quarantined fern/tool.sh" in out + err and "✓ committed shared/fern's history" in out + err
    assert "nothing to change" not in out + err
    assert "".join(og("scan")[1:]).strip() == "nothing to change in shared/"
    monkeypatch.setenv("OG_EXCHANGE", str(home / "no-exchange"))
    code, out, err = og("scan")
    assert code == 1 and (out + err).strip() == f"og scan: no exchange at {log.path(home / 'no-exchange')}"


def test_a_shared_folder_a_sandbox_made_unreadable_is_skipped_the_others_committed(ex, fern_out):
    if os.getuid() == 0:
        pytest.skip("root reads anything")
    e, _ = ex
    (e / "shared/other").mkdir()
    (e / "shared/other/notes.md").write_text("ok\n")
    (e / "shared/fern/notes.md").write_text("x\n")
    (e / "shared/fern").chmod(0)
    try:
        scan.scan(quiet=True)
    finally:
        (e / "shared/fern").chmod(0o755)
    assert log_of(e, "--format=%an", "--", "other") == "sbx-other"


def test_a_scan_lock_that_vanishes_as_its_read_is_a_scan_just_done_no_crash(ex, fern_out, monkeypatch):
    import pathlib
    e, _ = ex
    (e / ".scan-lock").mkdir()   # no pid yet, gone before its age is read
    real = pathlib.Path.stat

    def stat(self, *a, **k):
        if self.name == ".scan-lock":
            raise FileNotFoundError(str(self))
        return real(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "stat", stat)
    scan.scan(quiet=True)


def test_a_shared_file_removed_while_its_checked_is_skipped_and_the_scan_commits(ex, fern_out, monkeypatch):
    import pathlib
    e, _ = ex
    (e / "shared/fern/a.md").write_text("ok\n")
    (e / "shared/fern/b.md").write_text("ok\n")
    real = pathlib.Path.lstat

    def lstat(self):   # a.md removed by its sandbox between the listing and the check
        if self.name == "a.md":
            raise FileNotFoundError(str(self))
        return real(self)

    monkeypatch.setattr(pathlib.Path, "lstat", lstat)
    scan.scan(quiet=True)
    assert log_of(e, "--format=%an", "--", "fern") == "sbx-fern"


def test_take_from_a_box_with_shared_rules_broken_quarantines_before_taking(og, ex, fern_out):
    e, _ = ex
    (e / "shared/fern/planted-dir").mkdir()
    og("take", "fern")
    assert not (e / "shared/fern/planted-dir").exists() and (e / ".quarantine/fern/planted-dir").is_dir()

