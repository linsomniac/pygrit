import os
import subprocess

import pytest


def test_write_to_worktree_writes_file(tmp_path):
    import pygritlib

    work = tmp_path / "r"
    repo = pygritlib.Repository.init(str(work))
    repo.write_to_worktree(b"sub/greeting.txt", b"hello\n", 0o100644)
    assert (work / "sub" / "greeting.txt").read_bytes() == b"hello\n"


def test_write_to_worktree_executable_bit(tmp_path):
    import pygritlib

    work = tmp_path / "r"
    repo = pygritlib.Repository.init(str(work))
    repo.write_to_worktree(b"run.sh", b"#!/bin/sh\n", 0o100755)
    assert os.access(work / "run.sh", os.X_OK)


def test_write_to_worktree_bare_raises(tmp_path):
    import pygritlib

    gd = tmp_path / "b.git"
    repo = pygritlib.Repository.init(str(gd), bare=True)
    with pytest.raises(pygritlib.RepositoryError):
        repo.write_to_worktree(b"x.txt", b"y", 0o100644)


def test_checkout_tree_materializes_files(tmp_path):
    import pygritlib

    dst = tmp_path / "dst"
    repo = pygritlib.Repository.init(str(dst))
    blob = repo.odb.write(pygritlib.ObjectKind.BLOB, b"alpha\n")
    idx = repo.index()
    idx.add(b"dir/a.txt", blob, 0o100644)
    tree = idx.write_tree()
    repo.checkout_tree(tree)
    assert (dst / "dir" / "a.txt").read_bytes() == b"alpha\n"


def test_checkout_tree_overlay_preserves_untracked(tmp_path):
    import pygritlib

    dst = tmp_path / "dst"
    repo = pygritlib.Repository.init(str(dst))
    (dst / "keep.txt").write_bytes(b"mine\n")
    blob = repo.odb.write(pygritlib.ObjectKind.BLOB, b"alpha\n")
    idx = repo.index()
    idx.add(b"a.txt", blob, 0o100644)
    repo.checkout_tree(idx.write_tree())
    assert (dst / "keep.txt").read_bytes() == b"mine\n"
    assert (dst / "a.txt").read_bytes() == b"alpha\n"


def test_checkout_tree_no_clobber_without_force(tmp_path):
    import pygritlib

    dst = tmp_path / "dst"
    repo = pygritlib.Repository.init(str(dst))
    (dst / "a.txt").write_bytes(b"existing\n")
    blob = repo.odb.write(pygritlib.ObjectKind.BLOB, b"alpha\n")
    idx = repo.index()
    idx.add(b"a.txt", blob, 0o100644)
    tree = idx.write_tree()
    with pytest.raises(FileExistsError):
        repo.checkout_tree(tree)
    assert (dst / "a.txt").read_bytes() == b"existing\n"
    repo.checkout_tree(tree, force=True)
    assert (dst / "a.txt").read_bytes() == b"alpha\n"


def test_checkout_tree_updates_index(tmp_path, git_env):
    import pygritlib

    dst = tmp_path / "dst"
    repo = pygritlib.Repository.init(str(dst))
    blob = repo.odb.write(pygritlib.ObjectKind.BLOB, b"alpha\n")
    idx = repo.index()
    idx.add(b"a.txt", blob, 0o100644)
    repo.checkout_tree(idx.write_tree(), update_index=True)
    staged = subprocess.run(
        ["git", "ls-files", "--stage"],
        cwd=dst,
        env=git_env,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.decode()
    assert "a.txt" in staged


def test_checkout_tree_bare_raises(tmp_path):
    import pygritlib

    gd = tmp_path / "b.git"
    repo = pygritlib.Repository.init(str(gd), bare=True)
    empty = repo.odb.write(pygritlib.ObjectKind.BLOB, b"x")
    idx = repo.index()
    idx.add(b"a.txt", empty, 0o100644)
    tree = idx.write_tree()
    with pytest.raises(pygritlib.RepositoryError):
        repo.checkout_tree(tree)


def test_checkout_tree_parent_component_clobber(tmp_path):
    import pygritlib

    dst = tmp_path / "dst"
    repo = pygritlib.Repository.init(str(dst))
    # A regular file sits where the tree needs a directory "D".
    (dst / "D").write_bytes(b"i am a file\n")
    blob = repo.odb.write(pygritlib.ObjectKind.BLOB, b"alpha\n")
    idx = repo.index()
    idx.add(b"D/f.txt", blob, 0o100644)
    tree = idx.write_tree()
    with pytest.raises(FileExistsError):
        repo.checkout_tree(tree)
    assert (dst / "D").read_bytes() == b"i am a file\n"  # untouched without force
    repo.checkout_tree(tree, force=True)
    assert (dst / "D" / "f.txt").read_bytes() == b"alpha\n"


def test_checkout_tree_skips_gitlink(tmp_path):
    import pygritlib

    dst = tmp_path / "dst"
    repo = pygritlib.Repository.init(str(dst))
    blob = repo.odb.write(pygritlib.ObjectKind.BLOB, b"alpha\n")
    # A gitlink (submodule) entry alongside a normal blob.
    fake_commit = repo.odb.write(
        pygritlib.ObjectKind.COMMIT,
        b"tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904\nauthor a <a@x> 0 +0000\n"
        b"committer a <a@x> 0 +0000\n\nm\n",
    )
    idx = repo.index()
    idx.add(b"a.txt", blob, 0o100644)
    idx.add(b"sub", fake_commit, 0o160000)
    tree = idx.write_tree()
    repo.checkout_tree(tree)
    assert (dst / "a.txt").read_bytes() == b"alpha\n"
    assert not (dst / "sub").exists()  # gitlink skipped, nothing written
