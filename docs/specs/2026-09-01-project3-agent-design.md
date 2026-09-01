# 项目 3 设计文档：Web 可视化 AI 工具 Agent

- 日期：2026-09-01（完整版）
- 状态：✅ 已定稿（用户委托 Claude 按求职市场最优决策，9 项决策全部经 brainstorming 逐题确认）
- 决策方式：brainstorming architectural 流程（9 个澄清题 + 设计呈现）+ 用户委托定稿

## 1. 背景与目标

学习计划第 3 个月压轴项目，简历排序第一的差异化王牌：**纯 Python 选手做不出的 Vue 可视化 Agent 链路面板**。验收锚点：一句话复杂指令 → Agent 分步调用工具 → 前端全程可视化可演示；GitHub README + 演示 GIF。

简历文案锚点（设计不得偏离）：

> 基于 LangGraph + FastAPI 构建可观测 Web AI Agent；支持 Function Calling 自定义工具调度、多轮 ReAct 任务规划、异常重试；Vue3 实现 Agent 执行链路可视化面板，实时展示思考过程与工具调用日志；可自动完成"查询数据→生成 ECharts 图表→生成总结报告"多步骤任务

## 2. 已确认决策表（2026-09-01）

| # | 决策点 | 结论 |
|---|---|---|
| Q1 | 核心演示场景 | 「查合肥未来 4 天天气，画温度柱状图，算平均温度，写出行建议」——四步三轮 ReAct 循环（**4 天**：高德免费天气 API extensions=all 只返回今天+未来 3 天共 4 条，实测文档约束） |
| Q2 | 天气数据源 | 高德天气 API（真实数据，key 走 `.env`，与项目 2 同模式） |
| Q3 | Agent 实现路线 | 手搭 LangGraph StateGraph（与项目 2 的 create_agent 差异化，简历深度靠它） |
| Q4 | 链路面板形态 | 步骤时间线（非树形）：状态徽章实时点亮、工具步骤可展开、图表内嵌渲染 |
| Q5 | 学习顺序 | 已完成补课（黑马 Agent 02/04/05 + LangGraph 官方 ReAct 教程） |
| Q6 | 工具清单 | 3 个：weather_query + chart_generate + calculator（计算器 10 行代码换一轮演示） |
| Q7 | chart_generate 边界 | 工具 = 确定性 Python 代码构造完整 ECharts option 返回（LLM 只决策不画图） |
| Q8 | 在线 Demo 口径 | 录屏 GIF + Docker 一键启动 + 面试现场笔记本演示（海外托管国内不稳，已实测） |
| Q9 | 图结构 | 标准 ReAct 双节点循环（agent ⇄ tools），不做 Planner 节点（v2 话题） |

## 3. 总体架构

```
用户一句话指令（Vue 聊天输入）
  → POST /api/chat/stream (SSE，项目 2 已验证姿势)
  → FastAPI → LangGraph StateGraph（手搭 ReAct）
      agent 节点 ⇄ tools 节点（weather_query / chart_generate / calculator）
  → 每一步产生 trace 事件（SSE 单流回前端）
  → 前端双区渲染：
     左区 = 聊天区（最终回答流式，项目 2 同款）
     右区 = Agent 链路面板（步骤时间线实时点亮 + 图表内嵌）
```

技术栈全部沿用已会技术：Python 3.14 + FastAPI + LangGraph 1.2（手搭图）+ httpx；Vue 3.5 + TS + Vite + ECharts 5；Docker Compose 部署。**零新框架**。目录结构沿用项目 2 monorepo：`backend/`（main.py + rag 等价物 agent 包）+ `frontend/` + `docs/` + `screenshots/`。

## 4. 后端设计

### 4.1 图结构（LangGraph StateGraph，手搭）

- **状态**：`MessagesState`（LangGraph 内置 TypedDict：`messages: Annotated[list, add_messages]`，add_messages 是 reducer——同名消息按 id 去重，这就是多轮上下文的基础）
- **agent 节点**：LLM（deepseek-chat，项目 2 同配置）读状态 messages 输出 AI 消息——带 tool_calls 或最终回答
- **tools 节点**：按 tool_calls 逐个执行（本项目工具都快，串行够用），结果以 ToolMessage 追加
- **条件边**：agent 输出最后一条消息有 tool_calls → tools 节点；否则 → END
- **recursion_limit=15**（防死循环；面试点：三步演示 15 轮绰绰有余，超了就说明 Agent 失控）

### 4.2 三个工具（@tool 装饰器，LangChain 标准接口）

| 工具 | 签名 | 关键实现 |
|---|---|---|
| `weather_query` | `(city: str, days: int) -> str` | httpx 调高德天气 API（`/v3/weather/weatherInfo?city=&extensions=all`），返回结构化 JSON 文本；days 超出 1-4 时**钳制为 4**（高德免费版最多今天+未来 3 天）；key 走 `.env`；接口失败**返回错误文本**让模型知道（不是抛异常——ReAct 的观察环节需要"知道失败"） |
| `chart_generate` | `(chart_type, title, categories: list, series: list[dict]) -> str` | 确定性 Python 代码构造完整 ECharts option 并 JSON 序列化返回；纯函数无 LLM 参与；trace 层按工具名识别图表事件（见 4.3，不需要返回值里埋标记） |
| `calculator` | `(expression: str) -> str` | `ast` 白名单解析（四则运算），**绝不直接 eval**（安全，面试点）；非法表达式返回错误文本 |

### 4.3 trace 事件协议（SSE 单流）

图执行全程的事件序列（面板的数据源全部来自图执行本身，不是前端事后拼——这就是"可观测"）：

| 事件 | data | 含义 |
|---|---|---|
| `start` | `{}` | 握手（v1 无历史持久化，不需要 thread_id） |
| `step_start` | `{step_idx, type: "thinking"\|"tool"}` | 一个步骤开始（时间线新条目） |
| `thinking` | `{text}` | agent 节点 LLM 思考文本流式 |
| `tool_call` | `{tool_name, args}` | 模型决定调用工具 |
| `tool_result` | `{tool_name, result, ok}` | 工具执行结果（ok=false 即错误观察） |
| `chart` | `{option}` | chart_generate 产物，前端直接 setOption |
| `step_end` | `{step_idx}` | 步骤结束 |
| `answer` | `{text}` | 最终回答全文（非流式——面板是主角，思考流式、回答整段） |
| `done` | `{}` | 结束 |
| `error` | `{detail}` | 异常兜底（GraphRecursionError 等），前端提示用户 |

实现方式：`graph.astream_events(version="v2")`（项目 2 已验证姿势）——`on_chat_model_stream` 给思考 token 流；`on_chat_model_end` 的 `tool_calls` 给 tool_call 步骤边界、`on_tool_end` 给工具结果；节点归属用事件 `metadata["langgraph_node"]` 识别；chart 事件 = trace 层检测到工具名为 `chart_generate` 且结果合法时把 JSON 解析成 option 转发。

## 5. 前端设计

### 5.1 布局

- **左区（聊天区）**：消息列表 + 输入框；回答由 `answer` 事件整段渲染（v1 回答非流式，思考流式——面板是主角）；"新对话"按钮重置会话
- **右区（Agent 链路面板）**：本次差异化核心，卡片式步骤时间线

### 5.2 链路面板状态机

步骤条目模型（前端 TS `TraceStep`）：`{id, type: thinking|tool, status: running|done|error, title, detail?, args?, ok?, chartOption?}`

- `step_start` → 新增条目，status=running（思考类显示三点动画，工具类显示齿轮）
- `thinking` → 追加到当前思考条目的 detail
- `tool_call` → 工具条目显示参数（可折叠的 JSON 预览）
- `tool_result` → 工具条目 status=done（ok=false 标红）；展开看返回内容
- `chart` → 工具条目下内嵌渲染 ECharts（复用你大屏经验：setOption + resize 监听）
- `step_end` → 条目定稿；`answer` → 聊天区渲染最终回答；`done` → 面板整体完成态

SSE 消费用 fetch + ReadableStream 手动解析（POST 无法用 EventSource，项目 2 已验证同款姿势）。

## 6. 错误处理与重试

| 场景 | 策略 |
|---|---|
| 工具执行失败（高德超时/表达式非法） | 工具返回错误文本（不抛异常）→ ToolMessage 进观察环节 → **LLM 自主决定换参数重试或向用户说明**（ReAct 天然重试机制，面试点） |
| Agent 失控（反复调工具） | recursion_limit=15，超出由 LangGraph 抛 GraphRecursionError → 后端转 `error` 事件给前端提示 |
| 高德 key 缺失 | 后端启动时检查，缺失打日志警告（不影响启动，运行时工具返回明确错误文本）；`.env.example` 写获取指引 |
| SSE 断线 | 前端捕获流异常，提示"连接中断，请重试"（v1 不做断线续传） |

## 7. 测试与验收

### 7.1 测试（pytest，项目 2 模式）

- **工具单测**：chart_generate（option 结构断言：有 title/xAxis/series 且数值对）、calculator（四则运算 + 非法表达式拒绝 + `__import__` 等注入尝试被拒）、weather_query（httpx mock 高德响应，不真打接口）
- **图集成测试**：真实 LLM 跑一条最短指令（"算一下 23 加 5"），断言工具 calculator 被调用且最终答案含 28
- **SSE 契约测试**：httpx 流式消费，断言事件序列完整（start→…→done）

### 7.2 验收清单（对齐学习计划）

1. 一句话指令「查合肥未来 4 天天气，画温度柱状图，算平均温度，写出行建议」→ 面板看到 4 步、3 种工具、ReAct 循环 3 轮 ✅
2. 柱状图正确渲染在面板内（ECharts option 由 chart_generate 确定性生成）✅
3. 链路面板实时点亮（思考动画→工具齿轮→结果→图表），截图/GIF 存档 ✅
4. 演示录屏 GIF 进 README；docker compose up 一键启动 ✅
5. 推 GitHub（网络恢复后）✅

## 8. 部署与交付

- Docker Compose 前后端（项目 2 全套姿势复用：多阶段构建、.dockerignore、registry mirror 提示、单 worker）
- `.env` 含 `DEEPSEEK_API_KEY` + `AMAP_API_KEY`（高德 key 注册：高德开放平台控制台免费申请 Web 服务 key）
- README：架构图 + 演示 GIF + 三步启动 + 面试口径附录
- 演示 GIF：本地 Docker 演示时用 Xbox Game Bar（Win+G）录屏 30 秒，截取四步链路

## 9. 面试口径（每个组件的"为什么"）

| 组件 | 口径 |
|---|---|
| 手搭 StateGraph | "create_agent 是黑盒预置，手搭让我控制节点粒度、能拿到每个节点的执行事件做可视化" |
| Function Calling | "模型不是被 if 控制——把工具 schema 喂给模型，模型自主输出 tool_call，框架执行回传，这就是 Function Calling" |
| chart_generate 确定性 | "图表配置由代码确定性生成，不依赖模型输出——杜绝 LLM 生成非法 ECharts option" |
| calculator 安全 | "用 ast 白名单解析而不是 eval，防代码注入" |
| 失败重试 | "工具失败返回错误文本进观察环节，模型自主决定重试或放弃——ReAct 的天然容错；recursion_limit 兜底防死循环" |
| 可观测 | "链路面板数据全部来自图执行本身的事件流，不是前端事后拼装" |
| SSE 选型 | "单向事件流用 SSE 足够，比 WebSocket 更简单且代理友好" |
| 不做项 | "v1 不做 Planner 任务分解、多工具并行、Memory 持久化——YAGNI，场景不需要；这是 v2 路线" |

## 10. v1 明确不做

- Planner 任务分解节点（Q9 已定）
- WebSocket / 多工具并行执行
- 对话历史持久化（每次刷新即新会话，与项目 2 的 InMemorySaver 取舍同理）
- 在线托管部署（Q8 已定口径：GIF + 现场演示）
- 文档读写工具（Q6 已否）

## 11. 实施顺序建议（供 writing-plans 细化）

1. 项目脚手架：git init + 前后端目录 + requirements/package（项目 2 模板起步）
2. 后端三工具 + 单测（不依赖 LLM，最稳的地基）
3. StateGraph 手搭 + trace 事件转换层 + 图集成测试
4. SSE 接口 + 契约测试
5. 前端聊天区（项目 2 迁移）+ 链路面板 + chart 渲染
6. 联调验收（四步演示 + 截图）
7. Docker + README + GIF + GitHub
