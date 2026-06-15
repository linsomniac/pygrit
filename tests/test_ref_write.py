import subprocess

import pytest


def test_ref_mismatch_error_is_griterror_subclass():
    import pylibgrit

    assert issubclass(pylibgrit.RefMismatchError, pylibgrit.GritError)


def _init(repo, env):
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], env=env, check=True)


def _commit(repo, env, msg):
    (repo / "f").write_text(msg)
    subprocess.run(["git", "add", "f"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=repo, env=env, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, env=env,
        stdout=subprocess.PIPE, check=True,
    ).stdout.decode().strip()


def test_update_ref_overwrite(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    c1 = _commit(repo, git_env, "one")
    pg = pylibgrit.Repository.open(str(repo / ".git"))
    pg.update_ref(b"refs/heads/feature", pylibgrit.ObjectId.from_hex(c1))
    got = subprocess.run(
        ["git", "rev-parse", "refs/heads/feature"], cwd=repo, env=git_env,
        stdout=subprocess.PIPE, check=True,
    ).stdout.decode().strip()
    assert got == c1


def test_update_ref_create_only(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    c1 = _commit(repo, git_env, "one")
    pg = pylibgrit.Repository.open(str(repo / ".git"))
    oid = pylibgrit.ObjectId.from_hex(c1)
    pg.update_ref(b"refs/heads/new", oid, create=True)  # ok, doesn't exist
    with pytest.raises(pylibgrit.RefMismatchError):
        pg.update_ref(b"refs/heads/new", oid, create=True)  # now exists


def test_update_ref_cas(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    c1 = _commit(repo, git_env, "one")
    c2 = _commit(repo, git_env, "two")
    pg = pylibgrit.Repository.open(str(repo / ".git"))
    o1, o2 = pylibgrit.ObjectId.from_hex(c1), pylibgrit.ObjectId.from_hex(c2)
    pg.update_ref(b"refs/heads/cas", o1)
    # CAS succeeds when expected matches:
    pg.update_ref(b"refs/heads/cas", o2, expected_old=o1)
    # CAS fails when expected is stale:
    with pytest.raises(pylibgrit.RefMismatchError):
        pg.update_ref(b"refs/heads/cas", o1, expected_old=o1)  # current is o2 now


def test_update_ref_create_and_expected_old_is_error(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    c1 = _commit(repo, git_env, "one")
    pg = pylibgrit.Repository.open(str(repo / ".git"))
    oid = pylibgrit.ObjectId.from_hex(c1)
    with pytest.raises(ValueError):
        pg.update_ref(b"refs/heads/x", oid, create=True, expected_old=oid)


def test_delete_ref_and_cas_delete(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    c1 = _commit(repo, git_env, "one")
    c2 = _commit(repo, git_env, "two")
    pg = pylibgrit.Repository.open(str(repo / ".git"))
    o1, o2 = pylibgrit.ObjectId.from_hex(c1), pylibgrit.ObjectId.from_hex(c2)
    pg.update_ref(b"refs/heads/d", o2)
    with pytest.raises(pylibgrit.RefMismatchError):
        pg.delete_ref(b"refs/heads/d", expected_old=o1)   # stale -> refused
    pg.delete_ref(b"refs/heads/d", expected_old=o2)        # matches -> deleted
    rc = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", "refs/heads/d"],
        cwd=repo, env=git_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode
    assert rc != 0  # ref is gone


def test_set_head_symbolic(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    _commit(repo, git_env, "one")
    pg = pylibgrit.Repository.open(str(repo / ".git"))
    pg.set_head(b"refs/heads/other")
    got = subprocess.run(
        ["git", "symbolic-ref", "HEAD"], cwd=repo, env=git_env,
        stdout=subprocess.PIPE, check=True,
    ).stdout.decode().strip()
    assert got == "refs/heads/other"


def test_set_symbolic_ref(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    c1 = _commit(repo, git_env, "one")
    pg = pylibgrit.Repository.open(str(repo / ".git"))
    pg.update_ref(b"refs/heads/main", pylibgrit.ObjectId.from_hex(c1))
    pg.set_symbolic_ref(b"refs/heads/alias", b"refs/heads/main")
    got = subprocess.run(
        ["git", "symbolic-ref", "refs/heads/alias"], cwd=repo, env=git_env,
        stdout=subprocess.PIPE, check=True,
    ).stdout.decode().strip()
    assert got == "refs/heads/main"
