from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from html import unescape
import json
from pathlib import Path
import re
import sys
from typing import Callable
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .mobile_tools import MobileTools, ScreenElement
from .qq_command import QqDeviceCommand


@dataclass(frozen=True)
class WebQueryResult:
    success: bool
    message: str
    detail: str
    url: str = ""


class BrowserWebQueryWorkflow:
    """Runs authorized web queries through the device browser."""

    _BROWSER_NOISE = {
        "Google", "Search", "Images", "Videos", "News", "Maps", "Shopping",
        "All", "More", "Tools", "Sign in", "登录", "全部", "图片", "视频",
        "新闻", "地图", "购物", "更多", "工具", "搜索", "新标签页",
        "Google Search", "Clear Search", "Search by voice", "AI Mode", "Forums",
        "Choose area", "How location is used", "Search Results", "Thinking",
        "About this result",
    }
    _BROWSER_NOISE_PARTS = (
        "search google or type url", "open the home page", "customize and control",
        "connection is secure", "tabs", "web view", "new tab", "double-tap to search",
    )

    def __init__(
        self,
        tools: MobileTools,
        device: str,
        *,
        settle_seconds: float = 0.8,
        browser_timeout_seconds: float = 5.0,
        rss_fetcher: Callable[[str], list[str]] | None = None,
        weather_fetcher: Callable[[str], list[str]] | None = None,
        web_fetcher: Callable[[str], list[str]] | None = None,
    ) -> None:
        self.tools = tools
        self.device = device
        self.settle_seconds = settle_seconds
        self.browser_timeout_seconds = browser_timeout_seconds
        self.rss_fetcher = rss_fetcher or self._fetch_bing_rss
        self.weather_fetcher = weather_fetcher or self._fetch_open_meteo
        self.web_fetcher = web_fetcher or self._fetch_ponychat_web_search

    def run(self, command: QqDeviceCommand) -> WebQueryResult:
        attempts: list[str] = []
        for provider in ("google", "bing"):
            url = self._search_url(command.query, command.kind, provider)
            try:
                self.tools.open_url(self.device, url)
                elements = self._wait_for_results(command.query)
                browser_summaries = self._extract_snippets(elements, command.query)
                supplemental: list[str] = []
                if provider == "google":
                    supplemental = (
                        self.weather_fetcher(command.query)
                        if command.kind == "weather_search"
                        else self.web_fetcher(command.query) or self.rss_fetcher(command.query)
                    )
                elif not browser_summaries:
                    supplemental = self.rss_fetcher(command.query)
                if browser_summaries or supplemental:
                    return WebQueryResult(
                        True,
                        self._format_message(command, browser_summaries, supplemental, url),
                        f"已综合 {provider} 浏览器搜索与联网摘要",
                        url,
                    )
                attempts.append(f"{provider} 未提供可读取的结果摘要")
            except Exception as exc:
                attempts.append(f"{provider}: {type(exc).__name__}: {exc}")
            self.tools.press_button(self.device, "HOME")
            self._settle()
        fallback_url = self._search_url(command.query, command.kind, "google")
        return WebQueryResult(False, "", "；".join(attempts), fallback_url)

    def _wait_for_results(self, query: str) -> list[ScreenElement]:
        deadline = time.monotonic() + self.browser_timeout_seconds
        latest: list[ScreenElement] = []
        while time.monotonic() < deadline:
            self._settle()
            latest = self.tools.list_elements(self.device)
            if len(self._extract_snippets(latest, query)) >= 2:
                return latest
        return latest

    def _settle(self) -> None:
        if self.settle_seconds:
            time.sleep(self.settle_seconds)

    @classmethod
    def _extract_snippets(cls, elements: list[ScreenElement], query: str) -> list[str]:
        candidates: list[tuple[int, int, str]] = []
        seen: set[str] = set()
        normalized_query = query.strip().casefold()
        for element in elements:
            for value in element.strings:
                content = " ".join(value.split()).strip()
                normalized = content.casefold()
                if not content or normalized == normalized_query or content in cls._BROWSER_NOISE:
                    continue
                if any(part in normalized for part in cls._BROWSER_NOISE_PARTS):
                    continue
                if len(content) < 2 or content.startswith(("google.com/search?", "bing.com/search?")):
                    continue
                if normalized in seen:
                    continue
                seen.add(normalized)
                candidates.append((element.y, element.x, content))
        candidates.sort(key=lambda item: (item[0], item[1]))
        selected: list[str] = []
        total = 0
        for _, _, content in candidates:
            clipped = content[:180]
            if total + len(clipped) > 650:
                break
            selected.append(clipped)
            total += len(clipped)
            if len(selected) >= 10:
                break
        return selected

    @staticmethod
    def _fetch_bing_rss(query: str) -> list[str]:
        url = (
            "https://www.bing.com/search?format=rss&mkt=zh-CN&setlang=zh-hans"
            f"&q={quote_plus(query)}"
        )
        request = Request(url, headers={"User-Agent": "PonyChat-Companion/0.1"})
        with urlopen(request, timeout=15) as response:
            payload = response.read()
        root = ElementTree.fromstring(payload)
        results: list[str] = []
        total = 0
        for item in root.findall(".//item"):
            title = BrowserWebQueryWorkflow._plain_text(item.findtext("title") or "")
            link = (item.findtext("link") or "").strip()
            description = BrowserWebQueryWorkflow._plain_text(item.findtext("description") or "")
            if not title or not link:
                continue
            if not BrowserWebQueryWorkflow._is_relevant(query, f"{title} {description}"):
                continue
            summary = f"{title}\n{description[:180]}\n{link}" if description else f"{title}\n{link}"
            if total + len(summary) > 650:
                break
            results.append(summary)
            total += len(summary)
            if len(results) >= 4:
                break
        return results

    @staticmethod
    def _fetch_ponychat_web_search(query: str) -> list[str]:
        workspace_root = Path(__file__).resolve().parents[3]
        root_text = str(workspace_root)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
        from Backend.chat_modules.smart_router import run_web_search

        summary = asyncio.run(run_web_search(query, debug_mode="companion_web_query"))
        lines: list[str] = []
        total = 0
        for raw in summary.splitlines():
            content = raw.strip()
            if not content:
                continue
            clipped = content[:220]
            if total + len(clipped) > 650:
                break
            lines.append(clipped)
            total += len(clipped)
            if len(lines) >= 8:
                break
        return lines

    @staticmethod
    def _fetch_open_meteo(query: str) -> list[str]:
        location = re.sub(
            r"(?:今天|明天|后天|现在|当前|未来\s*\d+\s*天|的|天气|气温|预报|怎么样|如何)",
            " ",
            query,
        )
        location = " ".join(location.split()).strip() or query.strip()
        geocode_url = (
            "https://geocoding-api.open-meteo.com/v1/search?count=1&language=zh&format=json"
            f"&name={quote_plus(location)}"
        )
        places = BrowserWebQueryWorkflow._read_json(geocode_url).get("results") or []
        if not places:
            return []
        place = places[0]
        forecast_url = (
            "https://api.open-meteo.com/v1/forecast?forecast_days=3&timezone=auto"
            "&temperature_unit=celsius"
            "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
            f"&latitude={place['latitude']}&longitude={place['longitude']}"
        )
        forecast = BrowserWebQueryWorkflow._read_json(forecast_url)
        current = forecast.get("current") or {}
        daily = forecast.get("daily") or {}
        name = " ".join(filter(None, (place.get("name"), place.get("admin1"), place.get("country"))))
        condition = BrowserWebQueryWorkflow._weather_condition(current.get("weather_code"))
        lines = [
            f"{name}：{condition}，{current.get('temperature_2m', '--')}°C，"
            f"体感 {current.get('apparent_temperature', '--')}°C，"
            f"风速 {current.get('wind_speed_10m', '--')} km/h",
        ]
        dates = daily.get("time") or []
        highs = daily.get("temperature_2m_max") or []
        lows = daily.get("temperature_2m_min") or []
        rain = daily.get("precipitation_probability_max") or []
        count = min(3, len(dates), len(highs), len(lows), len(rain))
        for index in range(count):
            lines.append(
                f"{dates[index]}：{lows[index]}–{highs[index]}°C，最高降雨概率 {rain[index]}%"
            )
        lines.append("数据来源：https://open-meteo.com/")
        return lines

    @staticmethod
    def _read_json(url: str) -> dict:
        request = Request(url, headers={"User-Agent": "PonyChat-Companion/0.1"})
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _weather_condition(code) -> str:
        descriptions = {
            0: "晴", 1: "大部晴朗", 2: "多云", 3: "阴",
            45: "雾", 48: "雾凇", 51: "小毛毛雨", 53: "毛毛雨", 55: "强毛毛雨",
            61: "小雨", 63: "中雨", 65: "大雨", 71: "小雪", 73: "中雪", 75: "大雪",
            80: "阵雨", 81: "中等阵雨", 82: "强阵雨", 95: "雷暴",
        }
        return descriptions.get(code, "天气状况未知")

    @staticmethod
    def _is_relevant(query: str, content: str) -> bool:
        stop = set("的了和与在一下帮我从网上网络搜索查询找看看文章资料视频网页")
        query_chars = {char.casefold() for char in query if char.isalnum() and char not in stop}
        if not query_chars:
            return True
        normalized = content.casefold()
        return sum(char in normalized for char in query_chars) >= min(2, len(query_chars))

    @staticmethod
    def _plain_text(value: str) -> str:
        return " ".join(unescape(re.sub(r"<[^>]+>", " ", value)).split())

    @staticmethod
    def _format_message(
        command: QqDeviceCommand,
        browser_summaries: list[str],
        supplemental: list[str],
        url: str,
    ) -> str:
        labels = {
            "weather_search": "天气查询",
            "article_search": "文章与资料查询",
            "video_search": "视频查询",
            "web_search": "联网查询",
        }
        label = labels.get(command.kind, "联网查询")
        sections = [f"{label}：{command.query}"]
        if browser_summaries:
            sections.append(
                "【浏览器可见结果】\n"
                + "\n".join(f"• {snippet}" for snippet in browser_summaries)
            )
        else:
            sections.append("【浏览器】已在设备中打开搜索结果")
        if supplemental:
            sections.append(
                "【综合摘要】\n"
                + "\n".join(f"• {snippet}" for snippet in supplemental)
            )
        sections.append(f"完整结果：{url}")
        return BrowserWebQueryWorkflow._normalize_celsius("\n\n".join(sections))[:1800]

    @staticmethod
    def _normalize_celsius(text: str) -> str:
        def convert(match: re.Match) -> str:
            celsius = (float(match.group(1)) - 32.0) * 5.0 / 9.0
            rounded = round(celsius, 1)
            value = str(int(rounded)) if rounded.is_integer() else f"{rounded:.1f}"
            return f"{value}°C"

        normalized = re.sub(
            r"(-?\d+(?:\.\d+)?)\s*(?:°\s*F|℉|华氏度?)",
            convert,
            text,
            flags=re.I,
        )
        return re.sub(
            r"华氏\s*(-?\d+(?:\.\d+)?)\s*度?",
            convert,
            normalized,
            flags=re.I,
        )

    @staticmethod
    def _search_url(query: str, kind: str, provider: str) -> str:
        encoded = quote_plus(query)
        if provider == "bing":
            if kind == "video_search":
                return f"https://www.bing.com/videos/search?q={encoded}"
            return f"https://www.bing.com/search?q={encoded}"
        if kind == "video_search":
            return f"https://www.google.com/search?tbm=vid&q={encoded}"
        return f"https://www.google.com/search?q={encoded}"
