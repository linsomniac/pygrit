import subprocess

import pytest


def _git(repo, env, *args):
    return (
        subprocess.run(
            ["git", *args], cwd=repo, env=env, stdout=subprocess.PIPE, check=True
        )
        .stdout.decode()
        .strip()
    )


def _repo_one_commit(tmp_path, git_env):
    import pylibgrit

    work = tmp_path / "r"
    repo = pylibgrit.Repository.init(str(work))
    sig = pylibgrit.Signature(b"A", b"a@x", (1112911993, 0))
    b1 = repo.odb.write(pylibgrit.ObjectKind.BLOB, b"x\n")
    idx = repo.index()
    idx.add(b"a.txt", b1, 0o100644)
    idx.write()
    c1 = repo.commit_index(message=b"one\n", author=sig, committer=sig)
    return repo, work, c1, sig


def test_lightweight_tag(tmp_path, git_env):
    import pylibgrit

    repo, work, c1, _sig = _repo_one_commit(tmp_path, git_env)
    repo.create_lightweight_tag(b"v1", c1)
    assert _git(work, git_env, "rev-parse", "refs/tags/v1") == c1.hex
    with pytest.raises(pylibgrit.RefMismatchError):
        repo.create_lightweight_tag(b"v1", c1)


def test_lightweight_tag_force_moves(tmp_path, git_env):
    import pylibgrit

    repo, work, c1, sig = _repo_one_commit(tmp_path, git_env)
    repo.create_lightweight_tag(b"v1", c1)
    # a second commit to move the tag to
    b2 = repo.odb.write(pylibgrit.ObjectKind.BLOB, b"y\n")
    idx = repo.index()
    idx.add(b"a.txt", b2, 0o100644)
    idx.write()
    c2 = repo.commit_index(message=b"two\n", author=sig, committer=sig)
    repo.create_lightweight_tag(b"v1", c2, force=True)
    assert _git(work, git_env, "rev-parse", "refs/tags/v1") == c2.hex


def test_annotated_tag(tmp_path, git_env):
    import pylibgrit

    repo, work, c1, sig = _repo_one_commit(tmp_path, git_env)
    tag_oid = repo.create_annotated_tag(
        b"v2", c1, pylibgrit.ObjectKind.COMMIT, message=b"release 2\n", tagger=sig
    )
    assert _git(work, git_env, "rev-parse", "refs/tags/v2") == tag_oid.hex
    assert _git(work, git_env, "rev-parse", "refs/tags/v2^{commit}") == c1.hex
    assert _git(work, git_env, "cat-file", "-t", tag_oid.hex) == "tag"


def test_annotated_tag_force_moves(tmp_path, git_env):
    import pylibgrit

    repo, work, c1, sig = _repo_one_commit(tmp_path, git_env)
    repo.create_lightweight_tag(b"v3", c1)
    with pytest.raises(pylibgrit.RefMismatchError):
        repo.create_annotated_tag(
            b"v3", c1, pylibgrit.ObjectKind.COMMIT, message=b"m\n", tagger=sig
        )
    tag_oid = repo.create_annotated_tag(
        b"v3", c1, pylibgrit.ObjectKind.COMMIT, message=b"m\n", tagger=sig, force=True
    )
    assert _git(work, git_env, "rev-parse", "refs/tags/v3") == tag_oid.hex
