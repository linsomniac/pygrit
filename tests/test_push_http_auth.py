"""repo.push over Basic-auth smart-HTTP: correct creds succeed; missing creds raise."""

from __future__ import annotations

from pathlib import Path

import pytest

import pygritlib
from tests.gitlib import run_git

USER, PW = "alice", "s3cret"


def _advance(local: Path, env: dict[str, str]) -> str:
    (local / "b.txt").write_text("two\n")
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
        "c2",
        env=env,
    )
    return run_git(local, "rev-parse", "HEAD", env=env).decode().strip()


def test_auth_push_with_kwargs(http_auth_push_server) -> None:
    p, env = http_auth_push_server, http_auth_push_server.env
    new = _advance(p.local_path, env)
    repo = pygritlib.Repository.open(p.local_path / ".git", p.local_path)
    report = repo.push(
        p.repo_url, ["main"], username=USER, password=PW, use_credential_helpers=False
    )
    assert report.ok
    assert (
        run_git(p.server_path, "rev-parse", "refs/heads/main", env=env).decode().strip()
        == new
    )


def test_auth_push_missing_credentials_raises(http_auth_push_server) -> None:
    p, env = http_auth_push_server, http_auth_push_server.env
    _advance(p.local_path, env)
    repo = pygritlib.Repository.open(p.local_path / ".git", p.local_path)
    with pytest.raises(pygritlib.AuthenticationError):
        repo.push(p.repo_url, ["main"], use_credential_helpers=False)
