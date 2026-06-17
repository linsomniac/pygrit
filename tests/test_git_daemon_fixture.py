"""The git_daemon fixture serves a bare repo reachable over git:// (oracle check)."""

from __future__ import annotations

from tests.gitlib import run_git


def test_daemon_serves_refs(git_daemon, tmp_path) -> None:
    # `git ls-remote` (the oracle) can reach the served repo and see refs/heads/main.
    out = run_git(tmp_path, "ls-remote", git_daemon.repo_url).decode()
    assert "refs/heads/main" in out
    assert git_daemon.head_oid in out
