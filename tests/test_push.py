"""repo.push over git:// — new branch, fast-forward, and PushReport shape."""

from __future__ import annotations

import pygritlib
from tests.gitlib import run_git


def _commit(local, env, name, content) -> str:
    (local / name).write_text(content)
    run_git(local, "add", "-A", env=env)
    run_git(
        local,
        "-c",
        "user.name=T",
        "-c",
        "user.email=t@e",
        "commit",
        "-q",
        "-m",
        name,
        env=env,
    )
    return run_git(local, "rev-parse", "HEAD", env=env).decode().strip()


def test_push_fast_forward(git_daemon_push) -> None:
    local = git_daemon_push.local_path
    env = git_daemon_push.env
    new = _commit(local, env, "b.txt", "two\n")
    repo = pygritlib.Repository.open(local / ".git", local)
    report = repo.push(git_daemon_push.repo_url, ["main"])
    assert report.ok
    server_main = (
        run_git(git_daemon_push.server_path, "rev-parse", "refs/heads/main", env=env)
        .decode()
        .strip()
    )
    assert server_main == new
    [res] = report.results
    assert res.remote_ref == b"refs/heads/main"
    assert res.status in {"ok", "up-to-date"}
    assert res.new_oid is not None
    assert res.new_oid.hex == new


def test_push_new_branch(git_daemon_push) -> None:
    local = git_daemon_push.local_path
    env = git_daemon_push.env
    run_git(local, "checkout", "-q", "-b", "feature", env=env)
    new = _commit(local, env, "f.txt", "feat\n")
    repo = pygritlib.Repository.open(local / ".git", local)
    report = repo.push(git_daemon_push.repo_url, ["feature"])
    assert report.ok
    server = (
        run_git(git_daemon_push.server_path, "rev-parse", "refs/heads/feature", env=env)
        .decode()
        .strip()
    )
    assert server == new


def test_push_tag_goes_to_tags_namespace(git_daemon_push) -> None:
    local, env = git_daemon_push.local_path, git_daemon_push.env
    run_git(local, "tag", "v1.0", env=env)
    repo = pygritlib.Repository.open(local / ".git", local)
    report = repo.push(git_daemon_push.repo_url, ["v1.0"])
    assert report.ok
    out = run_git(
        git_daemon_push.server_path, "for-each-ref", "--format=%(refname)", env=env
    ).decode()
    assert "refs/tags/v1.0" in out
    assert "refs/heads/v1.0" not in out


def test_push_raw_oid_without_dest_raises(git_daemon_push) -> None:
    import pytest

    local, env = git_daemon_push.local_path, git_daemon_push.env
    head = run_git(local, "rev-parse", "HEAD", env=env).decode().strip()
    repo = pygritlib.Repository.open(local / ".git", local)
    with pytest.raises(ValueError):
        repo.push(git_daemon_push.repo_url, [head])  # bare oid, no destination
