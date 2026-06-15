def test_ref_mismatch_error_is_griterror_subclass():
    import pylibgrit

    assert issubclass(pylibgrit.RefMismatchError, pylibgrit.GritError)
