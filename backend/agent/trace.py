"""LangGraph 执行过程 → 前端 trace 事件流。

事件顺序（前后端契约，Task 5/6 依赖）：
start → 多轮 (step_start/thinking/tool_call/tool_result/chart/step_end) → answer → done
"""

import json

from agent.graph import build_graph


async def stream_trace(question: str):
    """async generator：逐个 yield (事件名, data) 元组"""
    yield ("start", {})

    step_idx = 0

    try:
        async for ev in build_graph().astream_events(
            {"messages": [("user", question)]},
            config={"recursion_limit": 15},
            version="v2",
        ):
            name = ev["event"]
            node = ev["metadata"].get("langgraph_node")

            if name == "on_chat_model_start" and node == "agent":
                # 开思考步：step_idx 自增 → yield ("step_start", {"step_idx": ..., "type": "thinking"})
                step_idx += 1
                yield ("step_start", {"step_idx": step_idx, "type": "thinking"})
            elif name == "on_chat_model_stream" and node == "agent":
                # content 非空才 yield ("thinking", {"text": ...})
                chunk = ev["data"]["chunk"]
                if chunk.content:
                    yield ("thinking", {"text": chunk.content})
            elif name == "on_chat_model_end" and node == "agent":
                chunk = ev["data"]["output"]
                tool_calls = chunk.tool_calls
                yield ("step_end", {"step_idx": step_idx})
                # 两种结局：
                #   有 tool_calls → 关思考步；每个 tool_call 开工具步 + yield tool_call
                if tool_calls:
                    for tc in tool_calls:
                        step_idx += 1
                        yield ("step_start", {"step_idx": step_idx, "type": "tool"})
                        yield (
                            "tool_call",
                            {
                                "tool_name": tc["name"],
                                "args": tc["args"],
                            },
                        )
                #   无 tool_calls → 关思考步 + yield ("answer", {"text": ...})
                else:
                    yield ("answer", {"text": chunk.content})
            elif name == "on_tool_end":
                # tool_result；chart_generate 且 ok → json.loads 后 yield ("chart", {...})
                # 最后关工具步
                result = ev["data"]["output"]
                ok = "失败" not in result
                yield (
                    "tool_result",
                    {"tool_name": ev["name"], "result": result, "ok": ok},
                )
                if ev["name"] == "chart_generate" and ok:
                    yield ("chart", {"option": json.loads(result)})
                yield ("step_end", {"step_idx": step_idx})
        yield ("done", {})
    except Exception as e:
        yield ("error", {"detail": str(e)})
