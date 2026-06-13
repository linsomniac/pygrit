def test_native_module_imports():
    import pygrit

    assert pygrit._hello() == "pygrit"
