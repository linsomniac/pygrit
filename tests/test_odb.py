import pytest

from tests.gitlib import cat_file_data, rev_parse


def test_odb_read_blob_matches_git(simple_repo):
    import pygritlib

    blob_oid = rev_parse(simple_repo, "HEAD:a.txt")
    repo = pygritlib.Repository.discover(str(simple_repo))
    obj = repo.odb.read(pygritlib.ObjectId.from_hex(blob_oid))
    assert obj.id.hex == blob_oid
    assert obj.kind is pygritlib.ObjectKind.BLOB
    assert obj.data == cat_file_data(simple_repo, blob_oid)


def test_odb_read_commit_matches_git(simple_repo):
    import pygritlib

    commit_oid = rev_parse(simple_repo, "HEAD")
    repo = pygritlib.Repository.discover(str(simple_repo))
    obj = repo.odb.read(pygritlib.ObjectId.from_hex(commit_oid))
    assert obj.kind is pygritlib.ObjectKind.COMMIT
    assert obj.data == cat_file_data(simple_repo, commit_oid)


def test_odb_exists(simple_repo):
    import pygritlib

    commit_oid = rev_parse(simple_repo, "HEAD")
    repo = pygritlib.Repository.discover(str(simple_repo))
    assert repo.odb.exists(pygritlib.ObjectId.from_hex(commit_oid)) is True


def test_odb_read_missing_raises(simple_repo):
    import pygritlib

    repo = pygritlib.Repository.discover(str(simple_repo))
    missing = pygritlib.ObjectId.from_hex("0" * 40)
    with pytest.raises(pygritlib.ObjectNotFoundError):
        repo.odb.read(missing)
