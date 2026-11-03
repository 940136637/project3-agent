# T1 超时·重试·降级 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 project3-agent 的 LLM 调用与工具执行加上超时、指数退避重试与失败降级,链路在任何单点故障下不死、错误如实上报。

**Architecture:** 新增 `agent/resilience.py` 统一承载配置(环境变量可调)与重试/超时策略;`graph.py` 的 LLM 调用用 tenacity 包装(关闭 SDK 内建重试,避免双重重试),`tools_node` 改 async 并给每个工具统一加 `asyncio.wait_for` 超时兜底与未知工具兜底;`tools.py` 的天气 HTTP 调用按"可恢复错误才重试"原则重试,失败消息如实报告重试次数。SSE 事件契约与前端协议零改动。

**Tech Stack:** Python + tenacity + langchain-openai(ChatOpenAI)/langgraph + httpx + pytest(离线 fake,不新增 pytest 插件)

**Spec:** `D:\study\企业级工程化学习计划.md` §4 T1(设计文档 v2)

## Global Constraints

- **SSE 事件契约不动**:`trace.py` / `main.py` 的事件名、data 结构与前端面板协议零改动
- **失败消息契约不动**:工具失败消息必须仍以 "X失败" 开头(既有 `trace.py` 的 `"失败" not in result` 判定、既有测试断言均依赖)
- **测试离线**:新增测试一律 fake LLM / monkeypatch `httpx.get`,不调真实 API;`test_graph.py` 中既有 2 例真实 LLM 集成测试保留原样,仅作手动冒烟
- **运行命令**:一律 `cd backend && .venv/Scripts/python.exe -m pytest tests/... -v`;代码注释中文,风格与现有文件一致
- **Git**:先在 `t1-timeout-retry-degradation` 分支工作,收口时合并回 main;每个 commit 消息末尾加 `Co-Authored-By: Claude Code <noreply@anthropic.com>`
- 不新增 pytest 插件(测试中用 `asyncio.run(...)` 驱动 async 函数)

## Review Focus

1. **幻觉/不存在的工具名**(模型编造 tool 名)→ `tools_node` 不崩溃、返回"工具不存在"消息 → Task 3 测试覆盖
2. **工具超时后线程仍在跑**(`to_thread` 无法强杀线程)→ 至少"不再等待"并返回超时消息 → Task 3 测试覆盖
3. **LLM 持续失败** → 重试耗尽后异常向上抛,由既有 `error` SSE 事件兜底,不静默吞掉 → Task 2 测试覆盖
4. **HTTP 4xx**(参数/鉴权错误,重试无意义)→ 立即失败且消息如实报"已重试0次" → Task 4 测试覆盖
5. **HTTP 5xx 重试耗尽** → 消息如实报告实际重试次数(tenacity statistics),不谎报 → Task 4 测试覆盖

---

### Task 1: resilience 配置模块 + 测试基建

**Files:**
- Create: `backend/agent/resilience.py`
- Create: `backend/tests/test_resilience.py`
- Modify: `backend/conftest.py`(当前为空文件,新增 autouse fixture)
- Modify: `backend/requirements.txt`(新增 tenacity)

**Interfaces:**
- Produces(后续任务依赖):
  - `ResilienceConfig`(frozen dataclass)字段与默认值:
    `llm_timeout_seconds: float = 60`、`llm_max_retries: int = 2`、`tool_timeout_seconds: float = 60`、`weather_http_timeout_seconds: float = 10`、`weather_max_retries: int = 2`、`retry_wait_min_seconds: float = 1.0`、`retry_wait_max_seconds: float = 10.0`
  - `get_config() -> ResilienceConfig`:按名读环境变量(全部可选,缺省用上面默认值)——`LLM_TIMEOUT_SECONDS`、`LLM_MAX_RETRIES`、`TOOL_TIMEOUT_SECONDS`、`WEATHER_HTTP_TIMEOUT_SECONDS`、`WEATHER_MAX_RETRIES`、`RETRY_WAIT_MIN_SECONDS`、`RETRY_WAIT_MAX_SECONDS`;非法值(如 "abc")抛 `ValueError`(fail fast,不静默回退)

- [ ] **Step 1: 建工作分支**

```bash
git switch -c t1-timeout-retry-degradation
```

- [ ] **Step 2: 写失败测试** `backend/tests/test_resilience.py`

```python
from agent.resilience import get_config, ResilienceConfig


def test_defaults():
    cfg = get_config()
    assert cfg.llm_timeout_seconds == 60
    assert cfg.llm_max_retries == 2
    assert cfg.tool_timeout_seconds == 60
    assert cfg.weather_http_timeout_seconds == 10
    assert cfg.weather_max_retries == 2
    assert cfg.retry_wait_min_seconds == 1.0
    assert cfg.retry_wait_max_seconds == 10.0


def test_env_override(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("LLM_MAX_RETRIES", "5")
    cfg = get_config()
    assert cfg.llm_timeout_seconds == 30
    assert cfg.llm_max_retries == 5


def test_invalid_env_raises(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "abc")
    import pytest
    with pytest.raises(ValueError):
        get_config()
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_resilience.py -v`
Expected: FAIL(ImportError: No module named 'agent.resilience')

- [ ] **Step 4: 实现 `backend/agent/resilience.py`**

模块 docstring 说明职责:健壮性配置与重试/超时策略的统一入口。`get_config()` 每次调用都重新读环境变量(不在模块级缓存),注释说明:这让配置可热生效、测试可注入。int/float 转换失败时 `raise ValueError(f"环境变量 {name} 值非法: {val}")`。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_resilience.py -v`
Expected: 3 passed

- [ ] **Step 6: 装 tenacity 并固化为精确版本**

```bash
cd backend && .venv/Scripts/python.exe -m pip install tenacity
.venv/Scripts/python.exe -m pip show tenacity   # 拿到版本号
```

把 `tenacity==<解析到的版本>` 追加到 `backend/requirements.txt`(沿用文件内 `==` 精确固定风格)。

- [ ] **Step 7: conftest 加"零等待重试"fixture** `backend/conftest.py`

```python
import pytest


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    """所有测试零退避等待:重试立即发生,测试不因指数退避变慢"""
    monkeypatch.setenv("RETRY_WAIT_MIN_SECONDS", "0")
    monkeypatch.setenv("RETRY_WAIT_MAX_SECONDS", "0")
```

并在 `test_resilience.py` 加一条证明它生效的测试:

```python
def test_fast_retries_fixture():
    cfg = get_config()
    assert cfg.retry_wait_min_seconds == 0
    assert cfg.retry_wait_max_seconds == 0
```

- [ ] **Step 8: 全量跑测试确认无回归**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 既有用例全过(2 例真实 LLM 集成测试需网络与 key)+ 新增 4 例过

- [ ] **Step 9: Commit**

```bash
git add backend/agent/resilience.py backend/tests/test_resilience.py backend/conftest.py backend/requirements.txt
git commit -m "feat(resilience): 新增健壮性配置模块(超时/重试参数环境变量化)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: LLM 调用超时 + 自动重试

**Files:**
- Modify: `backend/agent/resilience.py`(新增 `llm_retry` 工厂)
- Modify: `backend/agent/graph.py`(llm 构造参数 + agent_node 调用包装)
- Modify: `backend/tests/test_graph.py`(新增 FakeLLM 与 3 例离线测试)
- Modify: `backend/requirements.txt`(openai 从传递依赖转直接依赖)

**Interfaces:**
- Consumes: Task 1 的 `get_config()` / `ResilienceConfig`
- Produces: `def llm_retry(cfg: ResilienceConfig)` —— 返回一个 tenacity 装饰器,配置为:`reraise=True`、`stop=stop_after_attempt(cfg.llm_max_retries + 1)`、`wait=wait_exponential(multiplier=1, min=cfg.retry_wait_min_seconds, max=cfg.retry_wait_max_seconds)`、`retry=retry_if_exception_type((openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError, openai.InternalServerError))`。不用 wait_random 抖动(注释说明:生产可加抖动防惊群,本模块保持确定性便于测试,讲法里讲)

- [ ] **Step 1: 写失败测试** `backend/tests/test_graph.py` 追加(文件头补 `import pytest` 与 `from openai import APIConnectionError`、`from langchain_core.messages import AIMessage`)

```python
class FakeLLM:
    """可配置失败次数的假模型:先失败 fail_times 次,之后返回固定回答"""

    def __init__(self, fail_times: int, answer: str = "答:28"):
        self.fail_times = fail_times
        self.answer = answer
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise APIConnectionError("模拟网络抖动")
        return AIMessage(content=self.answer, tool_calls=[])


def test_llm_transient_failure_recovers(monkeypatch):
    """LLM 第一次失败,tenacity 自动重试后成功,链路不中断"""
    from agent import graph as graph_mod
    fake = FakeLLM(fail_times=1)
    monkeypatch.setattr(graph_mod, "llm_with_tools", fake)
    result = graph_mod.build_graph().invoke(
        {"messages": [("user", "你好")]},
        config={"recursion_limit": 15},
    )
    assert result["messages"][-1].content == "答:28"
    assert fake.calls == 2


def test_llm_persistent_failure_raises(monkeypatch):
    """LLM 持续失败:重试耗尽后异常上抛,交给既有 error 事件兜底,不静默"""
    from agent import graph as graph_mod
    fake = FakeLLM(fail_times=99)
    monkeypatch.setattr(graph_mod, "llm_with_tools", fake)
    with pytest.raises(APIConnectionError):
        graph_mod.build_graph().invoke(
            {"messages": [("user", "你好")]},
            config={"recursion_limit": 15},
        )
    assert fake.calls == 3  # 默认 llm_max_retries=2 → 共 3 次尝试


def test_llm_timeout_configured():
    from agent import graph as graph_mod
    assert graph_mod.llm.timeout == 60.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_graph.py::test_llm_transient_failure_recovers tests/test_graph.py::test_llm_persistent_failure_raises tests/test_graph.py::test_llm_timeout_configured -v`
Expected: FAIL(test_llm_transient_failure_recovers 与 test_llm_persistent_failure_raises 失败:无重试行为)

- [ ] **Step 3: 实现 `llm_retry` 工厂** `backend/agent/resilience.py`

按 Interfaces 给出的精确配置实现,文件头补充 openai 异常类的 import。

- [ ] **Step 4: 改造 `backend/agent/graph.py`**

两处改动:
1. llm 构造:`llm = ChatOpenAI(model="deepseek-chat", api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com", timeout=get_config().llm_timeout_seconds, max_retries=0)` —— 注释:SDK 内建重试关闭,重试统一交给 tenacity 层,避免双重重试叠加
2. `agent_node` 改为调用时构建装饰器(配置每次调用都读,测试的零等待环境变量才生效):

```python
def agent_node(state: MessagesState) -> dict:
    cfg = get_config()

    @llm_retry(cfg)
    def _invoke(messages):
        return llm_with_tools.invoke(messages)

    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    ai_msg = _invoke(messages)
    return {"messages": [ai_msg]}
```

- [ ] **Step 5: openai 转直接依赖**

```bash
cd backend && .venv/Scripts/python.exe -m pip show openai   # 拿版本号
```

把 `openai==<版本号>` 追加到 `backend/requirements.txt`(代码现在直接 import openai 异常类,不能只靠传递依赖)。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_graph.py -v`
Expected: 新增 3 例过;既有 2 例真实 LLM 集成测试预期过(需网络+key)

- [ ] **Step 7: Commit**

```bash
git add backend/agent/resilience.py backend/agent/graph.py backend/tests/test_graph.py backend/requirements.txt
git commit -m "feat(agent): LLM 调用加超时与指数退避自动重试

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 工具执行超时 + 未知工具兜底

**Files:**
- Modify: `backend/agent/resilience.py`(新增 `run_tool_with_timeout` 与 `is_5xx_error`)
- Modify: `backend/agent/graph.py`(`tools_node` 改 async)
- Modify: `backend/tests/test_resilience.py`(helper 2 例)
- Modify: `backend/tests/test_graph.py`(3 例)

**Interfaces:**
- Consumes: Task 1 的 `get_config()`
- Produces(供 Task 4 使用):
  - `async def run_tool_with_timeout(tool, args: dict, timeout_seconds: float) -> str` —— `asyncio.wait_for(asyncio.to_thread(tool.invoke, args), timeout=timeout_seconds)`;捕获 `asyncio.TimeoutError` 返回 `f"{tool.name}执行超时(超过{timeout_seconds}秒),已中断"`。注释必须写明:to_thread 无法强杀线程,超时只是"不再等待",所以工具内部必须有 HTTP 级超时兜底(Task 4)
  - `def is_5xx_error(e: Exception) -> bool` —— `isinstance(e, httpx.HTTPStatusError) and e.response.status_code >= 500`
- `tools_node` 契约:`async def tools_node(state: MessagesState) -> dict`;对每个 tool_call:名字不在 `tool_map` 里 → 生成 `ToolMessage(content=f"工具不存在:{call['name']}", tool_call_id=call["id"], name=call["name"])` 并 continue(不崩溃);否则 `res = await run_tool_with_timeout(tool_func, call["args"], get_config().tool_timeout_seconds)`,照旧包装 ToolMessage。返回 `{"messages": tool_msg_list}` 不变。

- [ ] **Step 1: 写失败测试** `backend/tests/test_resilience.py` 追加

```python
import asyncio


class SlowTool:
    name = "slow_tool"

    def invoke(self, args):
        import time
        time.sleep(0.2)
        return "慢结果"


class FastTool:
    name = "fast_tool"

    def invoke(self, args):
        return "快结果"


def test_run_tool_timeout_returns_message():
    r = asyncio.run(run_tool_with_timeout(SlowTool(), {}, 0.05))
    assert r.startswith("slow_tool执行超时")


def test_run_tool_success_returns_result():
    r = asyncio.run(run_tool_with_timeout(FastTool(), {}, 5))
    assert r == "快结果"
```

- [ ] **Step 2: 写失败测试** `backend/tests/test_graph.py` 追加(文件头补 `import asyncio` 与 `from langchain_core.messages import AIMessage`——若 Task 2 已补过 AIMessage 则跳过)

```python
class SlowTool:
    name = "slow_tool"

    def invoke(self, args):
        import time
        time.sleep(0.2)
        return "慢结果"


def _tool_call_state(name: str, args: dict):
    return {
        "messages": [
            AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "t1"}])
        ]
    }


def test_tools_node_unknown_tool_returns_fallback():
    from agent import graph as graph_mod
    # 未知工具名:即使 TOOLS 里有别的工具也不该崩
    r = asyncio.run(graph_mod.tools_node(_tool_call_state("no_such", {})))
    assert r["messages"][0].content.startswith("工具不存在")


def test_tools_node_timeout_returns_message(monkeypatch):
    from agent import graph as graph_mod
    monkeypatch.setattr(graph_mod, "TOOLS", [SlowTool()])
    r = asyncio.run(graph_mod.tools_node(_tool_call_state("slow_tool", {})))
    assert r["messages"][0].content.startswith("slow_tool执行超时")
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_resilience.py tests/test_graph.py -v`
Expected: FAIL(helper 与 tools_node 相关新测试失败:tools_node 还是同步版本/无 helper)

- [ ] **Step 4: 实现 `run_tool_with_timeout` 与 `is_5xx_error`** `backend/agent/resilience.py`

按 Interfaces 实现;`is_5xx_error` 供 Task 4 的重试谓词使用,本任务先落代码与单测。

- [ ] **Step 5: 改造 `tools_node` 为 async** `backend/agent/graph.py`

按 Interfaces 的契约实现;`build_graph()` 本身不用改(LangGraph 原生支持 async 节点)。既有的"逐条执行并包装 ToolMessage"逻辑保留,只把 `tool_func.invoke(...)` 换成 `await run_tool_with_timeout(...)`。

- [ ] **Step 6: 补一条正常工具路径测试** `backend/tests/test_graph.py`

```python
def test_tools_node_normal_tool(monkeypatch):
    from agent import graph as graph_mod
    from agent.tools import calculator
    monkeypatch.setattr(graph_mod, "TOOLS", [calculator])
    r = asyncio.run(
        graph_mod.tools_node(_tool_call_state("calculator", {"expression": "23+5"}))
    )
    assert "28" in r["messages"][0].content
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_resilience.py tests/test_graph.py -v`
Expected: 全绿(真实 LLM 2 例需网络+key)

- [ ] **Step 8: 全链路手动验证(SSE 契约未破坏)**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/test_trace.py tests/test_chat_stream.py -v
```

Expected: trace/chat_stream 既有用例全过,事件契约未变。

- [ ] **Step 9: Commit**

```bash
git add backend/agent/resilience.py backend/agent/graph.py backend/tests/test_resilience.py backend/tests/test_graph.py
git commit -m "feat(agent): 工具执行统一超时兜底与未知工具降级

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 天气 HTTP 重试 + 失败消息如实报告

**Files:**
- Modify: `backend/agent/tools.py`(`weather_query` 内部)
- Modify: `backend/tests/test_tools.py`(`TestWeatherQuery` 追加 4 例)

**Interfaces:**
- Consumes: Task 1 的 `get_config()`;Task 3 的 `is_5xx_error`
- Produces: 无新导出;`weather_query` 签名与返回 JSON 结构不变。失败消息新格式:`f"天气查询失败(已重试{N}次):{e}"`,N 取 `_fetch.retry.statistics["attempt_number"] - 1`(tenacity 的 Retrying 统计,如实反映实际重试次数)

- [ ] **Step 1: 写失败测试** `backend/tests/test_tools.py` 的 `TestWeatherQuery` 追加

```python
def test_5xx_retried_then_succeeds(self, monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500)
        return httpx.Response(200, json=self.FAKE)

    monkeypatch.setattr(httpx, "get", flaky)
    r = weather_query.invoke({"city": "合肥", "days": 2})
    assert json.loads(r)["city"] == "合肥"
    assert calls["n"] == 2  # 500 → 重试 → 成功


def test_5xx_exhausted_reports_retry_count(self, monkeypatch):
    calls = {"n": 0}

    def always_500(*a, **kw):
        calls["n"] += 1
        return httpx.Response(500)

    monkeypatch.setattr(httpx, "get", always_500)
    r = weather_query.invoke({"city": "合肥", "days": 2})
    assert r.startswith("天气查询失败")
    assert "已重试2次" in r  # weather_max_retries=2,如实报告
    assert calls["n"] == 3


def test_4xx_not_retried(self, monkeypatch):
    calls = {"n": 0}

    def bad_key(*a, **kw):
        calls["n"] += 1
        return httpx.Response(403)

    monkeypatch.setattr(httpx, "get", bad_key)
    r = weather_query.invoke({"city": "合肥", "days": 2})
    assert r.startswith("天气查询失败")
    assert "已重试0次" in r  # 4xx 重试无意义,立即失败
    assert calls["n"] == 1


def test_timeout_retried_then_succeeds(self, monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.TimeoutException("第一次超时")
        return httpx.Response(200, json=self.FAKE)

    monkeypatch.setattr(httpx, "get", flaky)
    r = weather_query.invoke({"city": "合肥", "days": 2})
    assert json.loads(r)["city"] == "合肥"
    assert calls["n"] == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_tools.py -v`
Expected: 新增 4 例 FAIL(当前无重试逻辑);既有 3 例仍 PASS

- [ ] **Step 3: 改造 `weather_query`** `backend/agent/tools.py`

只改函数内部(签名、成功路径 JSON 结构、days 钳制、`status != "1"` 业务校验全部保留)。重试装饰器**在函数体内每次调用时构建**(配置热生效 + 测试零等待注入):

```python
@tool
def weather_query(city: str, days: int) -> str:
    """查询城市未来几天天气预报。days 取值范围 1-4。"""
    cfg = get_config()

    @retry(
        reraise=True,
        stop=stop_after_attempt(cfg.weather_max_retries + 1),
        wait=wait_exponential(multiplier=1, min=cfg.retry_wait_min_seconds, max=cfg.retry_wait_max_seconds),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)) | retry_if_exception(is_5xx_error),
    )
    def _fetch(params: dict) -> httpx.Response:
        # 4xx 由 raise_for_status 抛出且不在重试谓词内 → 立即失败
        # 5xx 同样抛出,但被 is_5xx_error 接住 → 重试
        resp = httpx.get(
            "https://restapi.amap.com/v3/weather/weatherInfo",
            params=params,
            timeout=cfg.weather_http_timeout_seconds,
        )
        resp.raise_for_status()
        return resp

    try:
        days = min(max(days, 1), 4)
        params = {"key": os.getenv("AMAP_API_KEY"), "city": city, "extensions": "all"}
        resp = _fetch(params)
        data = resp.json()
        if data.get("status") != "1":
            raise ValueError(f"高德接口返回status={data.get('status')}")  # 业务错误,重试无意义

        forecasts_all = data["forecasts"][0]["casts"]
        take = forecasts_all[:days]
        output = {"city": city, "forecasts": take}
        return json.dumps(output, ensure_ascii=False)
    except Exception as e:
        retries = _fetch.retry.statistics["attempt_number"] - 1
        return f"天气查询失败(已重试{retries}次):{e}"
```

文件头补充 import:tenacity 的 `retry/stop_after_attempt/wait_exponential/retry_if_exception_type/retry_if_exception`,以及 `from agent.resilience import get_config, is_5xx_error`。保留原 `timeout=10` 的语义(由 `weather_http_timeout_seconds` 默认 10 承接)。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_tools.py -v`
Expected: 7 例全过(既有 3 例不改动也必须过——`test_network_error_returns_text_not_exception` 的 `startswith("天气查询失败")` 断言在新消息格式下仍成立)

- [ ] **Step 5: Commit**

```bash
git add backend/agent/tools.py backend/tests/test_tools.py
git commit -m "feat(tools): 天气 HTTP 调用指数退避重试,失败消息如实报告重试次数

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: README 收口 + 全量回归 + 合并发布

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README 新增「健壮性设计」小节**

放在现有架构说明之后,内容要点:①三层防护——LLM 调用超时+指数退避重试、工具统一超时兜底(超时不再等待,线程不可杀故工具内部有 HTTP 超时)、HTTP 重试只针对可恢复错误(连接/超时/5xx,4xx 与业务错误立即失败)②失败消息统一"X失败(已重试N次)"格式,trace 面板据此标红 ③环境变量配置表:7 个变量(名称/默认值/含义)。

- [ ] **Step 2: 全量回归**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: 全部通过(离线用例全绿;2 例真实 LLM 集成测试需网络+key,预期过)

- [ ] **Step 3: 提交并推送分支**

```bash
git add README.md
git commit -m "docs: README 增加健壮性设计与配置说明(T1 收口)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
git push -u origin t1-timeout-retry-degradation
```

- [ ] **Step 4: 合并回 main 并推送**

```bash
git switch main
git merge --no-ff t1-timeout-retry-degradation -m "feat: T1 超时·重试·降级加固收口

Co-Authored-By: Claude Code <noreply@anthropic.com>"
git push
```

- [ ] **Step 5: 验收对照设计文档自检**

对照 `D:\study\企业级工程化学习计划.md` §4 T1 验收项:①人为制造工具超时/失败链路不死 ✓(Task 3 测试)②LLM 失败自动重试可恢复 ✓(Task 2 测试)③pytest 覆盖 ✓(新增 16 例离线测试)。全部满足后在设计文档进度处勾选 T1。

---

## 执行记录(2026-11-03)

结果:`pytest tests/` **35 passed**(T1 新增 20 例);全链路真实冒烟通过。以下为执行中相对计划的必要偏离,均已验证:

1. **`agent_node` 也改为 async + `ainvoke`**:LangGraph 中只要存在 async 节点,`graph.invoke`(同步)就不可用("No synchronous function provided"),故 `agent_node`/`tools_node` 同时异步化。
2. **既有 2 例真实 LLM 图测试改 `ainvoke`**:`graph.invoke` → `asyncio.run(graph.ainvoke(...))`,断言不变。
3. **超时/未知工具消息以"失败"开头**:计划的 `f"{tool.name}执行超时…"` 会被 trace 的 `"失败" not in result` 判成 ok=True(面板标绿),违反"失败消息契约"。改为 `X执行失败:超时(…),已放弃等待` / `工具调用失败:模型请求了不存在的工具 X`。
4. **trace.py 有改动(计划原定零改动)**:工具超时后线程迟到补发 `on_tool_end`,会领走已超时的步骤并标成成功(已实测复现)。改为在 `tools` 节点 `on_chain_end` 按 `tool_call_id` 认领 ToolMessage 收口,并对缺结果的步骤兜底失败收口;思考轮开始时 `_drain_pending` 兜底。
5. **重试次数统计改读 `_fetch.statistics`**:tenacity 9.1.4 中 `f.retry.statistics` 为空,统计挂在被装饰函数上;读错会永远显示"已重试 0 次"。
6. **测试 mock 补 `request=REQ`**:httpx 0.28 的 `raise_for_status()` 要求响应带 request,否则抛 RuntimeError。
7. **`test_defaults` 需先清退避环境变量**:conftest 的 autouse fixture 把它设为 0;`llm.timeout` 断言改为 `llm.request_timeout`(langchain-openai 1.5.1 字段名)。

遗留:`AMAP_API_KEY` 当前返回 `INVALID_USER_KEY`(status=0),天气演示需换有效免费 key;T1 行为符合设计(业务错误不重试、降级作答)。
