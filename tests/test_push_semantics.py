"""repo.push git:// semantics: delete, force, non-ff rejection, lease, dry-run, atomic."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pylibgrit
from tests.gitlib import run_git


# AIDEV-NOTE: Helper to make a new commit in the local worktree using the git oracle.
# Returns the new HEAD hex string. Used throughout to advance the pusher's history.
def _commit(local: Path, env: dict[str, str], name: str, content: str) -> str:
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


def _server_ref(p: SimpleNamespace, env: dict[str, str], ref: str) -> str | None:
    """Return the hex OID of `ref` on the server, or None if absent."""
    out = (
        run_git(p.server_path, "for-each-ref", "--format=%(objectname)", ref, env=env)
        .decode()
        .strip()
    )
    return out or None


def _open(p: SimpleNamespace) -> pylibgrit.Repository:
    return pylibgrit.Repository.open(p.local_path / ".git", p.local_path)


def test_push_delete(git_daemon_push) -> None:
    # AIDEV-NOTE: Verify that ":refs/heads/doomed" (delete syntax) removes the ref on the server.
    p, env = git_daemon_push, git_daemon_push.env
    run_git(p.local_path, "push", "-q", p.repo_url, "main:refs/heads/doomed", env=env)
    assert _server_ref(p, env, "refs/heads/doomed") is not None
    report = _open(p).push(p.repo_url, [":refs/heads/doomed"])
    assert report.ok
    assert report.results[0].deletion is True
    assert _server_ref(p, env, "refs/heads/doomed") is None


def test_push_non_fast_forward_rejected(git_daemon_push) -> None:
    # AIDEV-NOTE: Push a diverged history without force; expect reject-non-fast-forward in results.
    # The rejection is returned as DATA (PushRefResult.status), NOT as an exception.
    p, env = git_daemon_push, git_daemon_push.env
    _commit(p.local_path, env, "b.txt", "two\n")
    _open(p).push(p.repo_url, ["main"])
    run_git(p.local_path, "reset", "-q", "--hard", p.base_oid, env=env)
    diverged = _commit(p.local_path, env, "c.txt", "other\n")
    report = _open(p).push(p.repo_url, ["main"])
    assert not report.ok
    assert report.results[0].status == "reject-non-fast-forward"
    assert _server_ref(p, env, "refs/heads/main") != diverged


def test_push_force(git_daemon_push) -> None:
    # AIDEV-NOTE: The same diverged scenario, but force=True. Server must accept and update the ref.
    p, env = git_daemon_push, git_daemon_push.env
    _commit(p.local_path, env, "b.txt", "two\n")
    _open(p).push(p.repo_url, ["main"])
    run_git(p.local_path, "reset", "-q", "--hard", p.base_oid, env=env)
    diverged = _commit(p.local_path, env, "c.txt", "other\n")
    report = _open(p).push(p.repo_url, ["main"], force=True)
    assert report.ok
    assert _server_ref(p, env, "refs/heads/main") == diverged


def test_push_lease_stale_rejected(git_daemon_push) -> None:
    # AIDEV-NOTE: Force-with-lease: send a wrong expected_old (the new commit OID, not the server
    # tip). The server must reject as stale. This exercises the lease path in PushSpec.
    p, env = git_daemon_push, git_daemon_push.env
    new = _commit(p.local_path, env, "b.txt", "two\n")
    wrong = pylibgrit.ObjectId.from_hex(new)  # != server's base_oid -> stale
    spec = pylibgrit.PushSpec(
        b"refs/heads/main", src=pylibgrit.ObjectId.from_hex(new), expected_old=wrong
    )
    report = _open(p).push(p.repo_url, [spec])
    assert not report.ok
    assert report.results[0].status == "reject-stale"
    assert _server_ref(p, env, "refs/heads/main") == p.base_oid


def test_push_lease_fresh_accepted(git_daemon_push) -> None:
    # AIDEV-NOTE: Force-with-lease with the correct expected_old (the server's actual tip). Must
    # succeed and update the server ref.
    p, env = git_daemon_push, git_daemon_push.env
    new = _commit(p.local_path, env, "b.txt", "two\n")
    spec = pylibgrit.PushSpec(
        b"refs/heads/main",
        src=pylibgrit.ObjectId.from_hex(new),
        expected_old=pylibgrit.ObjectId.from_hex(p.base_oid),  # correct current value
    )
    report = _open(p).push(p.repo_url, [spec])
    assert report.ok
    assert _server_ref(p, env, "refs/heads/main") == new


def test_push_dry_run(git_daemon_push) -> None:
    # AIDEV-NOTE: dry_run=True must leave the server unchanged while still populating new_oid in
    # the result (so callers can preview what would happen).
    p, env = git_daemon_push, git_daemon_push.env
    new = _commit(p.local_path, env, "b.txt", "two\n")
    report = _open(p).push(p.repo_url, ["main"], dry_run=True)
    assert _server_ref(p, env, "refs/heads/main") == p.base_oid  # unchanged
    result = report.results[0]
    assert result.new_oid is not None
    assert result.new_oid.hex == new  # computed but not applied


def test_push_atomic_all_or_nothing(git_daemon_push) -> None:
    # AIDEV-NOTE: atomic=True means either all refs update or none do. Here `main` is diverged
    # (non-ff), so the server must reject the whole batch. `feature` should show atomic-push-failed,
    # and must NOT appear on the server. This exercises the all-or-nothing guarantee.
    p, env = git_daemon_push, git_daemon_push.env
    landed = _commit(p.local_path, env, "b.txt", "two\n")
    _open(p).push(p.repo_url, ["main"])  # server main now == landed
    run_git(p.local_path, "reset", "-q", "--hard", p.base_oid, env=env)
    _commit(p.local_path, env, "c.txt", "other\n")  # main now diverged (non-ff)
    run_git(p.local_path, "checkout", "-q", "-b", "feature", env=env)
    _commit(p.local_path, env, "f.txt", "feat\n")
    report = _open(p).push(p.repo_url, ["main", "feature"], atomic=True)  # no force
    assert not report.ok
    by_ref = {r.remote_ref: r.status for r in report.results}
    assert by_ref[b"refs/heads/main"] == "reject-non-fast-forward"
    assert by_ref[b"refs/heads/feature"] == "atomic-push-failed"
    # Neither ref landed: feature absent, main still pinned to its pre-batch value.
    assert _server_ref(p, env, "refs/heads/feature") is None
    assert _server_ref(p, env, "refs/heads/main") == landed
