# 静态页面响应（含缓存破坏）
# 约定：js/ 下 import 的 URL 一律使用 ?v=__CACHE_VERSION__，禁止写死 ?v= 具体值，否则同一文件会被请求成多个 URL、出现多版本并行。
import os
import re
import time
from fastapi.responses import Response, FileResponse

from .config import FRONTEND_ROOT

# 每次后端启动生成一个版本号，用于替换 index.html 里所有 ?v=xxx，避免浏览器用旧 JS/CSS 缓存
CACHE_VERSION = str(int(time.time()))

# 占位符：在 JS 的 import URL 中写 ?v=__CACHE_VERSION__，后端下发时替换为 CACHE_VERSION，保证与 HTML 中 script 的 ?v= 一致，同一文件只存在一个版本
CACHE_VERSION_PLACEHOLDER = "__CACHE_VERSION__"


def js_content_with_cache_bust(content: str) -> str:
    """对 JS 文件内容做缓存版本替换，使 import 的 ?v=__CACHE_VERSION__ 与本次启动版本一致。"""
    if CACHE_VERSION_PLACEHOLDER not in content:
        return content
    return content.replace(CACHE_VERSION_PLACEHOLDER, CACHE_VERSION)


def index_html_with_cache_bust(project_root: str | None = None):
    """
    读取 html/index.html，把其中所有 ?v=... 替换成本次启动的 CACHE_VERSION，返回 Response。
    这样每次重启后端，前端请求到的 script/link 的 URL 都会变，自然跳过旧缓存。
    """
    root = project_root or FRONTEND_ROOT
    file_path = os.path.join(root, "html", "index.html")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return FileResponse(file_path)
    content = re.sub(r"\?v=[^\"']+", f"?v={CACHE_VERSION}", content)
    return Response(
        content=content.encode("utf-8"),
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache", "ETag": f'W/"cb_{CACHE_VERSION}"'},
    )
