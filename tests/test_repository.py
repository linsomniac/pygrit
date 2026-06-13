import os

import pytest

from tests.gitlib import git_text  # noqa: F401  (available if needed)


def test_discover_returns_repository(simple_repo):
    import pygrit

    repo = pygrit.Repository.discover(str(simple_repo))
    assert repo.git_dir == os.fsencode(simple_repo / ".git")
    assert repo.work_tree == os.fsencode(simple_repo)
    assert repo.is_bare is False


def test_discover_missing_repo_raises(tmp_path):
    import pygrit

    with pytest.raises(pygrit.RepositoryError):
        pygrit.Repository.discover(str(tmp_path))


def test_open_explicit_dirs(simple_repo):
    import pygrit

    repo = pygrit.Repository.open(str(simple_repo / ".git"), str(simple_repo))
    assert repo.is_bare is False
