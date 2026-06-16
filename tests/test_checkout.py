import os

import pytest


def test_write_to_worktree_writes_file(tmp_path):
    import pylibgrit

    work = tmp_path / "r"
    repo = pylibgrit.Repository.init(str(work))
    repo.write_to_worktree(b"sub/greeting.txt", b"hello\n", 0o100644)
    assert (work / "sub" / "greeting.txt").read_bytes() == b"hello\n"


def test_write_to_worktree_executable_bit(tmp_path):
    import pylibgrit

    work = tmp_path / "r"
    repo = pylibgrit.Repository.init(str(work))
    repo.write_to_worktree(b"run.sh", b"#!/bin/sh\n", 0o100755)
    assert os.access(work / "run.sh", os.X_OK)


def test_write_to_worktree_bare_raises(tmp_path):
    import pylibgrit

    gd = tmp_path / "b.git"
    repo = pylibgrit.Repository.init(str(gd), bare=True)
    with pytest.raises(pylibgrit.RepositoryError):
        repo.write_to_worktree(b"x.txt", b"y", 0o100644)
