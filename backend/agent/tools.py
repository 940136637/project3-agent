import json
import os
import httpx
from dotenv import load_dotenv
from langchain_core.tools import tool
import ast
import operator

load_dotenv()

ALLOWED_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def _eval(node):
    # 叶子节点：只认数字
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    # 二元运算：运算符必须在白名单里
    if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPS:
        left = _eval(node.left)
        right = _eval(node.right)
        return ALLOWED_OPS[type(node.op)](left, right)
    # 一元负号（如 -3）
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand)
    # 其他任何节点（函数调用、import、下标……）→ 拒绝
    raise ValueError("不支持的表达式")


@tool
def calculator(expression: str) -> str:
    """计算四则运算数学表达式，如 "23+5"。"""
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval(tree.body)
        return f"结果：{result}"
    except Exception as e:
        return f"计算失败：{e}"


@tool
def chart_generate(chart_type: str, title: str, categories: list, series: list) -> str:
    """生成 ECharts 图表配置。series 每项是 {"name": str, "data": list}。"""
    support_types = ["bar", "line", "pie"]
    if chart_type not in support_types:
        return f"图表生成失败：不支持的图表类型"
    option = {
        "title": {"text": title},
        "tooltip": {},
        "xAxis": {"type": "category", "data": categories},
        "yAxis": {"type": "value"},
        "series": [
            {"name": s["name"], "type": chart_type, "data": s["data"]} for s in series
        ],
    }
    return json.dumps(option, ensure_ascii=False)


# ---------------------- ③ weather_query 高德天气查询 ----------------------
@tool
def weather_query(city: str, days: int) -> str:
    """查询城市未来几天天气预报。days 取值范围 1-4。"""
    try:
        # 钳制范围 1~4
        days = min(max(days, 1), 4)
        api_key = os.getenv("AMAP_API_KEY")
        params = {"key": api_key, "city": city, "extensions": "all"}
        resp = httpx.get(
            "https://restapi.amap.com/v3/weather/weatherInfo", params=params, timeout=10
        )
        data = resp.json()
        # 高德status=1才代表成功
        if data.get("status") != "1":
            raise ValueError(f"高德接口返回status={data.get('status')}")

        forecasts_all = data["forecasts"][0]["casts"]
        take = forecasts_all[:days]
        output = {"city": city, "forecasts": take}
        return json.dumps(output, ensure_ascii=False)
    except Exception as e:
        return f"天气查询失败：{e}"


TOOLS = [weather_query, chart_generate, calculator]
