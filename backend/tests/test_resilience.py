import asyncio

import httpx
import pytest

from agent.resilience import get_config, is_5xx_error, run_tool_with_timeout


def test_defaults(monkeypatch):
    # conftest 的 autouse fixture 会把退避设为 0，这里先清掉才能验证真实默认值
    monkeypatch.delenv("RETRY_WAIT_MIN_SECONDS", raising=False)
    monkeypatch.delenv("RETRY_WAIT_MAX_SECONDS", raising=False)
    cfg = get_config()
    assert cfg.llm_timeout_seconds == 60
    assert cfg.llm_max_retries == 2
    assert cfg.tool_timeout_seconds == 60
    assert cfg.weather_http_timeout_seconds == 10
    assert cfg.weather_max_retries == 2
    assert cfg.retry_wait_min_seconds == 1.0
    assert cfg.retry_wait_max_seconds == 10.0


def test_env_override(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("LLM_MAX_RETRIES", "5")
    cfg = get_config()
    assert cfg.llm_timeout_seconds == 30
    assert cfg.llm_max_retries == 5


def test_invalid_env_raises(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "abc")

    with pytest.raises(ValueError):
        get_config()


def test_fast_retries_fixture():
    """conftest 的 autouse fixture 生效：测试内退避为 0，不拖慢用例"""
    cfg = get_config()
    assert cfg.retry_wait_min_seconds == 0
    assert cfg.retry_wait_max_seconds == 0


class SlowTool:
    name = "slow_tool"

    def invoke(self, args):
        import time

        time.sleep(0.2)
        return "慢结果"


class FastTool:
    name = "fast_tool"

    def invoke(self, args):
        return "快结果"


def test_run_tool_timeout_returns_message():
    """工具超时：不抛异常，返回失败文本（含"失败"二字，面板才能标红）"""
    r = asyncio.run(run_tool_with_timeout(SlowTool(), {}, 0.05))
    assert r.startswith("slow_tool执行失败")
    assert "超时" in r


def test_run_tool_success_returns_result():
    r = asyncio.run(run_tool_with_timeout(FastTool(), {}, 5))
    assert r == "快结果"


REQ = httpx.Request("GET", "https://example.com")


def test_is_5xx_error_true():
    err = httpx.HTTPStatusError(
        "server error", request=REQ, response=httpx.Response(500, request=REQ)
    )
    assert is_5xx_error(err) is True


def test_is_5xx_error_false_for_4xx():
    err = httpx.HTTPStatusError(
        "client error", request=REQ, response=httpx.Response(404, request=REQ)
    )
    assert is_5xx_error(err) is False


def test_is_5xx_error_false_for_other_exception():
    assert is_5xx_error(ValueError("boom")) is False
