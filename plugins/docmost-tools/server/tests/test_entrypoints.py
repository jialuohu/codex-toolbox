from __future__ import annotations


def test_package_imports_without_initializing_network_or_browser() -> None:
    from docmost_tools import __version__, server

    assert __version__ == "0.1.0"
    assert callable(server.main)
