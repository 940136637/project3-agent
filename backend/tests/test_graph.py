import asyncio
import time

import httpx
import pytest
from langchain_core.messages import AIMessage
from openai import APIConnectionError

from agent.graph import build_graph


def _conn_error() -> APIConnectionError:
    """构造一个 openai 的连接异常（3.x 的构造函数要求传 request）"""
    return APIConnectionError(request=httpx.Request("POST", "https://api.deepseek.com"))


class FakeLLM:
    """可配置失败次数的假模型：先失败 fail_times 次，之后返回固定回答"""

    def __init__(self, fail_times: int, answer: str = "答:28"):
        self.fail_times = fail_times
        self.answer = answer
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise _conn_error()
        return AIMessage(content=self.answer, tool_calls=[])


def test_calculator_reasoning_chain():
    """最短链路：问算术 → agent 调 calculator → 观察结果 → 回答 28（真实 LLM 冒烟）"""
    graph = build_graph()
    result = asyncio.run(
        graph.ainvoke(
            {"messages": [("user", "算一下 23 加 5")]},
            config={"recursion_limit": 15},
        )
    )
    messages = result["messages"]
    answer = messages[-1].content
    assert "28" in answer
    tool_msgs = [m for m in messages if m.type == "tool"]
    assert tool_msgs, "预期过程中至少有一次工具调用"


def test_no_tool_question_answered_directly():
    """无需工具的闲聊问题：不调工具直接答（真实 LLM 冒烟）"""
    graph = build_graph()
    result = asyncio.run(
        graph.ainvoke(
            {"messages": [("user", "你好")]},
            config={"recursion_limit": 15},
        )
    )
    assert len(result["messages"]) >= 2


def test_llm_transient_failure_recovers(monkeypatch):
    """LLM 第一次失败，tenacity 自动重试后成功，链路不中断"""
    from agent import graph as graph_mod

    fake = FakeLLM(fail_times=1)
    monkeypatch.setattr(graph_mod, "llm_with_tools", fake)
    result = asyncio.run(
        graph_mod.build_graph().ainvoke(
            {"messages": [("user", "你好")]},
            config={"recursion_limit": 15},
        )
    )
    assert result["messages"][-1].content == "答:28"
    assert fake.calls == 2


def test_llm_persistent_failure_raises(monkeypatch):
    """LLM 持续失败：重试耗尽后异常上抛，交给既有 error 事件兜底，不静默"""
    from agent import graph as graph_mod

    fake = FakeLLM(fail_times=99)
    monkeypatch.setattr(graph_mod, "llm_with_tools", fake)
    with pytest.raises(APIConnectionError):
        asyncio.run(
            graph_mod.build_graph().ainvoke(
                {"messages": [("user", "你好")]},
                config={"recursion_limit": 15},
            )
        )
    assert fake.calls == 3  # 默认 llm_max_retries=2 → 共 3 次尝试


def test_llm_timeout_configured():
    """LLM 单次调用超时来自配置，不是 SDK 默认的无限等待"""
    from agent import graph as graph_mod

    assert graph_mod.llm.request_timeout == 60.0


class SlowTool:
    name = "slow_tool"

    def invoke(self, args):
        time.sleep(0.2)
        return "慢结果"


def _tool_call_state(name: str, args: dict):
    return {
        "messages": [
            AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "t1"}])
        ]
    }


def test_tools_node_unknown_tool_returns_fallback():
    """模型幻觉出不存在的工具名：不崩溃，返回错误观察"""
    from agent import graph as graph_mod

    r = asyncio.run(graph_mod.tools_node(_tool_call_state("no_such_tool", {})))
    assert r["messages"][0].content.startswith("工具调用失败")


def test_tools_node_timeout_returns_message(monkeypatch):
    """单个工具卡死：超时后返回失败观察，整条链路继续"""
    from agent import graph as graph_mod

    monkeypatch.setattr(graph_mod, "TOOLS", [SlowTool()])
    monkeypatch.setenv("TOOL_TIMEOUT_SECONDS", "0.05")
    r = asyncio.run(graph_mod.tools_node(_tool_call_state("slow_tool", {})))
    assert r["messages"][0].content.startswith("slow_tool执行失败")


def test_tools_node_normal_tool(monkeypatch):
    """正常工具路径：超时包装不影响正常结果"""
    from agent import graph as graph_mod
    from agent.tools import calculator

    monkeypatch.setattr(graph_mod, "TOOLS", [calculator])
    r = asyncio.run(
        graph_mod.tools_node(_tool_call_state("calculator", {"expression": "23+5"}))
    )
    assert "28" in r["messages"][0].content
