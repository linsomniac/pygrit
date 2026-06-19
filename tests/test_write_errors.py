import os
import subprocess

import pytest


def _init(repo, env):
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], env=env, check=True)


def test_odb_write_unwritable_dir_raises_oserror(tmp_path, git_env):
    """Writing a loose object into a read-only objects dir maps grit-lib's IO error to OSError."""
    import pygritlib

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    pg = pygritlib.Repository.open(str(repo / ".git"))

    objects_dir = repo / ".git" / "objects"
    original_mode = objects_dir.stat().st_mode
    os.chmod(objects_dir, 0o555)  # read+execute, no write
    try:
        # As root (or on filesystems that ignore the mode), the dir stays writable; skip then.
        if os.access(objects_dir, os.W_OK):
            pytest.skip(
                "objects dir still writable (root / permissive FS); cannot test"
            )
        with pytest.raises(OSError):
            pg.odb.write(pygritlib.ObjectKind.BLOB, b"unwritable\n")
    finally:
        os.chmod(objects_dir, original_mode)  # restore so tmp cleanup works
