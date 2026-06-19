"""The two networking exception types exist and subclass GritError."""

import pygritlib


def test_network_error_is_griterror_subclass() -> None:
    assert issubclass(pygritlib.NetworkError, pygritlib.GritError)


def test_authentication_error_is_griterror_subclass() -> None:
    assert issubclass(pygritlib.AuthenticationError, pygritlib.GritError)


def test_exceptions_are_distinct() -> None:
    assert pygritlib.NetworkError is not pygritlib.AuthenticationError
    assert not issubclass(pygritlib.NetworkError, pygritlib.AuthenticationError)
    assert not issubclass(pygritlib.AuthenticationError, pygritlib.NetworkError)
