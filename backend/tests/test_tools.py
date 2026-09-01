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
        r = chart_generate.invoke(
            {
                "chart_type": "bar",
                "title": "合肥4天温度",
                "categories": ["09-01", "09-02", "09-03", "09-04"],
                "series": [{"name": "温度", "data": [31, 28, 26, 29]}],
            }
        )
        opt = json.loads(r)
        assert opt["title"]["text"] == "合肥4天温度"
        assert opt["xAxis"]["type"] == "category"
        assert opt["xAxis"]["data"] == ["09-01", "09-02", "09-03", "09-04"]
        assert opt["yAxis"]["type"] == "value"
        assert opt["series"][0]["type"] == "bar"
        assert opt["series"][0]["name"] == "温度"
        assert opt["series"][0]["data"] == [31, 28, 26, 29]


class TestWeatherQuery:
    # 与高德真实返回结构一致：forecasts 按城市分组，casts 才是天气数组
    FAKE = {
        "status": "1",
        "forecasts": [
            {
                "city": "合肥市",
                "adcode": "340100",
                "casts": [
                    {
                        "date": "2026-09-01",
                        "week": "1",
                        "dayweather": "晴",
                        "nightweather": "多云",
                        "daytemp": "31",
                        "nighttemp": "22",
                    },
                    {
                        "date": "2026-09-02",
                        "week": "2",
                        "dayweather": "阴",
                        "nightweather": "小雨",
                        "daytemp": "28",
                        "nighttemp": "21",
                    },
                    {
                        "date": "2026-09-03",
                        "week": "3",
                        "dayweather": "小雨",
                        "nightweather": "阴",
                        "daytemp": "26",
                        "nighttemp": "19",
                    },
                    {
                        "date": "2026-09-04",
                        "week": "4",
                        "dayweather": "多云",
                        "nightweather": "晴",
                        "daytemp": "29",
                        "nighttemp": "20",
                    },
                    {
                        "date": "2026-09-05",
                        "week": "5",
                        "dayweather": "晴",
                        "nightweather": "晴",
                        "daytemp": "30",
                        "nighttemp": "21",
                    },
                ],
            }
        ],
    }

    def test_returns_structured_json(self, monkeypatch):
        monkeypatch.setattr(
            httpx,
            "get",
            lambda *a, **kw: httpx.Response(200, json=self.FAKE),
        )
        r = weather_query.invoke({"city": "合肥", "days": 2})
        data = json.loads(r)
        assert data["city"] == "合肥"
        assert len(data["forecasts"]) == 2
        assert data["forecasts"][0]["daytemp"] == "31"

    def test_days_clamped_to_4(self, monkeypatch):
        monkeypatch.setattr(
            httpx,
            "get",
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
