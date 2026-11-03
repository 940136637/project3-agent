"""健壮性策略统一入口：超时、重试、降级。

设计取舍（面试可直接讲）：

1. **配置走环境变量，每次调用重新读取**：生产可热调、测试可注入；
   不在 import 时读一次就固化，否则 monkeypatch 环境变量对测试无效。
2. **只对"可恢复错误"重试**：网络抖动、超时、限流、5xx。4xx（参数/鉴权错误）
   与业务错误（如高德返回 status != 1）重试没有意义，立即失败——重试只会放大故障。
3. **不做随机抖动（jitter）**：本项目单实例演示，确定性优先、测试稳定；
   高并发下应加 jitter 防"惊群"（thundering herd），这一点在面试讲法里说明。
4. **超时是硬边界**：任何外部调用都必须给超时，不允许"永远等待"。
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import httpx
from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


@dataclass(frozen=True)
class ResilienceConfig:
    """一套超时/重试参数。frozen：配置只读，避免运行中被意外改写。"""

    llm_timeout_seconds: float = 60
    llm_max_retries: int = 2
    tool_timeout_seconds: float = 60
    weather_http_timeout_seconds: float = 10
    weather_max_retries: int = 2
    retry_wait_min_seconds: float = 1.0
    retry_wait_max_seconds: float = 10.0


def _read_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        # fail fast：配置写错就启动失败，而不是静默用默认值埋雷
        raise ValueError(f"环境变量 {name} 值非法: {raw!r}") from None


def _read_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"环境变量 {name} 值非法: {raw!r}") from None


def get_config() -> ResilienceConfig:
    """读取当前环境变量，返回一份配置快照。"""
    return ResilienceConfig(
        llm_timeout_seconds=_read_float("LLM_TIMEOUT_SECONDS", 60),
        llm_max_retries=_read_int("LLM_MAX_RETRIES", 2),
        tool_timeout_seconds=_read_float("TOOL_TIMEOUT_SECONDS", 60),
        weather_http_timeout_seconds=_read_float("WEATHER_HTTP_TIMEOUT_SECONDS", 10),
        weather_max_retries=_read_int("WEATHER_MAX_RETRIES", 2),
        retry_wait_min_seconds=_read_float("RETRY_WAIT_MIN_SECONDS", 1.0),
        retry_wait_max_seconds=_read_float("RETRY_WAIT_MAX_SECONDS", 10.0),
    )


def llm_retry(cfg: ResilienceConfig):
    """LLM 调用的重试装饰器工厂。

    - 重试次数 = 失败尝试之外的额外重试次数（llm_max_retries=2 → 最多 3 次尝试）
    - 指数退避：1s、2s、4s……封顶 retry_wait_max_seconds
    - reraise=True：重试耗尽后抛原始异常，交给上层 SSE error 事件兜底，不静默吞掉
    """
    return retry(
        reraise=True,
        stop=stop_after_attempt(cfg.llm_max_retries + 1),
        wait=wait_exponential(
            multiplier=1,
            min=cfg.retry_wait_min_seconds,
            max=cfg.retry_wait_max_seconds,
        ),
        retry=retry_if_exception_type(
            (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)
        ),
    )


async def run_tool_with_timeout(tool: Any, args: dict, timeout_seconds: float) -> str:
    """在超时上限内执行同步工具，超时返回可读的失败文本而不是抛异常。

    注意：asyncio.to_thread 无法强杀线程，超时只是"不再等待"，工具线程可能仍在跑。
    因此工具内部必须有自己的 I/O 超时兜底（见 tools.weather_query 的 HTTP timeout），
    否则线程会一直挂着、越积越多。
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(tool.invoke, args), timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        return f"{tool.name}执行失败:超时(超过{timeout_seconds}秒),已放弃等待"


def is_5xx_error(exc: BaseException) -> bool:
    """是否为 HTTP 5xx（服务端故障，通常可恢复、值得重试）。"""
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response is not None
        and exc.response.status_code >= 500
    )
