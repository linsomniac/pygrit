def test_objectkind_members():
    import pygritlib

    assert {k.name for k in pygritlib.ObjectKind} >= {"COMMIT", "TREE", "BLOB", "TAG"}


def test_objectkind_distinct():
    import pygritlib

    assert pygritlib.ObjectKind.COMMIT != pygritlib.ObjectKind.TREE


def test_objectkind_values_are_stable():
    import pygritlib

    assert (
        pygritlib.ObjectKind.COMMIT,
        pygritlib.ObjectKind.TREE,
        pygritlib.ObjectKind.BLOB,
        pygritlib.ObjectKind.TAG,
    ) == (0, 1, 2, 3)
