import pytest


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    """所有测试零退避等待:重试立即发生,测试不因指数退避变慢"""
    monkeypatch.setenv("RETRY_WAIT_MIN_SECONDS", "0")
    monkeypatch.setenv("RETRY_WAIT_MAX_SECONDS", "0")
