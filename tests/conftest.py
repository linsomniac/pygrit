"""Pytest fixtures: hermetic, deterministic git environment."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

DETERMINISTIC_DATE = "2005-04-07T22:13:13"


@pytest.fixture
def git_env(tmp_path: Path) -> dict[str, str]:
    """Isolated git environment: no user/system config, fixed identity, UTC, C locale."""
    home = tmp_path / "home"
    home.mkdir()
    return {
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "TZ": "UTC",
        "LC_ALL": "C",
        "PATH": __import__("os").environ["PATH"],
        "GIT_AUTHOR_NAME": "Test Author",
        "GIT_AUTHOR_EMAIL": "author@example.com",
        "GIT_AUTHOR_DATE": DETERMINISTIC_DATE,
        "GIT_COMMITTER_NAME": "Test Committer",
        "GIT_COMMITTER_EMAIL": "committer@example.com",
        "GIT_COMMITTER_DATE": DETERMINISTIC_DATE,
    }


def _git(repo: Path, env: dict[str, str], *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


@pytest.fixture
def simple_repo(tmp_path: Path, git_env: dict[str, str]) -> Path:
    """A repo with one commit: a.txt='hello\\n', plus a dir/b.txt."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, git_env, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("hello\n")
    (repo / "dir").mkdir()
    (repo / "dir" / "b.txt").write_text("world\n")
    _git(repo, git_env, "add", "-A")
    _git(repo, git_env, "commit", "-q", "-m", "initial commit")
    return repo
