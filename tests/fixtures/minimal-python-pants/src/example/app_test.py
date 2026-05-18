from example.app import greet


def test_greet() -> None:
    assert greet("Pants") == "Hello, Pants"
