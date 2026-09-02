import asyncio
import json

import httpx

from main import app


def test_chat_stream_contract():
    """真实 LLM 最短链路，断言 SSE 事件序列契约"""
    asyncio.run(_collect())


async def _collect():
    transport = httpx.ASGITransport(app=app)
    events = []
    answer = ""
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST",
            "/api/chat/stream",
            json={"question": "算一下 23 加 5"},
        ) as resp:
            assert resp.status_code == 200
            current_event = None
            async for line in resp.aiter_lines():
                if line.startswith("event: "):
                    current_event = line[7:]
                elif line.startswith("data: ") and current_event:
                    data = json.loads(line[6:])
                    events.append(current_event)
                    if current_event == "answer":
                        answer = data["text"]

    # 事件序列契约
    assert events[0] == "start"
    assert events[-1] == "done"
    assert "step_start" in events
    assert "tool_call" in events
    assert "tool_result" in events
    assert "answer" in events
    # 业务正确性
    assert "28" in answer
    # 思考事件与步骤边界配对
    step_starts = [i for i, e in enumerate(events) if e == "step_start"]
    step_ends = [i for i, e in enumerate(events) if e == "step_end"]
    assert len(step_starts) == len(step_ends)
