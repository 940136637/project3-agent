"""LangGraph 执行过程 → 前端 trace 事件流。

事件顺序（前后端契约）：
start → 多轮 (step_start/thinking/tool_call/tool_result/chart/step_end) → answer → done

T1 变更：工具步改为在「tools 节点结束」时按 tool_call_id 收口，而不是等 on_tool_end。
原因：工具超时后 run_tool_with_timeout 只是不再等待，工具线程可能迟到完成并补发
on_tool_end——若按事件到达顺序收口，面板会把一个已经超时的步骤标成成功。以节点
输出（ToolMessage）为准，既杜绝这种串台，也不再依赖并行工具的完成顺序。
"""

import json

from agent.graph import build_graph


def _drain_pending(pending_steps: list) -> list:
    """把没拿到 ToolMessage 的工具步按失败收口。

    pending_steps: [(step_idx, tool_name, tool_call_id)]，原地清空，返回待发事件列表。
    """
    events = []
    for step_id, tool_name, _call_id in pending_steps:
        events.append(
            (
                "tool_result",
                {
                    "tool_name": tool_name,
                    "result": "工具执行失败:超时或被中断,没有拿到结果",
                    "ok": False,
                    "step_idx": step_id,
                },
            )
        )
        events.append(("step_end", {"step_idx": step_id}))
    pending_steps.clear()
    return events


async def stream_trace(question: str):
    """async generator：逐个 yield (事件名, data) 元组"""
    yield ("start", {})

    step_idx = 0
    # 已开步、还没收口的工具步：(step_idx, tool_name, tool_call_id)
    pending_steps = []
    try:
        async for ev in build_graph().astream_events(
            {"messages": [("user", question)]},
            config={"recursion_limit": 15},
            version="v2",
        ):
            name = ev["event"]
            node = ev["metadata"].get("langgraph_node")

            if name == "on_chat_model_start" and node == "agent":
                # 上一轮还有工具步没收口（工具超时/节点异常）→ 先按失败收口
                for pending_ev in _drain_pending(pending_steps):
                    yield pending_ev
                # 开思考步：step_idx 自增 → yield ("step_start", {"step_idx": ..., "type": "thinking"})
                step_idx += 1
                yield ("step_start", {"step_idx": step_idx, "type": "thinking"})
            elif name == "on_chat_model_stream" and node == "agent":
                # content 非空才 yield ("thinking", {"text": ...})
                chunk = ev["data"]["chunk"]
                if chunk.content:
                    yield ("thinking", {"text": chunk.content, "step_idx": step_idx})
            elif name == "on_chat_model_end" and node == "agent":
                chunk = ev["data"]["output"]
                tool_calls = chunk.tool_calls
                yield ("step_end", {"step_idx": step_idx})
                # 两种结局：
                #   有 tool_calls → 关思考步；每个 tool_call 开工具步 + yield tool_call
                if tool_calls:
                    for tc in tool_calls:
                        step_idx += 1
                        pending_steps.append((step_idx, tc["name"], tc["id"]))
                        yield ("step_start", {"step_idx": step_idx, "type": "tool"})
                        yield (
                            "tool_call",
                            {
                                "tool_name": tc["name"],
                                "args": tc["args"],
                                "step_idx": step_idx,
                            },
                        )
                #   无 tool_calls → 关思考步 + yield ("answer", {"text": ...})
                else:
                    yield ("answer", {"text": chunk.content})
            elif name == "on_chain_end" and node == "tools":
                # tools 节点输出 {"messages": [ToolMessage...]}：按 tool_call_id 精确认领
                messages = (ev["data"].get("output") or {}).get("messages", [])
                by_call_id = {m.tool_call_id: m for m in messages}
                remaining = []
                for step_id, tool_name, call_id in pending_steps:
                    msg = by_call_id.get(call_id)
                    if msg is None:
                        remaining.append((step_id, tool_name, call_id))
                        continue
                    result = msg.content if isinstance(msg.content, str) else str(msg.content)
                    # 失败消息契约：工具失败文本以 "XX失败" 开头
                    ok = "失败" not in result
                    yield (
                        "tool_result",
                        {
                            "tool_name": tool_name,
                            "result": result,
                            "ok": ok,
                            "step_idx": step_id,
                        },
                    )
                    if tool_name == "chart_generate" and ok:
                        yield ("chart", {"option": json.loads(result), "step_idx": step_id})
                    yield ("step_end", {"step_idx": step_id})
                pending_steps[:] = remaining
        # 图正常结束但仍有未收口的工具步（防御性兜底）
        for pending_ev in _drain_pending(pending_steps):
            yield pending_ev
        yield ("done", {})
    except Exception as e:
        yield ("error", {"detail": str(e)})
