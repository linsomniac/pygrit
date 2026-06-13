"""FFI lifetime safety: children (Odb, TreeIter) must outlive their parents.

AIDEV-NOTE: These tests pin the ownership model from design §6. `repo.odb` clones an
Arc<Repository>, and `iter(tree)` clones an Arc<[TreeEntryData]>, so each child owns its
own reference to the underlying data. After `del parent; gc.collect()` the child must
remain usable with no crash/abort. If either test segfaults, the binding holds a borrow
instead of an Arc — FIX the binding, do NOT weaken the test.
"""

from __future__ import annotations

import gc
from pathlib import Path

from tests.gitlib import rev_parse


def test_odb_outlives_repository(simple_repo: Path) -> None:
    import pygrit

    oid = rev_parse(simple_repo, "HEAD:a.txt")
    repo = pygrit.Repository.discover(str(simple_repo))
    odb = repo.odb
    del repo
    gc.collect()
    obj = odb.read(
        pygrit.ObjectId.from_hex(oid)
    )  # Arc keeps repo alive; must not crash
    assert obj.id.hex == oid


def test_tree_iter_outlives_tree(simple_repo: Path) -> None:
    import pygrit

    tree_oid = rev_parse(simple_repo, "HEAD^{tree}")
    repo = pygrit.Repository.discover(str(simple_repo))
    tree = repo.tree(pygrit.ObjectId.from_hex(tree_oid))
    it = iter(tree)
    del tree
    gc.collect()
    names = {e.name for e in it}
    assert b"a.txt" in names
