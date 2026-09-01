import os

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph

from agent.tools import TOOLS

load_dotenv()

llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

llm_with_tools = llm.bind_tools(TOOLS)

SYSTEM_PROMPT = "你是数据助手：可以查天气、生成图表、做计算。优先调用工具获取事实，再根据工具结果组织中文回答。"


def build_graph():
    g = StateGraph(MessagesState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
    g.add_edge("tools", "agent")
    return g.compile()


def agent_node(state: MessagesState) -> dict:
    # 1. 消息列表 = [SystemMessage(SYSTEM_PROMPT)] + state["messages"]
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    # 2. ai_msg = llm_with_tools.invoke(那个列表)
    ai_msg = llm_with_tools.invoke(messages)
    # 3. return {"messages": [ai_msg]}
    return {"messages": [ai_msg]}


def tools_node(state: MessagesState) -> dict:
    # 1. 取最后一条消息的 tool_calls（可能多个）
    last_ai_msg = state["messages"][-1]
    # 2. 名字→工具映射：{t.name: t for t in TOOLS}
    tool_map = {t.name: t for t in TOOLS}
    tool_msg_list = []
    # 3. 逐个执行 t.invoke(call["args"])，结果包装成
    for call in last_ai_msg.tool_calls:
        tool_func = tool_map[call["name"]]
        res = tool_func.invoke(call["args"])
        tm = ToolMessage(content=str(res), tool_call_id=call["id"], name=call["name"])
        tool_msg_list.append(tm)
    #    ToolMessage(content=str(结果), tool_call_id=call["id"], name=call["name"])
    # 4. return {"messages": [所有 ToolMessage 的列表]}
    return {"messages": tool_msg_list}


def should_continue(state: MessagesState) -> str:
    last_msg = state["messages"][-1]
    if last_msg.tool_calls:
        return "tools"
    return "end"
    # 最后一条消息有 tool_calls → "tools"，否则 → "end"
