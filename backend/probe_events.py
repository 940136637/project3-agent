import asyncio

from agent.graph import build_graph


async def main():
    graph = build_graph()
    async for ev in graph.astream_events(
        {"messages": [("user", "算一下 23 加 5")]},
        config={"recursion_limit": 15},
        version="v2",
    ):
        name = ev["event"]
        node = ev["metadata"].get("langgraph_node", "-")
        data = ev["data"]
        if name == "on_chat_model_stream":
            print(f"{node:>5} {name:20} content={data['chunk'].content!r}")
        elif name == "on_chat_model_end":
            chunk = data["output"]
            if chunk.tool_calls:
                print(
                    f"{node:>5} {name:20} tool_calls={[(t['name'], t['args']) for t in chunk.tool_calls]}"
                )
            else:
                print(f"{node:>5} {name:20} content={chunk.content!r}")
        elif name in ("on_chat_model_start", "on_tool_start", "on_tool_end"):
            extra = f" tool={ev['name']!r}" if ev.get("name") else ""
            if name == "on_tool_end":
                extra += f" output={data['output']!r}"
            print(f"{node:>5} {name:20}{extra}")
        else:
            print(f"{node:>5} {name:20} (其他事件)")


asyncio.run(main())
