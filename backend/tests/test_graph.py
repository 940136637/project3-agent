from agent.graph import build_graph


def test_calculator_reasoning_chain():
    """最短链路：问算术 → agent 调 calculator → 观察结果 → 回答 28"""
    graph = build_graph()
    result = graph.invoke(
        {"messages": [("user", "算一下 23 加 5")]},
        config={"recursion_limit": 15},
    )
    messages = result["messages"]
    answer = messages[-1].content
    assert "28" in answer
    tool_msgs = [m for m in messages if m.type == "tool"]
    assert tool_msgs, "预期过程中至少有一次工具调用"


def test_no_tool_question_answered_directly():
    """无需工具的闲聊问题：不调工具直接答"""
    graph = build_graph()
    result = graph.invoke(
        {"messages": [("user", "你好")]},
        config={"recursion_limit": 15},
    )
    assert len(result["messages"]) >= 2
