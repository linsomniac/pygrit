"""Pytest fixtures: hermetic, deterministic git environment."""

from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.gitlib import run_git

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


def _free_port() -> int:
    """Grab an ephemeral port by binding to :0 and releasing it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_port(host: str, port: int, proc: subprocess.Popen, timeout: float) -> bool:
    """Poll until `host:port` accepts a connection or `proc` dies / `timeout` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False  # daemon exited (e.g. `git daemon` unavailable)
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.05)
    return False


@pytest.fixture
def git_daemon(tmp_path: Path, git_env: dict[str, str]):
    """Serve a seeded bare repo over git:// on localhost. Skips if `git daemon` is unavailable.

    Yields a namespace with `repo_url`, `server_path` (the bare repo), and `head_oid`.
    """
    base = tmp_path / "srv"
    base.mkdir()
    # Seed a source repo, then make the served bare repo a clone of it.
    src = tmp_path / "src"
    src.mkdir()
    _git(src, git_env, "init", "-q", "-b", "main")
    (src / "a.txt").write_text("hello\n")
    (src / "dir").mkdir()
    (src / "dir" / "b.txt").write_text("world\n")
    _git(src, git_env, "add", "-A")
    _git(src, git_env, "commit", "-q", "-m", "initial commit")
    _git(src, git_env, "tag", "v1")
    server = base / "server.git"
    _git(tmp_path, git_env, "clone", "-q", "--bare", str(src), str(server))
    head_oid = run_git(src, "rev-parse", "HEAD", env=git_env).decode().strip()

    port = _free_port()
    # AIDEV-NOTE: `--export-all` lets git-daemon serve repos under `--base-path`
    # without requiring a `git-daemon-export-ok` marker file in each repo.
    # On the skip path, `_wait_port` returns False when the daemon dies early, so
    # `proc.terminate()` before `pytest.skip(...)` is a benign no-op on an already-dead process.
    proc = subprocess.Popen(
        [
            "git",
            "daemon",
            "--reuseaddr",
            "--listen=127.0.0.1",
            f"--port={port}",
            f"--base-path={base}",
            "--export-all",
            str(base),
        ],
        env=git_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not _wait_port("127.0.0.1", port, proc, timeout=5.0):
        proc.terminate()
        pytest.skip("git daemon unavailable")
    try:
        yield SimpleNamespace(
            repo_url=f"git://127.0.0.1:{port}/server.git",
            server_path=server,
            src=src,
            head_oid=head_oid,
            env=git_env,
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
