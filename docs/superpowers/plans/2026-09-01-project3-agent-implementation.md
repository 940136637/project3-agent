# 项目 3 实施计划：Web 可视化 AI 工具 Agent

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一句话指令「查合肥未来 4 天天气，画温度柱状图，算平均温度，写出行建议」→ 手搭 LangGraph ReAct Agent 分步调用 3 个工具 → Vue 链路面板全程可视化，形成求职差异化王牌项目。

**Architecture:** FastAPI 后端手搭 StateGraph（agent 节点 ⇄ tools 节点条件循环），`astream_events` v2 把图执行过程翻译成 SSE trace 事件流；Vue 3 前端双区布局——左区聊天、右区步骤时间线面板（思考流式、图表内嵌渲染）。

**Tech Stack:** Python 3.14 + FastAPI + LangGraph 1.2.11（手搭图）+ langchain-openai（deepseek-chat）+ httpx；Vue 3.5 + TS + Vite + ECharts 5；pytest；Docker Compose。

**Spec:** `docs/specs/2026-09-01-project3-agent-design.md`（计划从 spec 论证，执行者两份都要读）

## Global Constraints

- 后端 venv：`backend/.venv`（PowerShell 命令用 `.\` 前缀 + 反斜杠；多命令用 `;` 连接，`&&` 不支持）
- LLM：`deepseek-chat`，`DEEPSEEK_API_KEY` 走根目录 `.env`；天气走高德 `AMAP_API_KEY`
- 版本锚点：`langgraph==1.2.11`、`langchain-core==1.5.6`（项目 2 锁定版本，复制项目 2 `backend/requirements.txt` 起步）
- **教学模式**：测试代码 Claude 给全（验收即测试）；**实现代码用户自己写**，Claude 逐行讲解 + 读磁盘 review + 贴输出验收
- 工具错误文本一律 `"XX失败：原因"` 开头（trace 层靠它判断 ok=false，别改约定）
- 中文回答；GBK 终端跑 Python 加 `PYTHONIOENCODING=utf-8`
- v1 不做：Planner 节点 / 多工具并行 / 历史持久化 / 在线托管 / 文档工具 / 断线续传
- 每次 commit 在对应 task 内完成，commit 前 `git status` 自查

---

### Task 1: 项目脚手架

**Files:**
- Create: `backend/requirements.txt`、`backend/main.py`、`backend/conftest.py`（空文件——pytest 会把它所在目录 backend/ 加进 sys.path，tests 才能 `from agent.tools import ...`）、`.env.example`、`.gitignore`
- Create: `frontend/`（vite vue-ts 脚手架 + proxy + echarts 依赖）

**Interfaces:**
- Produces: `main.py` 的 FastAPI app（Task 4 在它上面加 `/api/chat/stream`）；`backend/.venv`（所有 pytest 都用它跑）；前端 5173 端口 proxy `/api` → 8000

- [x] **Step 1: 创建后端 venv 并装依赖**

`requirements.txt` 直接复制项目 2 的（`D:\study\project2-rag\backend\requirements.txt`，版本锚点一致），另加 `httpx`（若没有）。PowerShell 在 `backend/` 下：

```powershell
cd backend; py -3.14 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

- [x] **Step 2: 写 hello 版 main.py**

```python
from fastapi import FastAPI

app = FastAPI(title="project3-agent")


@app.get("/health")
def health():
    return {"status": "ok"}
```

- [x] **Step 3: 验证后端能起**

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --port 8000
```

浏览器/curl 访问 `http://localhost:8000/health` → `{"status":"ok"}` 后 Ctrl+C 停掉。

- [x] **Step 4: 前端脚手架**

在项目根目录（PowerShell）：

```powershell
npm create vite@latest frontend -- --template vue-ts; cd frontend; npm install; npm install echarts
```

改 `frontend/vite.config.ts` 加 proxy（项目 2 同款）：

```ts
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
});
```

- [x] **Step 5: .env.example 与 .gitignore**

`.env.example`（根目录，注意每行尾换行）：

```
DEEPSEEK_API_KEY=在这里填你的DeepSeekkey
AMAP_API_KEY=在这里填你的高德Web服务key
```

`.gitignore` 复制项目 2 的（含 `.env`、`.venv/`、`node_modules/`、`dist/`、`__pycache__/`）。

- [x] **Step 6: 验证 + commit**

```powershell
cd frontend; npm run build
```

Expected: 全绿。然后：

```bash
git add -A; git commit -m "chore: 项目脚手架（后端 hello + 前端 vite + proxy）"
```

---

### Task 2: 三工具 + 单测（TDD）

**Files:**
- Create: `backend/agent/__init__.py`、`backend/agent/tools.py`
- Test: `backend/tests/test_tools.py`（测试代码全给，先写测试）

**Interfaces:**
- Produces（Task 3/4 依赖，签名一字不差）:
  - `weather_query(city: str, days: int) -> str`（@tool）
  - `chart_generate(chart_type: str, title: str, categories: list, series: list) -> str`（@tool）
  - `calculator(expression: str) -> str`（@tool）
  - `TOOLS = [weather_query, chart_generate, calculator]`
- 约定：weather_query 返回 `json.dumps({"city":..., "forecasts":[{date,week,dayweather,nightweather,daytemp,nighttemp}...]}, ensure_ascii=False)`，days 钳制 1-4；chart_generate 返回完整 ECharts option 的 JSON 字符串（含 title/xAxis/yAxis/series）；calculator 成功返回 `"结果：{值}"`；**所有失败返回 `"XX失败：原因"` 开头的文本，绝不抛异常**

- [x] **Step 1: 写测试**（`backend/tests/test_tools.py`，全给）

```python
import json

import httpx

from agent.tools import calculator, chart_generate, weather_query


class TestCalculator:
    def test_addition(self):
        r = calculator.invoke({"expression": "23+5"})
        assert "结果：28" in r

    def test_multiplication(self):
        r = calculator.invoke({"expression": "6*7"})
        assert "42" in r

    def test_invalid_expression_rejected(self):
        r = calculator.invoke({"expression": "hello"})
        assert r.startswith("计算失败")

    def test_code_injection_blocked(self):
        r = calculator.invoke({"expression": "__import__('os').system('echo hacked')"})
        assert r.startswith("计算失败")


class TestChartGenerate:
    def test_option_structure(self):
        r = chart_generate.invoke({
            "chart_type": "bar",
            "title": "合肥4天温度",
            "categories": ["09-01", "09-02", "09-03", "09-04"],
            "series": [{"name": "温度", "data": [31, 28, 26, 29]}],
        })
        opt = json.loads(r)
        assert opt["title"]["text"] == "合肥4天温度"
        assert opt["xAxis"]["type"] == "category"
        assert opt["xAxis"]["data"] == ["09-01", "09-02", "09-03", "09-04"]
        assert opt["yAxis"]["type"] == "value"
        assert opt["series"][0]["type"] == "bar"
        assert opt["series"][0]["name"] == "温度"
        assert opt["series"][0]["data"] == [31, 28, 26, 29]


class TestWeatherQuery:
    FAKE = {
        "status": "1",
        "forecasts": [
            {"date": "2026-09-01", "week": "1", "dayweather": "晴",
             "nightweather": "多云", "daytemp": "31", "nighttemp": "22"},
            {"date": "2026-09-02", "week": "2", "dayweather": "阴",
             "nightweather": "小雨", "daytemp": "28", "nighttemp": "21"},
        ],
    }

    def test_returns_structured_json(self, monkeypatch):
        monkeypatch.setattr(
            httpx, "get",
            lambda *a, **kw: httpx.Response(200, json=self.FAKE),
        )
        r = weather_query.invoke({"city": "合肥", "days": 2})
        data = json.loads(r)
        assert data["city"] == "合肥"
        assert len(data["forecasts"]) == 2
        assert data["forecasts"][0]["daytemp"] == "31"

    def test_days_clamped_to_4(self, monkeypatch):
        monkeypatch.setattr(
            httpx, "get",
            lambda *a, **kw: httpx.Response(200, json=self.FAKE),
        )
        r = weather_query.invoke({"city": "合肥", "days": 99})
        assert len(json.loads(r)["forecasts"]) <= 4

    def test_network_error_returns_text_not_exception(self, monkeypatch):
        def boom(*a, **kw):
            raise httpx.ConnectError("timeout")

        monkeypatch.setattr(httpx, "get", boom)
        r = weather_query.invoke({"city": "合肥", "days": 2})
        assert r.startswith("天气查询失败")
```

- [x] **Step 2: 跑测试确认红**

```powershell
cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_tools.py -v
```

Expected: FAIL（`ModuleNotFoundError: agent.tools` 或 import 错误——红得越早越好）

- [x] **Step 3: 自己写 `agent/tools.py`**（教学模式：逐行讲解时写）

要点（接口见上）：
- 三个函数都用 `from langchain_core.tools import tool` 的 `@tool` 装饰，docstring 写清用途与参数（模型靠它决策）
- `weather_query`：`load_dotenv()` 读 `AMAP_API_KEY`；`httpx.get("https://restapi.amap.com/v3/weather/weatherInfo", params={"key":..., "city": city, "extensions": "all"}, timeout=10)`；days 钳制 `min(max(days,1),4)` 截取 forecasts；整个请求包 try/except，失败返回 `f"天气查询失败：{e}"`
- `chart_generate`：确定性构造 option dict（title{text}、tooltip、xAxis{type:"category",data}、yAxis{type:"value"}、series 每项 {name, type: chart_type, data}），`json.dumps(..., ensure_ascii=False)`；chart_type 非法返回 `"图表生成失败：不支持的图表类型"`
- `calculator`：**用 `ast.parse` + 白名单节点类型**（Expression/BinOp/UnaryOp/Constant + 四则运算符），自己遍历节点求值；解析或计算异常返回 `f"计算失败：{e}"`。**绝不 eval**
- `TOOLS = [weather_query, chart_generate, calculator]`

- [x] **Step 4: 跑测试确认绿**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_tools.py -v
```

Expected: 8 passed

- [x] **Step 5: commit**

```bash
git add backend/agent backend/tests/test_tools.py; git commit -m "feat: 三工具（weather_query/chart_generate/calculator）+ 单测"
```

---

### Task 3: StateGraph 手搭 + 集成测试

**Files:**
- Create: `backend/agent/graph.py`
- Test: `backend/tests/test_graph.py`

**Interfaces:**
- Consumes: `TOOLS`（Task 2）
- Produces（Task 4 依赖）:
  - `build_graph()` — 返回 compiled graph，含节点 `agent`、`tools`
  - `graph.invoke({"messages": [("user", question)]}, config={"recursion_limit": 15})` 返回 `{"messages": [...]}`，最后一条 AI 消息即最终回答

- [x] **Step 1: 写集成测试**（`backend/tests/test_graph.py`，全给——真实 LLM，跑一次约 10 秒）

```python
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
```

- [x] **Step 2: 跑测试确认红**

Expected: FAIL（`ModuleNotFoundError: agent.graph`）

- [x] **Step 3: 自己写 `agent/graph.py`**（核心 Task，讲解重点：图结构/状态流/ReAct 循环）

结构（参考 LangGraph 官方 Build a ReAct agent 教程 + 黑马 Agent-04）：

```python
# 关键骨架（自己补全实现）
from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph

llm = ChatOpenAI(model="deepseek-chat", api_key=os.getenv("DEEPSEEK_API_KEY"),
                 base_url="https://api.deepseek.com")
llm_with_tools = llm.bind_tools(TOOLS)

SYSTEM_PROMPT = "你是数据助手：可以查天气、生成图表、做计算。优先调用工具获取事实，再根据工具结果组织中文回答。"

def agent_node(state: MessagesState): ...   # 返回 {"messages": [llm_with_tools.invoke(state["messages"])]}
def tools_node(state: MessagesState): ...   # 手写：遍历最后一条 AIMessage 的 tool_calls，
                                            # 按名字找到工具执行，每个结果包装成 ToolMessage(tool_call_id=...) 回写
def should_continue(state: MessagesState): ...  # 最后一条消息有 tool_calls → "tools"，否则 "end"

def build_graph():
    g = StateGraph(MessagesState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
    g.add_edge("tools", "agent")
    return g.compile()
```

教学点：`MessagesState` 内置 `messages: Annotated[list, add_messages]`（add_messages 是 reducer——同名消息按 id 去重，这就是"多轮对话状态"的基础）；`bind_tools` 把工具 schema 交给模型（Function Calling）；tools 节点返回 ToolMessage 回写、条件边看 `tool_calls` 决定循环还是结束；`recursion_limit` 在 invoke 的 config 里传（15）。

- [x] **Step 4: 跑测试确认绿**

Expected: 2 passed（约 20 秒，真实 LLM 调用）

- [x] **Step 5: commit**

```bash
git add backend/agent/graph.py backend/tests/test_graph.py; git commit -m "feat: 手搭 StateGraph ReAct（agent+tools 条件循环）"
```

---

### Task 4: trace 转换层 + SSE 接口 + 契约测试

**Files:**
- Create: `backend/agent/trace.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_chat_stream.py`

**Interfaces:**
- Consumes: `build_graph()`（Task 3）
- Produces（Task 5/6 前端依赖，事件名一字不差）:
  - `async def stream_trace(question: str)` — async generator，逐个 yield `(event, data)` 元组，顺序：`("start",{})` → 若干 `("step_start",{step_idx,type})` / `("thinking",{text})` / `("tool_call",{tool_name,args})` / `("tool_result",{tool_name,result,ok})` / `("chart",{option})` / `("step_end",{step_idx})` → `("answer",{text})` → `("done",{})`；异常时 yield `("error",{"detail":...})`
  - `main.py`：`POST /api/chat/stream`，请求体 `{"question": str}`，SSE 帧格式 `event: 事件名\ndata: {json}\n\n`

- [x] **Step 1: 写契约测试**（`backend/tests/test_chat_stream.py`，全给）

```python
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
            "POST", "/api/chat/stream",
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
```

- [x] **Step 2: 跑测试确认红**

Expected: FAIL（接口不存在，404 或断言失败）

- [x] **Step 3: 自己写 `agent/trace.py`**（本 Task 最难，讲解重点：astream_events 事件语义）

要点：
- `async for ev in build_graph().astream_events({"messages": [("user", question)]}, config={"recursion_limit": 15}, version="v2")`
- 用 `ev["event"]` + `ev["metadata"].get("langgraph_node")` 分类：
  - `on_chat_model_start`（agent 节点）→ `("step_start", {"step_idx": 自增, "type": "thinking"})`
  - `on_chat_model_stream`（agent 节点）→ `chunk.content` 非空则 `("thinking", {"text": ...})`
  - `on_chat_model_end`（agent 节点）：`chunk.tool_calls` 非空 → 先 `("step_end", ...)` 关掉思考步，再为**每个** tool_call 依次 `("step_start", {"type": "tool"})` + `("tool_call", {"tool_name":..., "args":...})`；`tool_calls` 为空 → 先 `("step_end", ...)` 关掉思考步，再 `("answer", {"text": chunk.content})`（step_start/step_end 必须配对——契约测试在盯数量，漏了最后一个 step_end 必红）
  - `on_tool_end`：`output = ev["data"]["output"]`（ToolMessage）→ `("tool_result", {"tool_name": ev["name"], "result": output.content, "ok": not output.content.startswith("失败")})`；若 `ev["name"] == "chart_generate"` 且 ok → `json.loads(output.content)` 后 `("chart", {"option": ...})`；最后 `("step_end", ...)`
- 整体 try/except：异常 → `("error", {"detail": str(e)})`

- [x] **Step 4: 自己写 `main.py` 的 SSE 接口**（项目 2 同款姿势）

```python
class ChatStreamRequest(BaseModel):
    question: str


@app.post("/api/chat/stream")
async def chat_stream(req: ChatStreamRequest):
    async def gen():
        try:
            async for ev_name, data in stream_trace(req.question):
                yield f"event: {ev_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'detail': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
```

（需要 `from fastapi.responses import StreamingResponse`、`from pydantic import BaseModel`、`from agent.trace import stream_trace`）

- [x] **Step 5: 跑测试确认绿**

Expected: 1 passed（约 15 秒，真实 LLM）

- [x] **Step 6: 全量回归 + commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

Expected: 11 passed（Task 2 的 8 + Task 3 的 2 + 本 Task 的 1）。然后 commit：

```bash
git add backend/agent/trace.py backend/main.py backend/tests/test_chat_stream.py; git commit -m "feat: trace 事件流 + SSE 接口"
```

---

### Task 5: 前端聊天区

**Files:**
- Modify: `frontend/src/App.vue`（清掉 demo 内容，双区网格布局）
- Create: `frontend/src/api/index.ts`、`frontend/src/views/ChatView.vue`、`frontend/src/types.ts`
- Create: `frontend/src/components/TracePanel.vue`（本 Task 只建骨架占位，Task 6 实现）

**Interfaces:**
- Consumes: SSE 事件协议（Task 4）
- Produces（Task 6 依赖）:
  - `api/index.ts` 导出 `streamChat(question: string, onEvent: (name: string, data: any) => void, onDone: () => void, onError: (msg: string) => void): Promise<void>`
  - `frontend/src/types.ts` 导出 `TraceStep` 类型（Task 6 面板消费，本 Task 先落地）:
    ```ts
    export interface TraceStep {
      id: number;
      type: "thinking" | "tool";
      status: "running" | "done" | "error";
      title: string;       // 思考 / 工具名
      detail: string;      // thinking 累积文本 / 工具返回内容
      args?: string;       // tool_call 参数（JSON 字符串）
      ok?: boolean;        // tool_result.ok
      chartOption?: object; // chart 事件的 option
    }
    ```
  - `steps` 状态提升在 `App.vue`（ref 数组），以 prop 下传给 ChatView（写）与 TracePanel（读）——数组是共享引用，ChatView 只做 push/改属性，纪律与项目 2 同款
  - `ChatView` 是事件消费的唯一入口：把 SSE 事件翻译成状态变更（Task 6 只补翻译表实现；TracePanel 只接收 props，不碰 fetch）

- [x] **Step 1: 写 `api/index.ts`**（项目 2 同款 fetch + ReadableStream 解析 SSE）

接口如上。要点：`fetch("/api/chat/stream", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({question})})`；`resp.body.getReader()` + `TextDecoder` 按 `\n\n` 分帧，帧内解析 `event:` / `data:` 行后调 `onEvent(name, JSON.parse(data))`；流结束调 `onDone()`；异常调 `onError()`。（小心不可见字符坑：手动打的字符串里的连字符务必确认是 ASCII）

- [x] **Step 2: 写 `ChatView.vue`**（左区聊天）

- props：`defineProps<{ steps: TraceStep[] }>()`（Task 6 用它做事件翻译；本 Task 只在"新对话"时清空）
- 状态：`messages: {role: "user"|"assistant", content: string}[]`、`input`、`loading`
- 发送：push 用户消息 → `streamChat(input, handleEvent, ...)`；`handleEvent` 里只认 `answer` 事件（push assistant 消息）与 `error` 事件（push 错误提示）——其余事件转发给 Task 6 的面板状态逻辑（本 Task 先留 TODO 注释：`// Task 6: 事件驱动 steps`）
- "新对话"按钮：清空 messages + `steps.splice(0, steps.length)`（props 数组是共享引用，清空即生效）
- 样式从简：卡片式消息列表 + 底部输入框，加载中禁用发送

- [x] **Step 3: `App.vue` 双区布局**

```vue
<script setup lang="ts">
import { ref } from "vue";
import ChatView from "./views/ChatView.vue";
import TracePanel from "./components/TracePanel.vue";
import type { TraceStep } from "./types";

const steps = ref<TraceStep[]>([]);
</script>

<template>
  <div class="layout">
    <ChatView :steps="steps" class="left" />
    <TracePanel :steps="steps" class="right" />
  </div>
</template>
```

grid 两列（左 5 右 7 或接近），面板区标题"Agent 执行链路"。TracePanel 骨架 = `defineProps<{ steps: TraceStep[] }>()` + 标题占位，渲染留到 Task 6。

- [x] **Step 4: 验收（手动行为清单 + build）**

后端起 uvicorn（`cd backend; .\.venv\Scripts\python.exe -m uvicorn main:app --port 8000`），前端 `npm run dev`，浏览器 http://localhost:5173：

1. 发送"算一下 23 加 5"→ 聊天区出现回答，内容含 28 ✅
2. 发送"你好"→ 正常回答 ✅
3. 点"新对话"→ 消息清空 ✅
4. 后端停掉再发送 → 前端出现错误提示（不是白屏）✅

`npm run build` 全绿。满足后 commit：

```bash
git add frontend; git commit -m "feat: 前端聊天区 + SSE 事件消费入口"
```

---

### Task 6: 链路面板（本项目差异化核心）

**Files:**
- Modify: `frontend/src/components/TracePanel.vue`（骨架 → 完整实现）
- Modify: `frontend/src/views/ChatView.vue`（事件驱动 steps）

**Interfaces:**
- Consumes: `streamChat`（Task 5）；SSE 事件协议（Task 4）
- Produces:
  - `TraceStep` 类型：Task 5 已落地 `frontend/src/types.ts`，本 Task 直接消费
  - `TracePanel` props: `{ steps: TraceStep[] }`，纯展示组件

- [x] **Step 1: ChatView 里写事件 → steps 的翻译逻辑**（在 Task 5 的 TODO 处实现）

| 事件 | 对 steps 的操作 |
|---|---|
| `step_start` | push `{id: step_idx, type, status:"running", title: type==="thinking" ? "思考" : "", detail:""}` |
| `thinking` | 追加到**最后一个** thinking 条目的 detail（响应式：改数组最后一项的属性，项目 2 代理坑教训） |
| `tool_call` | 当前工具条目填 `title: tool_name`、`args: JSON.stringify(args, null, 2)` |
| `tool_result` | 当前工具条目：`detail = result`、`ok = ok`、`status = ok ? "done" : "error"` |
| `chart` | 当前工具条目：`chartOption = option`、`status = "done"` |
| `step_end` | 当前条目 `status` 若非 error 则置 "done" |
| `answer` | （聊天区用，面板不需要） |
| `done` | loading=false |
| `error` | 聊天区显示错误，面板当前条目标 error |

- [x] **Step 2: 实现 `TracePanel.vue`**

- 左列时间线：竖线 + 每步一个圆点徽章（thinking=running 时三点呼吸动画；tool=running 时转圈/齿轮）
- 每步卡片：徽章 + 标题 + 状态色（running 蓝 / done 绿 / error 红）
- 工具卡片：参数与返回内容放 `<details>` 折叠块（默认展开参数、折叠返回）
- `chartOption` 存在时：卡片内嵌 `<div ref>` 渲染 ECharts——`echarts.init` + `setOption(chartOption)` + `ResizeObserver` 自适应（你大屏经验直接复用）；组件卸载 `dispose`
- 纯 props 展示，不写 fetch、不写全局状态

- [x] **Step 3: 验收（手动行为清单 + build）**

后端 + 前端都起，发送「查合肥未来 4 天天气，画温度柱状图，算平均温度，写出行建议」：

1. 面板出现 ≥4 个步骤条目，实时点亮（思考动画 → 工具执行 → 完成变绿）✅
2. 三个工具名都出现在时间线里（weather_query / chart_generate / calculator）✅
3. 柱状图内嵌渲染在 chart_generate 卡片里（不是新窗口不是外链）✅
4. 聊天区出现出行建议回答 ✅
5. `npm run build` 全绿 ✅

满足后截图 1 张存档到 `screenshots/`（Win+Shift+S → 另存为），commit：

```bash
git add frontend screenshots; git commit -m "feat: Agent 执行链路可视化面板（时间线+图表内嵌）"
```

---

### Task 7: 联调验收（spec 7.2 前三项）

**Files:** 无代码改动（改 bug 除外）；产出 `screenshots/1-5.png`

**Interfaces:** 无新增

- [ ] **Step 1: 双端起服**

```powershell
cd backend; .\.venv\Scripts\python.exe -m uvicorn main:app --port 8000
```

```powershell
cd frontend; npm run dev
```

- [ ] **Step 2: 用户执行四步演示 + 截图**

浏览器发「查合肥未来 4 天天气，画温度柱状图，算平均温度，写出行建议」，在以下时机各截一张（另存为到 `screenshots/`）：

1. `1.png`：回答完成后整体画面（左聊天右面板全貌）
2. `2.png`：面板第一轮——思考步骤 running（动画中）
3. `3.png`：weather_query 工具卡片展开（参数 + 返回 JSON 可见）
4. `4.png`：chart_generate 卡片 + 内嵌柱状图
5. `5.png`：最终 done 全绿时间线（四步徽章全 done）

- [ ] **Step 3: Claude 服务器取证复核**（读磁盘截图验真 + httpx 复验）

- 5 张截图真存进 `screenshots/`（文件大小正常、内容与时机描述一致）
- httpx 脚本复跑同一条指令，逐帧断言：事件序列完整（start→…→done）、`tool_call` 三个工具名全部到场、`chart` 事件 option 含 series、`answer` 含"建议"
- 面板状态机与事件序列一致性抽查（step_start/step_end 数量配对）

- [ ] **Step 4: 验收清单勾选 + commit**

spec 7.2 第 1-3 项勾选。commit：

```bash
git add screenshots docs; git commit -m "docs: 联调验收截图（四步演示）"
```

---

### Task 8: Docker + README + GIF + GitHub

**Files:**
- Create: `backend/Dockerfile`、`frontend/Dockerfile`、`docker-compose.yml`、`backend/.dockerignore`、`frontend/.dockerignore`、`README.md`
- 产出：`screenshots/6.png`（Docker 环境验证截图）、`docs/demo.gif`（录屏 GIF）

**Interfaces:** 无新增；compose 环境变量 `DEEPSEEK_API_KEY`、`AMAP_API_KEY` 从根 `.env` 注入（项目 2 同款）

- [ ] **Step 1: 写 Dockerfile ×2 + .dockerignore ×2**（项目 2 姿势照搬）

backend：`python:3.14-slim`，多阶段不必要（无编译产物），`COPY requirements.txt` → pip install → `COPY . .` → `CMD uvicorn main:app`；frontend：build 阶段 node + `npm run build`，运行阶段 nginx 配 `/api/` 反代。两个 `.dockerignore` 务必排除 `.venv/`、`node_modules/`、`data/`、`dist/`（项目 2 血泪教训：无 dockerignore 会把 venv 打进去）。

- [ ] **Step 2: 写 docker-compose.yml + 构建起服**

```yaml
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    environment:
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - AMAP_API_KEY=${AMAP_API_KEY}
  frontend:
    build: ./frontend
    ports: ["80:80"]
    depends_on: [backend]
```

`docker compose up -d --build` → 浏览器 http://localhost 发四步指令 → 验收全过 → 截 `6.png`。

- [ ] **Step 3: 录演示 GIF**（README 主图）

Docker 环境下用 Xbox Game Bar（Win+G）录屏 30 秒：从输入指令到面板四步走完 + 图表渲染。用工具（如 ScreenToGif，免费）转成 gif 存 `docs/demo.gif`（控制在 ~5MB 内，太长就截关键帧）。

- [ ] **Step 4: README**（Claude 起草 + 用户 quiz 通关，项目 2 分工模式）

结构：项目介绍（一句话+演示 GIF）→ 核心亮点（可视化链路面板）→ 架构图 → 技术栈 → 本地开发步骤 → Docker 启动步骤 → trace 事件协议表 → 验收清单 → 面试口径（spec 第 9 节摘要）。quiz 三问过关才算完成。

- [ ] **Step 5: 推 GitHub**

GitHub 网页建 `project3-agent` 仓库（不要 README 初始化）→ `git remote add origin <你的地址>` → `git push -u origin main`（网络抽风就重试，看到 remote 输出才算成功；项目 2 的 push 也可能还在挂起，一并处理）。

---

## 计划自查记录（写作后执行）

1. **Spec 覆盖**：spec 3 架构 ↔ Task 1/4/5/6；spec 4.1 图 ↔ Task 3；4.2 工具 ↔ Task 2；4.3 事件协议 ↔ Task 4/6；spec 5 前端 ↔ Task 5/6；6 错误处理 ↔ Task 2（失败文本约定）/3（recursion_limit）/4（error 事件）；7 测试验收 ↔ Task 2/3/4/7；8 部署 ↔ Task 8；9 面试口径随 README ✅
2. **占位符扫描**：实现步骤均为"自己写+接口签名+要点"（教学模式决定），无 TBD；测试代码全部具名给全 ✅
3. **类型一致性**：`stream_trace` 事件名 Task 4 定义 ↔ Task 6 翻译表一一对应；`TraceStep` 字段与事件 data 键一致；`build_graph` 签名 Task 3 定义 ↔ Task 4 消费一致；工具错误"XX失败"前缀 Task 2 约定 ↔ Task 4 的 ok 判断一致 ✅
