import subprocess

import pytest


def _init(repo, env):
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], env=env, check=True)


def _empty_tree(repo, env):
    return subprocess.run(
        ["git", "write-tree"], cwd=repo, env=env,
        stdout=subprocess.PIPE, check=True,
    ).stdout.decode().strip()


def test_create_commit_matches_git_commit_tree(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    tree_hex = _empty_tree(repo, git_env)

    pg = pylibgrit.Repository.open(str(repo / ".git"))
    tree = pylibgrit.ObjectId.from_hex(tree_hex)
    # Pin the same identity + time git uses below (epoch 1112911993, +0000).
    sig = pylibgrit.Signature(b"Test Author", b"author@example.com", (1112911993, 0))
    committer = pylibgrit.Signature(b"Test Committer", b"committer@example.com", (1112911993, 0))
    commit = pg.create_commit(
        tree, parents=[], author=sig, committer=committer, message=b"initial commit\n"
    )

    env = dict(git_env)
    env.update(
        GIT_AUTHOR_NAME="Test Author", GIT_AUTHOR_EMAIL="author@example.com",
        GIT_AUTHOR_DATE="1112911993 +0000",
        GIT_COMMITTER_NAME="Test Committer", GIT_COMMITTER_EMAIL="committer@example.com",
        GIT_COMMITTER_DATE="1112911993 +0000",
    )
    git_commit = subprocess.run(
        ["git", "commit-tree", tree_hex, "-m", "initial commit"],
        cwd=repo, env=env, stdout=subprocess.PIPE, check=True,
    ).stdout.decode().strip()
    assert commit.hex == git_commit


def test_create_commit_author_raw_byte_exact(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    tree_hex = _empty_tree(repo, git_env)
    pg = pylibgrit.Repository.open(str(repo / ".git"))
    tree = pylibgrit.ObjectId.from_hex(tree_hex)

    ident = b"Test Author <author@example.com> 1112911993 +0000"
    commit = pg.create_commit(
        tree, parents=[], author_raw=ident, committer_raw=ident, message=b"x\n"
    )
    # The raw author/committer header must round-trip verbatim.
    obj = pg.odb.read(commit)
    assert b"author " + ident + b"\n" in obj.data
    # And it equals git commit-tree with the same identity.
    env = dict(git_env)
    env.update(
        GIT_AUTHOR_NAME="Test Author", GIT_AUTHOR_EMAIL="author@example.com",
        GIT_AUTHOR_DATE="1112911993 +0000",
        GIT_COMMITTER_NAME="Test Author", GIT_COMMITTER_EMAIL="author@example.com",
        GIT_COMMITTER_DATE="1112911993 +0000",
    )
    git_commit = subprocess.run(
        ["git", "commit-tree", tree_hex, "-m", "x"],
        cwd=repo, env=env, stdout=subprocess.PIPE, check=True,
    ).stdout.decode().strip()
    assert commit.hex == git_commit


def test_create_commit_multi_parent(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    tree_hex = _empty_tree(repo, git_env)
    pg = pylibgrit.Repository.open(str(repo / ".git"))
    tree = pylibgrit.ObjectId.from_hex(tree_hex)
    sig = pylibgrit.Signature(b"A", b"a@x", (1, 0))
    p1 = pg.create_commit(tree, parents=[], author=sig, committer=sig, message=b"p1\n")
    p2 = pg.create_commit(tree, parents=[], author=sig, committer=sig, message=b"p2\n")
    merge = pg.create_commit(tree, parents=[p1, p2], author=sig, committer=sig, message=b"m\n")
    assert pg.commit(merge).parents == [p1, p2]


def test_create_commit_rejects_both_author_forms(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    pg = pylibgrit.Repository.open(str(repo / ".git"))
    tree = pylibgrit.ObjectId.from_hex(_empty_tree(repo, git_env))
    sig = pylibgrit.Signature(b"A", b"a@x", (1, 0))
    with pytest.raises(ValueError):
        pg.create_commit(
            tree, parents=[], author=sig, author_raw=b"A <a@x> 1 +0000",
            committer=sig, message=b"x\n",
        )
    with pytest.raises(ValueError):
        pg.create_commit(tree, parents=[], committer=sig, message=b"x\n")  # missing author
