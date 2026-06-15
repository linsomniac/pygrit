import subprocess

import pytest

from tests.gitlib import cat_file_data, cat_file_type


def _init(repo, env):
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], env=env, check=True)


def test_write_blob_matches_git_hash_object(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    # git's oracle oid for the same bytes
    git_oid = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=repo, env=git_env, input=b"hello\n",
        stdout=subprocess.PIPE, check=True,
    ).stdout.decode().strip()

    pg = pylibgrit.Repository.open(str(repo / ".git"))
    oid = pg.odb.write(pylibgrit.ObjectKind.BLOB, b"hello\n")
    assert oid.hex == git_oid
    # and it is actually on disk / readable
    assert pg.odb.read(oid).data == b"hello\n"
    assert cat_file_type(repo, oid.hex) == "blob"
    assert cat_file_data(repo, oid.hex) == b"hello\n"


def test_hash_computes_without_writing(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    pg = pylibgrit.Repository.open(str(repo / ".git"))
    oid = pg.odb.hash(pylibgrit.ObjectKind.BLOB, b"nope\n")
    assert pg.odb.exists(oid) is False  # hash() must not write


def test_write_is_idempotent(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    pg = pylibgrit.Repository.open(str(repo / ".git"))
    a = pg.odb.write(pylibgrit.ObjectKind.BLOB, b"dup\n")
    b = pg.odb.write(pylibgrit.ObjectKind.BLOB, b"dup\n")
    assert a == b
