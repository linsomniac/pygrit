import subprocess

import pytest


def _init(repo, env):
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], env=env, check=True)


def _commit(repo, env, msg):
    (repo / "f").write_text(msg)
    subprocess.run(["git", "add", "f"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=repo, env=env, check=True)
    return (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            env=env,
            stdout=subprocess.PIPE,
            check=True,
        )
        .stdout.decode()
        .strip()
    )


def test_update_ref_with_message_writes_reflog(tmp_path, git_env):
    import pygritlib

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    c1 = _commit(repo, git_env, "one")
    pg = pygritlib.Repository.open(str(repo / ".git"))
    sig = pygritlib.Signature(b"Test", b"t@example.com", (1112911993, 0))
    pg.update_ref(
        b"refs/heads/logged",
        pygritlib.ObjectId.from_hex(c1),
        create=True,
        message=b"branch: created",
        signer=sig,
    )
    log = (repo / ".git" / "logs" / "refs" / "heads" / "logged").read_text()
    assert "branch: created" in log
    assert "t@example.com" in log


def test_update_ref_without_message_no_reflog(tmp_path, git_env):
    import pygritlib

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    c1 = _commit(repo, git_env, "one")
    pg = pygritlib.Repository.open(str(repo / ".git"))
    pg.update_ref(b"refs/heads/silent", pygritlib.ObjectId.from_hex(c1), create=True)
    assert not (repo / ".git" / "logs" / "refs" / "heads" / "silent").exists()


def test_message_requires_signer(tmp_path, git_env):
    import pygritlib

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    c1 = _commit(repo, git_env, "one")
    pg = pygritlib.Repository.open(str(repo / ".git"))
    with pytest.raises(ValueError):
        pg.update_ref(
            b"refs/heads/x",
            pygritlib.ObjectId.from_hex(c1),
            create=True,
            message=b"no signer",
        )


def test_explicit_append_reflog(tmp_path, git_env):
    import pygritlib

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    c1 = _commit(repo, git_env, "one")
    c2 = _commit(repo, git_env, "two")
    pg = pygritlib.Repository.open(str(repo / ".git"))
    o1, o2 = pygritlib.ObjectId.from_hex(c1), pygritlib.ObjectId.from_hex(c2)
    sig = pygritlib.Signature(b"Test", b"t@example.com", (1112911993, 0))
    pg.append_reflog(
        b"refs/heads/main",
        o1,
        o2,
        signer=sig,
        message=b"manual entry",
        force_create=True,
    )
    log = (repo / ".git" / "logs" / "refs" / "heads" / "main").read_text()
    assert "manual entry" in log


def test_delete_ref_message_requires_signer(tmp_path, git_env):
    import pygritlib

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    c1 = _commit(repo, git_env, "one")
    pg = pygritlib.Repository.open(str(repo / ".git"))
    pg.update_ref(b"refs/heads/togo", pygritlib.ObjectId.from_hex(c1), create=True)
    with pytest.raises(ValueError):
        pg.delete_ref(
            b"refs/heads/togo", message=b"no signer"
        )  # message without signer


def test_delete_ref_with_message_runs_and_removes(tmp_path, git_env):
    import pygritlib

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    c1 = _commit(repo, git_env, "one")
    pg = pygritlib.Repository.open(str(repo / ".git"))
    sig = pygritlib.Signature(b"Test", b"t@example.com", (1112911993, 0))
    pg.update_ref(b"refs/heads/togo", pygritlib.ObjectId.from_hex(c1), create=True)
    # delete with a reflog message: the code path (append reflog before delete) runs cleanly
    # and the ref is removed. (We do NOT assert the per-ref reflog survives — deleting a ref
    # may also remove its log, which is acceptable.)
    pg.delete_ref(b"refs/heads/togo", message=b"branch: deleted", signer=sig)
    rc = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", "refs/heads/togo"],
        cwd=repo,
        env=git_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode
    assert rc != 0  # ref is gone
