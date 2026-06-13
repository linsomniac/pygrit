"""Helpers to build hermetic git fixture repos and query git as an oracle."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(repo: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    """Run a git command in `repo`, returning raw stdout bytes."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def git_text(repo: Path, *args: str) -> str:
    return run_git(repo, *args).decode("utf-8", "surrogateescape").strip()


def rev_parse(repo: Path, spec: str) -> str:
    return git_text(repo, "rev-parse", spec)


def cat_file_data(repo: Path, oid: str) -> bytes:
    """Return the raw object payload via `git cat-file --batch`.

    AIDEV-NOTE: `git cat-file --batch` emits a header line then the raw payload.
    Format: "<oid> <type> <size>\\n<payload>\\n"
    We partition on the first newline to get the header, parse the size from it,
    then slice exactly `size` bytes from the remainder (ignoring the trailing newline
    that git appends after the payload).
    """
    proc = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=repo,
        input=f"{oid}\n".encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    out = proc.stdout
    header, _, rest = out.partition(b"\n")
    _oid, _type, size = header.split(b" ")
    return rest[: int(size)]


def cat_file_type(repo: Path, oid: str) -> str:
    return git_text(repo, "cat-file", "-t", oid)
