import subprocess

import pytest

from tests.gitlib import cat_file_type


def _init(repo, env):
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], env=env, check=True)


def _one_commit(repo, env):
    (repo / "a.txt").write_text("hi\n")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "c"], cwd=repo, env=env, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, env=env,
        stdout=subprocess.PIPE, check=True,
    ).stdout.decode().strip()


def test_create_tag_matches_git(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    head = _one_commit(repo, git_env)
    pg = pylibgrit.Repository.open(str(repo / ".git"))
    target = pylibgrit.ObjectId.from_hex(head)
    tagger = pylibgrit.Signature(b"Tagger", b"tag@example.com", (1112911993, 0))
    tag = pg.create_tag(
        target, pylibgrit.ObjectKind.COMMIT, b"v1", message=b"release one\n", tagger=tagger,
    )
    assert cat_file_type(repo, tag.hex) == "tag"
    # read-side view agrees
    assert pg.tag(tag).name == b"v1"
    assert pg.tag(tag).target == target

    # Oracle: `git tag -a` takes its tagger from the committer identity/date, so pin those to
    # match the Signature above; refs/tags/v1 then points at the annotated-tag object.
    env = dict(git_env)
    env.update(
        GIT_COMMITTER_NAME="Tagger",
        GIT_COMMITTER_EMAIL="tag@example.com",
        GIT_COMMITTER_DATE="1112911993 +0000",
    )
    subprocess.run(
        ["git", "tag", "-a", "v1", "-m", "release one", head],
        cwd=repo, env=env, check=True,
    )
    git_tag = subprocess.run(
        ["git", "rev-parse", "refs/tags/v1"], cwd=repo, env=env,
        stdout=subprocess.PIPE, check=True,
    ).stdout.decode().strip()
    assert tag.hex == git_tag


def test_create_tag_non_utf8_message_raises(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo, git_env)
    head = _one_commit(repo, git_env)
    pg = pylibgrit.Repository.open(str(repo / ".git"))
    target = pylibgrit.ObjectId.from_hex(head)
    tagger = pylibgrit.Signature(b"T", b"t@x", (1, 0))
    with pytest.raises(ValueError):
        pg.create_tag(target, pylibgrit.ObjectKind.COMMIT, b"v2",
                      message=b"\xff\xfe", tagger=tagger)
