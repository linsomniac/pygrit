def test_native_module_imports():
    import pygritlib

    assert hasattr(pygritlib, "Repository")
    assert hasattr(pygritlib, "ObjectId")
    assert "Repository" in pygritlib.__all__
