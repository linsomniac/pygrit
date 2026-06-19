def test_exception_hierarchy():
    import pygritlib

    assert issubclass(pygritlib.RepositoryError, pygritlib.GritError)
    assert issubclass(pygritlib.ObjectNotFoundError, pygritlib.GritError)
    assert issubclass(pygritlib.InvalidObjectError, pygritlib.GritError)
    assert pygritlib.GritError is not pygritlib.RepositoryError
    assert not issubclass(pygritlib.ObjectNotFoundError, pygritlib.RepositoryError)
