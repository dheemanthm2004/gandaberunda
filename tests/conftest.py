"""Pytest configuration and global fixtures."""
import pytest


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Speed up retry and backoff tests by replacing time.sleep with a no-op."""
    monkeypatch.setattr("time.sleep", lambda seconds: None)

