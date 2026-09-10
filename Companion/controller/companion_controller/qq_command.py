from __future__ import annotations

import re
from dataclasses import dataclass

from .image_share_task import BrowserImageToQqTask, parse_browser_image_to_qq_task


@dataclass(frozen=True)
class QqDeviceCommand:
    kind: str
    query: str
    image_share_task: BrowserImageToQqTask | None = None


_IMAGE_SEARCH_PATTERNS = (
    re.compile(
        r"^(?:请|麻烦)?(?:帮我)?(?:从|在)?(?:网上|网络上|浏览器里|浏览器中|浏览器)?"
        r"(?:找|搜|搜索|查找)(?:一下)?(?P<query>.+?)(?:的)?(?:图片|照片|图)(?:吧)?[。！! ]*$",
        re.I,
    ),
    re.compile(
        r"^(?:请|麻烦)?(?:帮我)?(?:打开)?(?:网上|网络上的)(?P<query>.+?)(?:的)?"
        r"(?:图片|照片|图)(?:搜索结果)?(?:吧)?[。！! ]*$",
        re.I,
    ),
)

_SEARCH_VERBS = ("找", "搜", "搜索", "查", "查询", "查找", "看看", "看一下", "了解")
_NETWORK_MARKERS = ("网上", "网络上", "互联网上", "联网", "浏览器", "网页", "网站")
_LIVE_MARKERS = (
    "天气", "气温", "降雨", "空气质量", "新闻", "资讯", "热搜", "股价", "汇率",
    "航班", "列车", "路况", "比分", "票房",
)
_CONTENT_MARKERS = ("文章", "资料", "新闻", "资讯", "网页", "网站", "视频", "影片")
_QUESTION_MARKERS = ("怎么样", "多少", "如何", "会不会", "有没有", "多少度", "预报", "吗", "？", "?")
_DEVICE_ACTION_MARKERS = (
    "打开", "关闭", "启动", "退出", "返回", "发送", "发消息", "回复", "分享",
    "播放", "暂停", "继续播放", "设置", "切换", "调高", "调低", "调整",
    "安装", "下载", "创建", "删除", "拍照", "录像", "截图", "导航",
    "拨打", "建立提醒", "设个提醒", "设闹钟", "滑动", "点击",
)
_DEVICE_SCOPE_MARKERS = (
    "QQ", "qq", "微信", "浏览器", "网页", "网站", "应用", "软件", "相机",
    "相册", "视频", "音乐", "屏幕", "音量", "亮度", "WiFi", "wifi", "蓝牙",
    "设置", "联系人", "消息", "图片", "文件", "地图", "闹钟", "提醒",
)


def parse_qq_device_command(instruction: str) -> QqDeviceCommand | None:
    text = instruction.strip()
    if not text:
        return None
    image_share = parse_browser_image_to_qq_task(text)
    if image_share is not None:
        return QqDeviceCommand("image_share_to_qq", image_share.query, image_share)
    for pattern in _IMAGE_SEARCH_PATTERNS:
        match = pattern.fullmatch(text)
        if not match:
            continue
        query = match.group("query").strip(" ，,;；:：\"“”").removesuffix("的").strip()
        if query:
            return QqDeviceCommand("image_search", query)
    if not _looks_like_web_query(text):
        if _looks_like_general_device_command(text):
            return QqDeviceCommand("general_device", text)
        return None
    query = _extract_web_query(text)
    if not query:
        return None
    return QqDeviceCommand(_web_query_kind(query), query)


def _looks_like_web_query(text: str) -> bool:
    has_verb = any(word in text for word in _SEARCH_VERBS)
    has_scope = any(word in text for word in (*_NETWORK_MARKERS, *_LIVE_MARKERS, *_CONTENT_MARKERS))
    asks_live_question = any(word in text for word in _LIVE_MARKERS) and any(
        word in text for word in _QUESTION_MARKERS
    )
    return (has_verb and has_scope) or asks_live_question


def _extract_web_query(text: str) -> str:
    query = text.strip().strip("。！!？? ")
    query = re.sub(r"^(?:请|麻烦)?(?:帮我)?", "", query).strip()
    query = re.sub(
        r"^(?:从|在)?(?:网上|网络上|互联网上|联网|浏览器里|浏览器中|浏览器)?",
        "",
        query,
    ).strip()
    query = re.sub(r"^(?:搜索|查找|查询|看一下|看看|了解|找|搜|查)(?:一下)?", "", query).strip()
    return query.strip(" ，,;；:：\"“”")


def _web_query_kind(query: str) -> str:
    if any(marker in query for marker in ("天气", "气温", "降雨", "空气质量")):
        return "weather_search"
    if any(marker in query for marker in ("视频", "影片")):
        return "video_search"
    if any(marker in query for marker in ("文章", "资料", "新闻", "资讯", "网页", "网站")):
        return "article_search"
    return "web_search"


def _looks_like_general_device_command(text: str) -> bool:
    has_action = any(marker in text for marker in _DEVICE_ACTION_MARKERS)
    has_scope = any(marker in text for marker in _DEVICE_SCOPE_MARKERS)
    message_pattern = re.search(r"给.+(?:发|回复).+(?:消息|信息|图片|文件)", text)
    return (has_action and has_scope) or message_pattern is not None
