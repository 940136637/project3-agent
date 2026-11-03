import os

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph

from agent.resilience import get_config, llm_retry, run_tool_with_timeout
from agent.tools import TOOLS

load_dotenv()

llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
    # 单次调用超时：网络卡住时 SDK 自己会中断，不会无限等
    timeout=get_config().llm_timeout_seconds,
    # 关闭 SDK 内建重试：重试统一交给 tenacity 层，否则两层重试叠加、次数失控
    max_retries=0,
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


async def agent_node(state: MessagesState) -> dict:
    # 配置在调用时读取：环境变量可热调，测试也能注入零退避
    cfg = get_config()

    @llm_retry(cfg)
    async def _invoke(messages):
        # 用 ainvoke 而不是 invoke：节点是 async 的，阻塞式调用会卡住整个事件循环
        return await llm_with_tools.ainvoke(messages)

    # 1. 消息列表 = [SystemMessage(SYSTEM_PROMPT)] + state["messages"]
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    # 2. 带超时与指数退避重试地调用模型（网络抖动/限流/5xx 自动重试，重试耗尽才上抛）
    ai_msg = await _invoke(messages)
    # 3. return {"messages": [ai_msg]}
    return {"messages": [ai_msg]}


async def tools_node(state: MessagesState) -> dict:
    # 1. 取最后一条消息的 tool_calls（可能多个）
    last_ai_msg = state["messages"][-1]
    # 2. 名字→工具映射：{t.name: t for t in TOOLS}
    tool_map = {t.name: t for t in TOOLS}
    timeout_seconds = get_config().tool_timeout_seconds
    tool_msg_list = []
    # 3. 逐个执行，每个工具都有统一超时兜底；工具没跑完就返回失败观察，链路不死
    for call in last_ai_msg.tool_calls:
        tool_func = tool_map.get(call["name"])
        if tool_func is None:
            # 模型幻觉出一个不存在的工具：降级成错误观察，让模型自己纠正，不让图崩
            content = f"工具调用失败:模型请求了不存在的工具 {call['name']}"
        else:
            content = str(
                await run_tool_with_timeout(tool_func, call["args"], timeout_seconds)
            )
        tm = ToolMessage(
            content=content, tool_call_id=call["id"], name=call["name"]
        )
        tool_msg_list.append(tm)
    # 4. return {"messages": [所有 ToolMessage 的列表]}
    return {"messages": tool_msg_list}


def should_continue(state: MessagesState) -> str:
    last_msg = state["messages"][-1]
    if last_msg.tool_calls:
        return "tools"
    return "end"
    # 最后一条消息有 tool_calls → "tools"，否则 → "end"
