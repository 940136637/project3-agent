"""trace.py 事件协议单元测试（伪造 astream_events 流，不调真实 LLM）

覆盖两种工具轮形状：
  单工具轮：一轮思考只调一个工具（Task 4 原形状）
  双工具轮：一轮思考并行调两个工具（Task 7 联调抓到的真实模型行为）

协议要求（按 id 路由升级版）：
  - 每个 step_start 的 step_idx 唯一，且恰好有一个 step_end 配对
  - thinking / tool_call / tool_result / chart 事件 data 都带 step_idx，
    且等于自己宿主步骤的 id
  - 每个工具步的事件顺序：tool_call → tool_result → (chart) → step_end
"""

import asyncio
import json
from types import SimpleNamespace

from agent import trace


def chunk(content="", tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls or [])


CHART_OPTION = json.dumps(
    {"title": {"text": "温度"}, "series": [{"name": "温度", "data": [1]}]},
    ensure_ascii=False,
)

# 事件脚本：(event, name或node, data)
SCRIPT = [
    # 第 1 轮：思考 → 调 calculator（单工具）
    ("on_chat_model_start", "agent", {"chunk": chunk()}),
    ("on_chat_model_stream", "agent", {"chunk": chunk("算一下")}),
    ("on_chat_model_end", "agent",
     {"output": chunk("", [{"name": "calculator", "args": {"expression": "23+5"}}])}),
    ("on_tool_end", "calculator", {"output": "结果：28"}),
    # 第 2 轮：思考 → 并行调 chart_generate + calculator（双工具，bug 场景）
    ("on_chat_model_start", "agent", {"chunk": chunk()}),
    ("on_chat_model_stream", "agent", {"chunk": chunk("画图并计算")}),
    ("on_chat_model_end", "agent",
     {"output": chunk("", [
         {"name": "chart_generate",
          "args": {"chart_type": "bar", "title": "温度",
                   "categories": ["a"], "series": [{"name": "温度", "data": [1]}]}},
         {"name": "calculator", "args": {"expression": "1+2"}},
     ])}),
    ("on_tool_end", "chart_generate", {"output": CHART_OPTION}),
    ("on_tool_end", "calculator", {"output": "结果：3"}),
    # 第 3 轮：思考 → 直接回答
    ("on_chat_model_start", "agent", {"chunk": chunk()}),
    ("on_chat_model_stream", "agent", {"chunk": chunk("组织回答")}),
    ("on_chat_model_end", "agent", {"output": chunk("最终答案")}),
]


class FakeGraph:
    """伪造 compiled graph：astream_events 按 SCRIPT 逐个 yield"""

    def __init__(self, events):
        self._events = events

    async def astream_events(self, *args, **kwargs):
        for event, name_or_node, data in self._events:
            is_chat_model = event.startswith("on_chat_model")
            yield {
                "event": event,
                "name": name_or_node,
                "metadata": {"langgraph_node": "agent" if is_chat_model else "tools"},
                "data": data,
            }


def collect(monkeypatch):
    """跑一遍 stream_trace，收集全部 (事件名, data) 元组"""
    monkeypatch.setattr(trace, "build_graph", lambda: FakeGraph(SCRIPT))
    out = []

    async def run():
        async for ev in trace.stream_trace("测试问题"):
            out.append(ev)

    asyncio.run(run())
    return out


class TestStreamTraceProtocol:
    def test_start_and_done(self, monkeypatch):
        events = collect(monkeypatch)
        assert events[0] == ("start", {})
        assert events[-1] == ("done", {})
        assert not any(name == "error" for name, _ in events)

    def test_every_step_event_carries_matching_step_idx(self, monkeypatch):
        events = collect(monkeypatch)
        steps = {}  # step_idx -> 该步的事件名列表（保持出现顺序）
        for name, data in events:
            if name == "step_start":
                steps[data["step_idx"]] = ["step_start"]
            elif name in ("thinking", "tool_call", "tool_result", "chart", "step_end"):
                assert "step_idx" in data, f"{name} 事件缺 step_idx 字段"
                steps.setdefault(data["step_idx"], []).append(name)

        assert set(steps) == {1, 2, 3, 4, 5, 6}, f"步骤 id 集合不对: {set(steps)}"

        # 思考步：step_start → thinking → step_end
        for sid in (1, 3, 6):
            assert steps[sid] == ["step_start", "thinking", "step_end"], f"思考步 {sid} 序列不对: {steps[sid]}"
        # 单工具步：step_start → tool_call → tool_result → step_end
        assert steps[2] == ["step_start", "tool_call", "tool_result", "step_end"], f"calculator 步序列不对: {steps[2]}"
        # 双工具轮：chart_generate 步必须自带 chart 且不被 calculator 抢走
        assert steps[4] == ["step_start", "tool_call", "tool_result", "chart", "step_end"], \
            f"chart_generate 步序列不对（chart 被串到别的步骤了？）: {steps[4]}"
        assert steps[5] == ["step_start", "tool_call", "tool_result", "step_end"], \
            f"calculator 步序列不对: {steps[5]}"

    def test_tool_result_ok_and_chart_option(self, monkeypatch):
        events = collect(monkeypatch)
        results = {d["step_idx"]: (d["tool_name"], d["ok"])
                   for name, d in events if name == "tool_result"}
        assert results[2] == ("calculator", True)
        assert results[4] == ("chart_generate", True)
        assert results[5] == ("calculator", True)
        charts = {d["step_idx"]: d["option"] for name, d in events if name == "chart"}
        assert charts[4]["series"][0]["name"] == "温度"

    def test_answer_and_done(self, monkeypatch):
        events = collect(monkeypatch)
        answers = [d["text"] for name, d in events if name == "answer"]
        assert answers == ["最终答案"]
